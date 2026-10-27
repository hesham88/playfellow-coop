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

from playfellow_coop import _http, fastpath
from playfellow_coop.budget import DailyBudget

ENDPOINTS = {"sam": "https://api.meta.ai/v1"}  # pinned on purpose
MODEL = "sam-3.1"
USD_PER_IMAGE = 2.50 / 1000  # the published price: $2.50 per 1,000 images
DEFAULT_PROMPTS = {"me": "the player character", "reward": "coin or collectible item", "hazard": "hazard or enemy", "door": "door or exit"}
BOX = re.compile(r"<\|box;x1=([\d.]+);y1=([\d.]+);x2=([\d.]+);y2=([\d.]+);w=([\d.]+);h=([\d.]+)\|>")
CELL_CHANGE = 20  # grey-level change (0-255) that makes one thumbnail cell "different"
CELLS_NEEDED = 2  # a mover leaves one cell and enters another, so two different cells mean "something moved"


def _signature(image: Image.Image) -> bytes:
    return image.convert("L").resize((32, 32)).tobytes()


def _changed(a: bytes | None, b: bytes) -> bool:
    """True when the picture differs enough from the last keyframe: at least CELLS_NEEDED of its 32x32 cells changed."""
    return a is None or fastpath.changed_cells(a, b, CELL_CHANGE) >= CELLS_NEEDED  # Rust when built, the same count in Python otherwise


def mark_image(image: Image.Image, marker: Callable[[Image.Image], list[Mark]]) -> tuple[Image.Image, str]:
    """The picture the brain sees, with the numbered marks drawn on it, and the words that explain them (the engine's own steps)."""
    marks = marker(image)
    me = next((m for m in marks if m.kind == "me"), None)
    labelled = label_marks([m for m in marks if m.kind != "me"], me)
    if not labelled:
        return image, ""
    return draw_marks(image, labelled), legend(labelled)


def parse_boxes(text: str) -> list[tuple[tuple[float, float, float, float], tuple[float, float]]]:
    """Every box in a SAM answer as ((x1, y1, x2, y2), (width, height))."""
    out = []
    for match in BOX.finditer(text or ""):
        x1, y1, x2, y2, w, h = (float(v) for v in match.groups())
        out.append(((x1, y1, x2, y2), (w, h)))
    return out


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
                 client: httpx.Client | None = None, clock: Callable[[], float] = time.perf_counter):
        self._key = api_key
        self.prompts = dict(prompts or DEFAULT_PROMPTS)
        self.budget = budget
        self._client = client or _http.new_client()
        self._clock = clock
        self._signature: bytes | None = None
        self._marks: list[Mark] = []
        self.calls = 0  # requests attempted
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
        if self.budget is not None and self.budget.exhausted():
            self.last_error = BrainError("token_cap_day")  # nothing is sent
            return list(self._marks)
        buffer = io.BytesIO()
        image.convert("RGB").save(buffer, format="PNG")  # the picture is encoded ONCE, then shared by every phrase
        data = base64.standard_b64encode(buffer.getvalue()).decode("ascii")
        started = self._clock()
        marks: list[Mark] = []
        failure: BrainError | None = None
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
        return list(marks)

    def _find(self, kind: str, phrase: str, data: str) -> list[Mark]:
        body = {"model": MODEL, "input": [{"role": "user", "content": [
            {"type": "input_text", "text": phrase}, {"type": "input_image", "image_url": f"data:image/png;base64,{data}"}]}]}
        started = self._clock()
        with self._lock:
            self.calls += 1
        try:
            response = _http.post(self._client, ENDPOINTS["sam"] + "/responses", self._key, body)
        except BrainError:
            with self._lock:
                self.failed_calls += 1  # never reached the service: nothing is charged
            raise
        self.latencies.append(self._clock() - started)
        if 200 <= response.status_code < 300:
            if self.budget is not None:
                self.budget.record_cost(USD_PER_IMAGE)  # charged only when the service really answered
        else:
            with self._lock:
                self.failed_calls += 1  # a wrong key (401), a rate limit (429) or a server error is not billed, so not charged here
            _http.check_status(response.status_code)
        try:
            text = answer_text(response.json())
        except ValueError:
            raise BrainError("brain_trouble", detail="the answer was not in the expected shape") from None
        return [mark_from_box(kind, box, size) for box, size in parse_boxes(text)]
