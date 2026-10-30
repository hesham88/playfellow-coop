"""SAM on a short clip instead of many single pictures: record recent frames, encode an MP4, upload it once, stream the answer, parse it frame by frame, delete the file.

Why: video is billed $0.20 per 1,000 frames with a 50-frame minimum per request, a picture $2.50 per 1,000, so one clip request costs the same $0.01 as four pictures and is cheaper from
five pictures on (`sam_protocol.cheaper_mode`). SAM also follows each object through the clip, so ids stay the same across frames (they are only stable inside ONE response).

Pieces, each testable without the network:
  FrameBuffer          the last N frames of the game, newest last
  encode_mp4           frames -> MP4 (MPEG-4 or H.264 are accepted by the service; WebM and VP9 are not). Needs OpenCV; without it `NoEncoder` says so plainly
  upload / delete      POST /files with purpose user_data and an expiry set BEFORE the file part, DELETE /files/{id}
  StreamReader         turns the server-sent events of a streamed answer into frames as they complete, and keeps `usage.video_frames_processed`
  SamVideo.track       upload, stream, parse, delete (always, even when the answer fails)
"""
from __future__ import annotations

import json
import re
import tempfile
from collections import deque
from dataclasses import dataclass, field
from pathlib import Path
from typing import Iterable, Iterator

import httpx

from brain import BrainError
from playfellow_coop import _http
from playfellow_coop.sam_protocol import MAX_VIDEO_FRAMES, MIN_BILLED_VIDEO_FRAMES, Parsed, build_object_prompt, parse, request_metadata, sam_cost
from playfellow_coop.sam_protocol import PromptObject, StrictReader

BASE = "https://api.meta.ai/v1"
MODEL = "sam-3.1"
FILE_ID = re.compile(r"^[A-Za-z0-9_-]{3,128}$")
EXPIRES_MIN, EXPIRES_MAX = 3600, 2592000


class NoEncoder(RuntimeError):
    """No video encoder is installed here (the plain message says what to install)."""


class FrameBuffer:
    def __init__(self, max_frames: int = MIN_BILLED_VIDEO_FRAMES):
        self._frames: deque = deque(maxlen=max(1, min(max_frames, MAX_VIDEO_FRAMES)))

    def push(self, frame) -> None:
        self._frames.append(frame)

    def frames(self) -> list:
        return list(self._frames)

    def __len__(self) -> int:
        return len(self._frames)


def encode_mp4(frames: list, path: Path, fps: float = 10.0) -> Path:
    """Write `frames` (RGB arrays or Pillow images, all one size) to an MP4 at `path`. Raises NoEncoder when OpenCV is not installed or cannot write MPEG-4."""
    import numpy as np
    try:
        import cv2
    except ImportError:
        raise NoEncoder("video clips need OpenCV: pip install opencv-python-headless (until then SAM is asked about single pictures)") from None
    if not frames:
        raise ValueError("a clip needs at least one frame")
    arrays = [np.asarray(f.convert("RGB")) if hasattr(f, "convert") else np.asarray(f) for f in frames]
    height, width = arrays[0].shape[:2]
    if any(a.shape[:2] != (height, width) for a in arrays):
        raise ValueError("all frames of a clip must have the same size")
    writer = cv2.VideoWriter(str(path), cv2.VideoWriter_fourcc(*"mp4v"), float(fps), (width, height))
    if not writer.isOpened():
        raise NoEncoder("this OpenCV build cannot write MPEG-4 video")
    try:
        for array in arrays:
            writer.write(cv2.cvtColor(array, cv2.COLOR_RGB2BGR))
    finally:
        writer.release()
    return path


