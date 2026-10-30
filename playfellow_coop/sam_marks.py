"""SAM 3.1 marks: ask Meta's segmentation model where things are, and turn the answer into the engine's own marks.

This is part of the closed loop (see -> mark -> act -> check), not a screenshot describer: the marks are drawn on the picture the
brain sees, the engine's label_marks/draw_marks/legend explain them, and the brain's chosen key goes through the controls card.
Only the centre of each box is used. Keyframes only: SAM is asked again only when the picture has changed enough, and every
request is gated by the daily budget. A marker failure never stops play: the last good marks are reused.

UNVERIFIED until the first capped real call: the response JSON wrapper. The box tokens follow the format in Meta's docs
(`<|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>`); the wrapper is read tolerantly (`output_text`, or the text of `output[*].content[*]`)."""
from __future__ import annotations

import base64
import io
import re
import threading
import time
from concurrent.futures import ThreadPoolExecutor
from typing import Callable

import httpx
from PIL import Image

from brain import BrainError
from grounding import Mark, draw_marks, label_marks, legend, mark_from_box

from playfellow_coop import _http, fastpath, sam_protocol
from playfellow_coop.budget import DailyBudget

ENDPOINTS = {"sam": "https://api.meta.ai/v1"}  # pinned on purpose
MODEL = "sam-3.1"
USD_PER_IMAGE = 2.50 / 1000  # the published price: $2.50 per 1,000 images
# Credit day, 27 Oct, on the real service: SAM answers short, concrete, VISIBLE descriptions ("blue circle", "yellow circle", "key", "brown box") and answers
# nothing to game words ("coin", "player", "door", "wall") or to broad phrases ("the player character", "coin or collectible item", "door or exit").
# These three are checked live on the Practice Arena; the hazard phrase is not yet (that arena has no hazard). For another game the phrases come from its
# own look, never from this table (see the plan: the planner names what it sees, SAM finds it).
DEFAULT_PROMPTS = {"me": "blue circle", "reward": "yellow circle", "hazard": "red circle", "door": "brown box"}
MIN_BOX = 0.015  # a box shorter than this share of the picture's shorter side is a speck (the door's knob came back as a "yellow circle"): dropped
MIN_CONFIDENCE = 0.30  # a box the model itself is less than this sure of is dropped (only when the answer carries a confidence; none means keep)
CELL_CHANGE = 20  # grey-level change (0-255) that makes one thumbnail cell "different"
CELLS_NEEDED = 2  # a mover leaves one cell and enters another, so two different cells mean "something moved"


def _signature(image: Image.Image) -> bytes:
    return image.convert("L").resize((32, 32)).tobytes()


def _changed(a: bytes | None, b: bytes) -> bool:
    """True when the picture differs enough from the last keyframe: at least CELLS_NEEDED of its 32x32 cells changed."""
    return a is None or fastpath.changed_cells(a, b, CELL_CHANGE) >= CELLS_NEEDED  # Rust when built, the same count in Python otherwise


def mark_image_full(image: Image.Image, marker: Callable[[Image.Image], list[Mark]]) -> tuple[Image.Image, str, list[Mark]]:
    """The marked picture, the words that explain the marks, and the labelled marks themselves (ME first)."""
    marks = marker(image)
    me = next((m for m in marks if m.kind == "me"), None)
    labelled = label_marks([m for m in marks if m.kind != "me"], me)
    if not labelled:
        return image, "", []
    return draw_marks(image, labelled), legend(labelled), labelled


def mark_image(image: Image.Image, marker: Callable[[Image.Image], list[Mark]]) -> tuple[Image.Image, str]:
    """The picture the brain sees, with the numbered marks drawn on it, and the words that explain them (the engine's own steps)."""
    marked, words, _ = mark_image_full(image, marker)
    return marked, words


TOKEN = re.compile(r"<\|([A-Za-z][A-Za-z0-9_.-]*)(?:;([^|<>]*))?\|>")  # a payload never holds < > or |, so a token ends at the first |>
INT = re.compile(r"-?\d+")
UINT = re.compile(r"\d+")


