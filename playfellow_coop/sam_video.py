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
from playfellow_coop.sam_protocol import PromptObject

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