def upload(client: httpx.Client, key: str, path: Path, expires_seconds: int = EXPIRES_MIN, base: str = BASE) -> str:
    """Upload a clip for later requests and return its file id. The file expires by itself (1 hour to 30 days), so nothing lingers if a delete is missed. `purpose` and the
    expiry fields go first and the file last, so the service can start working before the whole body has arrived."""
    if not EXPIRES_MIN <= expires_seconds <= EXPIRES_MAX:
        raise ValueError(f"expires_seconds must be between {EXPIRES_MIN} and {EXPIRES_MAX}")
    with open(path, "rb") as handle:
        try:
            response = client.post(base + "/files", headers={"Authorization": f"Bearer {key}"},
                                   data={"purpose": "user_data", "expires_after[anchor]": "created_at", "expires_after[seconds]": str(expires_seconds)},
                                   files={"file": (Path(path).name, handle, "video/mp4")})
        except httpx.TimeoutException:
            raise BrainError("busy", retry=True, wait_seconds=5) from None
        except httpx.HTTPError:
            raise BrainError("offline", retry=True, wait_seconds=5) from None
    _http.check_status(response.status_code)
    try:
        file_id = response.json()["id"]
    except (ValueError, KeyError, TypeError):
        raise BrainError("brain_trouble", detail="the upload answer had no file id") from None
    if not isinstance(file_id, str) or not FILE_ID.match(file_id):
        raise BrainError("brain_trouble", detail="the upload answer had an unusable file id")
    return file_id


def delete(client: httpx.Client, key: str, file_id: str, base: str = BASE) -> bool:
    """Remove an uploaded file. False (never an exception) when it could not be removed: the expiry is the safety net."""
    if not FILE_ID.match(file_id):
        return False
    try:
        return client.delete(f"{base}/files/{file_id}", headers={"Authorization": f"Bearer {key}"}).status_code < 300
    except httpx.HTTPError:
        return False


def video_request(prompt: str, file_id: str, direction: str | None = None) -> dict:
    """The streamed segmentation request for a clip: one user message with the prompt and the uploaded video."""
    return {"model": MODEL, "stream": True, "metadata": request_metadata(direction=direction),
            "input": [{"type": "message", "role": "user", "content": [{"type": "input_text", "text": prompt}, {"type": "input_video", "file_id": file_id}]}]}


@dataclass
class StreamReader:
    """Reads the server-sent events of a streamed answer. `lines` are the raw text lines of the stream. Complete lines (one per frame) are handed out as soon as they end."""
    text: str = ""
    frames_billed: int | None = None
    status: str = "in_progress"
    failed: str = ""
    _pending: str = field(default="", repr=False)

    def feed(self, line: str) -> Iterator[Parsed]:
        line = line.strip()
        if not line.startswith("data:"):
            return
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError:
            return
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            self.text += event.get("delta") or ""
            self._pending += event.get("delta") or ""
            while "\n" in self._pending:
                done, self._pending = self._pending.split("\n", 1)
                if done.strip():
                    yield parse(done)
        elif kind in ("response.completed", "response.incomplete"):
            response = event.get("response") or {}
            self.status = "completed" if kind == "response.completed" else "incomplete"
            usage = response.get("usage") or {}
            frames = usage.get("video_frames_processed")
            self.frames_billed = frames if isinstance(frames, int) and not isinstance(frames, bool) else None
            if self._pending.strip():
                tail, self._pending = self._pending, ""
                yield parse(tail)
        elif kind in ("response.failed", "error"):
            self.status = "failed"
            error = (event.get("response") or {}).get("error") or event.get("error") or {}
            self.failed = str(error.get("code") or error.get("message") or "failed")[:120]


def read_stream(lines: Iterable[str]) -> tuple[StreamReader, list[Parsed]]:
    reader, frames = StreamReader(), []
    for line in lines:
        frames.extend(reader.feed(line))
    return reader, frames


def _index(value) -> int | None:
    """A lane index: a non-negative whole number (a JSON -0 or 0.0 is 0); anything else is not one."""
    if isinstance(value, bool):
        return None
    if isinstance(value, int):
        return value if value >= 0 else None
    if isinstance(value, float) and value.is_integer() and value >= 0:
        return int(value)
    return None


def _lane_dict(lane: tuple | None) -> dict | None:
    return None if lane is None else {"item_id": lane[0], "output_index": lane[1], "content_index": lane[2]}