def parse_records(text: str) -> list[dict]:
    """Every box token in a SAM answer, read the way the published protocol says (github.com/meta-models/meta-sam, protocol/sam3.md): fields are found by
    NAME after splitting on ';' (never by searching for 'x1=' in the text, because a mask payload may contain letters and '='), their order does not
    matter, a field without a value is ignored, x2 and y2 are INCLUSIVE in the source so the half-open right and bottom edges are x2+1 and y2+1, w and h
    are the picture's size, and an optional `c` is the model's confidence. A token with a missing or malformed required field is skipped, never guessed."""
    records = []
    for match in TOKEN.finditer(text or ""):
        if match.group(1) != "box":
            continue
        fields = {}
        for part in (match.group(2) or "").split(";"):
            key, sep, value = part.partition("=")
            if sep and key.strip():
                fields[key.strip()] = value.strip()
        try:
            if not all(INT.fullmatch(fields.get(k, "")) for k in ("x1", "y1", "x2", "y2")) or not all(UINT.fullmatch(fields.get(k, "")) for k in ("w", "h")):
                continue
            x1, y1, x2, y2, w, h = (int(fields[k]) for k in ("x1", "y1", "x2", "y2", "w", "h"))
        except ValueError:
            continue
        if w <= 0 or h <= 0 or not (0 <= x1 <= x2 < w and 0 <= y1 <= y2 < h):
            continue  # the whole inclusive box must lie inside the picture
        confidence = None
        if "c" in fields:
            try:
                confidence = float(fields["c"])
            except ValueError:
                confidence = None
        records.append({"box": (float(x1), float(y1), float(x2 + 1), float(y2 + 1)), "size": (float(w), float(h)), "confidence": confidence})
    return records


def parse_boxes(text: str) -> list[tuple[tuple[float, float, float, float], tuple[float, float]]]:
    """Every box in a SAM answer as ((left, top, right, bottom), (width, height)) with the half-open right and bottom edges."""
    return [(r["box"], r["size"]) for r in parse_records(text)]


def big_enough(boxes: list) -> list:
    """Drop specks: boxes whose width or height is under MIN_BOX of the picture's shorter side."""
    return [(box, size) for box, size in boxes if min(box[2] - box[0], box[3] - box[1]) >= MIN_BOX * min(size)]


def answer_text(body: object) -> str:
    """The text of a Responses-style answer: `output_text`, or the text parts of `output[*].content[*]`."""
    if not isinstance(body, dict):
        return ""
    if isinstance(body.get("output_text"), str):
        return body["output_text"]
    parts = []
    for item in body.get("output") or []:
        for part in (item.get("content") or []) if isinstance(item, dict) else []:
            if isinstance(part, dict) and isinstance(part.get("text"), str):
                parts.append(part["text"])
    return "\n".join(parts)