class StrictStream:
    """The stream adapter of the published protocol ("Streaming and outcomes"), on official Responses stream events. Exactly one output-text lane (item_id,
    output_index, content_index) is read: another lane, an invalid lane, text after the lane is final, final text that differs from the deltas, or a repeated
    finalizer is a `response_lane` error. `response.output_text.done` and an `output_text` `response.content_part.done` may each finalize the lane once, with the
    same text; a `reasoning_text` part is ignored. Refusals, failed responses and error events are typed terminal errors. A completed or explicitly incomplete
    response needs a final lane; the end of the input without one is an `eof` incomplete outcome. Text goes through `StrictReader` as it arrives."""

    def __init__(self, media: str | None = None):
        self.reader = StrictReader(media)
        self.status = "in_progress"  # completed, incomplete or failed
        self.outcome: dict | None = None
        self.error: dict | None = None
        self.frames_billed: int | None = None
        self.lane: tuple | None = None
        self._deltas = False
        self._text = ""
        self._final: str | None = None
        self._finalizers: set[str] = set()

    @property
    def parsed(self) -> Parsed:
        return self.reader.parsed

    def feed(self, line: str) -> None:
        """One server-sent-events line."""
        line = line.strip()
        if not line.startswith("data:"):
            return
        data = line[5:].strip()
        if data == "[DONE]":
            return
        try:
            event = json.loads(data)
        except ValueError:
            return
        if isinstance(event, dict):
            self.event(event)

    def event(self, event: dict) -> None:
        if self.status != "in_progress":
            return  # nothing counts after a terminal outcome or error
        kind = event.get("type", "")
        if kind == "response.output_text.delta":
            lane = self._lane(event)
            if lane is None:
                return
            if self._final is not None:
                self._lane_error("Output text arrived after its lane was final.", self.lane, lane)
                return
            delta = event.get("delta") if isinstance(event.get("delta"), str) else ""
            self._deltas, self._text = True, self._text + delta
            self.reader.feed(delta)
        elif kind == "response.output_text.done":
            self._finalize("output_text.done", event, event.get("text"))
        elif kind == "response.content_part.done":
            part = event.get("part") if isinstance(event.get("part"), dict) else {}
            if part.get("type") == "refusal":
                self._fail("response_refusal", str(part.get("refusal") if part.get("refusal") is not None else part.get("text", "")))
            elif part.get("type") == "output_text":
                self._finalize("content_part.done", event, part.get("text"))
        elif kind == "response.refusal.delta":
            self._fail("response_refusal", str(event.get("delta", "")))
        elif kind == "response.refusal.done":
            self._fail("response_refusal", str(event.get("refusal", "")))
        elif kind == "response.completed":
            self._terminal({"status": "completed"}, event)
        elif kind == "response.incomplete":
            details = (event.get("response") or {}).get("incomplete_details") or {}
            outcome = {"status": "incomplete", "reason": "response"}
            if isinstance(details.get("reason"), str):
                outcome["detail"] = details["reason"]
            self._terminal(outcome, event)
        elif kind == "response.failed":
            error = (event.get("response") or {}).get("error") or {}
            self._fail("response_failed", str(error.get("message", "")))
        elif kind == "error":
            self._fail("response_error", str(event.get("message", "")))

    def finish(self) -> None:
        """The input ended. Without a terminal event that is an `eof` incomplete outcome; a last line without a newline is still read."""
        if self.status == "in_progress":
            self.reader.finish()
            self.status, self.outcome = "incomplete", {"status": "incomplete", "reason": "eof"}

    def fail_source(self, operation: str) -> None:
        """The event source itself failed (`iterator`, `next` or `return`, the cleanup). A cleanup failure is not skipped, even after a final outcome."""
        if self.error is None:
            self.status, self.outcome = "failed", None
            self.error = {"code": "source_error", "message": f"The Responses event source failed during {operation}.", "source_operation": operation}

    # ---- internals
    def _lane(self, event: dict) -> tuple | None:
        item, out, content = event.get("item_id"), _index(event.get("output_index")), _index(event.get("content_index"))
        if not (isinstance(item, str) and item) or out is None or content is None:
            self._lane_error("The output text event has an invalid lane identity.", None, None)
            return None
        lane = (item, out, content)
        if self.lane is None:
            self.lane = lane
        elif lane != self.lane:
            self._lane_error("The response interleaved multiple output text lanes.", self.lane, lane)
            return None
        return lane

    def _finalize(self, kind: str, event: dict, text) -> None:
        lane = self._lane(event)
        if lane is None:
            return
        if not isinstance(text, str):
            self._lane_error("The final output text is missing.", self.lane, lane)
        elif kind in self._finalizers:
            self._lane_error("The output text lane was finalized twice by the same event type.", self.lane, lane)
        elif self._final is not None:
            if text != self._final:
                self._lane_error("A second final output text differs from the first.", self.lane, lane)
            else:
                self._finalizers.add(kind)  # the other event type with the same text: allowed once, and it does not feed the parser again
        elif self._deltas and text != self._text:
            self._lane_error("The final output text differs from the text streamed for its lane.", self.lane, lane)
        else:
            self._finalizers.add(kind)
            self._final = text
            if not self._deltas:
                self.reader.feed(text)  # no deltas: the final text is the whole answer

    def _terminal(self, outcome: dict, event: dict) -> None:
        if self._final is None:
            self._lane_error("The response ended before its output text lane was final.", self.lane, None)
            return
        self.reader.finish()
        usage = (event.get("response") or {}).get("usage") or {}
        frames = usage.get("video_frames_processed")
        self.frames_billed = frames if isinstance(frames, int) and not isinstance(frames, bool) else None
        self.status, self.outcome = outcome["status"], outcome

    def _lane_error(self, message: str, expected: tuple | None, received: tuple | None) -> None:
        self._fail("response_lane", message, expected_lane=_lane_dict(expected), received_lane=_lane_dict(received))

    def _fail(self, code: str, message: str, **extra) -> None:
        self.status, self.outcome = "failed", None
        self.error = {"code": code, "message": message, **extra}


def read_stream_strict(lines: Iterable[str], media: str | None = None) -> StrictStream:
    """Read a whole stream with `StrictStream`. A source that fails while starting, while reading, or while cleaning up becomes a `source_error`, never a crash."""
    stream = StrictStream(media)
    try:
        iterator = iter(lines)
    except Exception:  # noqa: BLE001 (any failure of the source is reported the same way)
        stream.fail_source("iterator")
        return stream
    try:
        while stream.status == "in_progress":
            try:
                line = next(iterator)
            except StopIteration:
                break
            except Exception:  # noqa: BLE001
                stream.fail_source("next")
                break
            stream.feed(line)
    finally:
        close = getattr(iterator, "close", None)
        if callable(close):
            try:
                close()
            except Exception:  # noqa: BLE001
                stream.fail_source("return")
    stream.finish()
    return stream


@dataclass
class Tracked:
    parsed: Parsed
    frames_billed: int | None
    cost_usd: float
    file_deleted: bool


class SamVideo:
    """Track objects through a recorded clip with one SAM request."""

    def __init__(self, key: str, client: httpx.Client | None = None, base: str = BASE):
        self._key = key
        self._client = client or _http.new_client()
        self.base = base

    def __repr__(self) -> str:
        return "<SamVideo>"

    def track(self, frames: list, objects: list[PromptObject], direction: str | None = "forward", fps: float = 10.0, folder: Path | None = None) -> Tracked:
        if not frames:
            raise ValueError("a clip needs at least one frame")
        if len(frames) > MAX_VIDEO_FRAMES:
            raise ValueError(f"a clip has at most {MAX_VIDEO_FRAMES} frames")
        first = frames[0]
        size = tuple(first.size) if hasattr(first, "size") and not hasattr(first, "shape") else (first.shape[1], first.shape[0])
        prompt = build_object_prompt(size, objects)
        with tempfile.TemporaryDirectory(dir=folder) as scratch:
            path = encode_mp4(frames, Path(scratch) / "clip.mp4", fps)
            file_id = upload(self._client, self._key, path, base=self.base)
        deleted = False
        try:
            lines: list[str] = []
            try:
                with self._client.stream("POST", self.base + "/responses", json=video_request(prompt, file_id, direction),
                                         headers={"Authorization": f"Bearer {self._key}", "Accept": "text/event-stream"}) as response:
                    _http.check_status(response.status_code)
                    lines = list(response.iter_lines())
            except httpx.TimeoutException:
                raise BrainError("busy", retry=True, wait_seconds=5) from None
            except httpx.HTTPError:
                raise BrainError("offline", retry=True, wait_seconds=5) from None
            reader, _ = read_stream(lines)
            if reader.status == "failed":
                raise BrainError("brain_trouble", detail=f"the segmentation failed: {reader.failed}")
            billed = reader.frames_billed if reader.frames_billed is not None else max(MIN_BILLED_VIDEO_FRAMES, len(frames))
            return_value = Tracked(parse(reader.text), reader.frames_billed, sam_cost(billed, "video"), False)
        finally:
            deleted = delete(self._client, self._key, file_id, self.base)
        return_value.file_deleted = deleted
        return return_value

    def close(self) -> None:
        self._client.close()