class SamMarker:
    """marker(image) -> list[Mark]: the engine's `Parts.marker` shape."""

    def __init__(self, api_key: str, prompts: dict[str, str] | None = None, budget: DailyBudget | None = None,
                 client: httpx.Client | None = None, clock: Callable[[], float] = time.perf_counter, tracer=None, tracker=None):
        self._key = api_key
        self.tracer = tracer  # an optional pf-trace/1 writer
        self.tracker = tracker  # an optional playfellow_coop.tracking.Tracker: follows what SAM found between SAM calls
        self._found: list = []  # (kind, pixel box) of the last keyframe, handed to the tracker
        self.tracked_pictures = 0  # pictures answered by the tracker with no SAM request
        self._png_bytes = 0
        self.prompts = dict(prompts or DEFAULT_PROMPTS)
        self.budget = budget
        self._client = client or _http.new_client()
        self._clock = clock
        self._signature: bytes | None = None
        self._marks: list[Mark] = []
        self.calls = 0  # requests attempted
        self.last_confidences: list[float | None] = []  # the model's own confidence for each box it last kept (None: the answer had none)
        self.failed_calls = 0  # attempts that did not end in a 2xx answer (never charged)
        self._lock = threading.Lock()
        self.keyframe_latencies: list[float] = []  # seconds for a whole keyframe (all phrases together)
        self.last_error: BrainError | None = None
        self.latencies: list[float] = []  # seconds per request, measured here

    def __repr__(self) -> str:
        return f"<SamMarker kinds={sorted(self.prompts)!r}>"

    def close(self) -> None:
        self._client.close()

    def __call__(self, image: Image.Image) -> list[Mark]:
        signature = _signature(image)
        if not _changed(self._signature, signature):
            return list(self._marks)  # the picture has not changed: no request, no cost
        if self.tracker is not None and self.tracker.tracks and self._marks:
            self.tracker.update(image)
            if not self.tracker.needs_sam():  # every tracked thing still matches well: the marks move with it, no request, no cost
                self.tracked_pictures += 1
                self._marks = [mark_from_box(kind, box, image.size) for kind, box in self.tracker.boxes()]
                self._signature = signature
                return list(self._marks)
        if self.budget is not None and self.budget.exhausted():
            self.last_error = BrainError("token_cap_day")  # nothing is sent
            return list(self._marks)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")  # the picture is encoded ONCE, then shared by every phrase
        self._png_bytes = len(buffer.getvalue())
        data = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
        started = self._clock()
        marks: list[Mark] = []
        failure: BrainError | None = None
        self._found = []
        with ThreadPoolExecutor(max_workers=max(1, len(self.prompts))) as pool:  # the phrases are asked at the same time
            futures = [pool.submit(self._find, kind, phrase, data) for kind, phrase in self.prompts.items()]
            for future in futures:
                try:
                    marks += future.result()
                except BrainError as error:
                    failure = failure or error
        self.keyframe_latencies.append(self._clock() - started)
        if failure is not None:
            self.last_error = failure  # a helper failure never stops play: keep the last good marks
            return list(self._marks)
        self.last_error = None
        self._signature, self._marks = signature, marks
        if self.tracker is not None:
            self.tracker.anchor(image, list(self._found))  # SAM confirmed the scene: keep each thing's look and its identity for the next pictures
        return list(marks)

    def _find(self, kind: str, phrase: str, data: str) -> list[Mark]:
        body = {"model": MODEL, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": phrase}, {"type": "input_image", "image_url": f"data:image/png;base64,{data}"}]}],
            "metadata": sam_protocol.request_metadata()}  # one_bit masks (several times smaller, we only need the boxes) and a confidence on every record; values are strings
        started = self._clock()
        with self._lock:
            self.calls += 1
        try:
            response = _http.post(self._client, ENDPOINTS["sam"] + "/responses", self._key, body)
        except BrainError as error:
            with self._lock:
                self.failed_calls += 1  # never reached the service: nothing is charged
            self._trace(started, error=error.key, parse={"valid": False})
            raise
        self.latencies.append(self._clock() - started)
        if 200 <= response.status_code < 300:
            if self.budget is not None:
                self.budget.record_cost(USD_PER_IMAGE)  # charged only when the service really answered
        else:
            with self._lock:
                self.failed_calls += 1  # a wrong key (401), a rate limit (429) or a server error is not billed, so not charged here
            self._trace(started, status=response.status_code, parse={"valid": False})
            _http.check_status(response.status_code)
        try:
            text = answer_text(response.json())
        except ValueError:
            self._trace(started, status=response.status_code, cost_usd=USD_PER_IMAGE, parse={"valid": False})
            raise BrainError("brain_trouble", detail="the answer was not in the expected shape") from None
        records = [r for r in sam_protocol.parse(text, strict=True, media="image").records if r.confidence is None or r.confidence >= MIN_CONFIDENCE]
        boxes = big_enough([((float(r.box.left), float(r.box.top), float(r.box.right), float(r.box.bottom)), (float(r.box.width), float(r.box.height))) for r in records])
        self.last_confidences = [r.confidence for r in records]
        self._trace(started, status=response.status_code, cost_usd=USD_PER_IMAGE, parse={"valid": bool(boxes), "boxes": len(boxes)})
        with self._lock:
            self._found += [(kind, box) for box, _ in boxes]
        return [mark_from_box(kind, box, size) for box, size in boxes]

    def _trace(self, started: float, **fields) -> None:
        if self.tracer is not None:
            self.tracer.request("marks", model=MODEL, images=1, image_bytes=self._png_bytes, request_ms=(self._clock() - started) * 1000.0,
                                **fields)
