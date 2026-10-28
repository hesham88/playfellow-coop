"""Pillar 1, seeing: whatever the screen grabber hands over becomes ONE standard picture (height x width x 3, uint8, RGB).

Windows grabbers return BGRA, Pillow gives RGB or RGBA, a capture card may give grey or 16-bit; windows come in every size. `normalize` turns them all into the same kind of
matrix, so every later step (skills, the classifier, the odometry, the model's picture) can rely on it. `FrameClock` measures how fast pictures really arrive.
"""
from __future__ import annotations

import time
from collections import deque
from typing import Callable

import numpy as np

Frame = np.ndarray


def to_rgb(picture, order: str = "rgb") -> Frame:
    """Any picture (Pillow image, array of 2, 3 or 4 channels, 8 or 16 bit, floats in 0..1) as an RGB uint8 array. `order` says whether a 3/4-channel array is "rgb" or "bgr"."""
    if hasattr(picture, "convert"):
        return np.asarray(picture.convert("RGB"))
    data = np.asarray(picture)
    if data.ndim == 2:
        data = np.stack([data] * 3, axis=2)
    if data.ndim != 3 or data.shape[2] not in (1, 3, 4):
        raise ValueError(f"cannot read a picture of shape {data.shape}")
    if data.shape[2] == 1:
        data = np.repeat(data, 3, axis=2)
    data = data[:, :, :3]
    if order == "bgr":
        data = data[:, :, ::-1]
    elif order != "rgb":
        raise ValueError(f"unknown channel order {order!r}")
    if data.dtype == np.uint8:
        return np.ascontiguousarray(data)
    if np.issubdtype(data.dtype, np.floating):
        return np.ascontiguousarray((np.clip(data, 0.0, 1.0) * 255.0 + 0.5).astype(np.uint8))
    if data.dtype == np.uint16:
        return np.ascontiguousarray((data >> 8).astype(np.uint8))
    return np.ascontiguousarray(np.clip(data, 0, 255).astype(np.uint8))


def resize(frame: Frame, width: int, height: int) -> Frame:
    """Resize with no new dependency: shrinking averages the source pixels each new pixel covers (no aliasing), enlarging repeats the nearest pixel (colours stay exact)."""
    src_h, src_w = frame.shape[:2]
    if (src_w, src_h) == (width, height):
        return frame
    if width <= 0 or height <= 0:
        raise ValueError("a picture needs a positive size")
    ys = np.minimum((np.arange(height) * src_h // height), src_h - 1)
    xs = np.minimum((np.arange(width) * src_w // width), src_w - 1)
    if width >= src_w and height >= src_h:
        return frame[ys][:, xs]
    # area average along each axis (rows first, then columns) using cumulative sums
    out = frame.astype(np.float64)
    if height < src_h:
        edges = np.linspace(0, src_h, height + 1)
        out = _area(out, edges, axis=0)
    elif height > src_h:
        out = out[ys]
    if width < src_w:
        edges = np.linspace(0, src_w, width + 1)
        out = _area(out, edges, axis=1)
    elif width > src_w:
        out = out[:, xs]
    return np.clip(out + 0.5, 0, 255).astype(np.uint8)


def _area(data: np.ndarray, edges: np.ndarray, axis: int) -> np.ndarray:
    size = data.shape[axis]
    cumulative = np.concatenate([np.zeros_like(np.take(data, [0], axis=axis)), np.cumsum(data, axis=axis)], axis=axis)

    def at(position):  # linear interpolation of the running sum at a fractional position
        lower = np.minimum(np.floor(position).astype(int), size)
        upper = np.minimum(lower + 1, size)
        weight = (position - lower).reshape([-1 if i == axis else 1 for i in range(data.ndim)])
        return np.take(cumulative, lower, axis=axis) * (1 - weight) + np.take(cumulative, upper, axis=axis) * weight

    total = at(edges[1:]) - at(edges[:-1])
    widths = (edges[1:] - edges[:-1]).reshape([-1 if i == axis else 1 for i in range(data.ndim)])
    return total / widths


def normalize(picture, size: tuple[int, int] | None = None, order: str = "rgb", max_side: int | None = None) -> Frame:
    """The standard matrix: RGB uint8, optionally resized to `size` (width, height), or shrunk so its long side is at most `max_side` (the aspect ratio is kept)."""
    frame = to_rgb(picture, order)
    if size is not None:
        return resize(frame, size[0], size[1])
    if max_side:
        height, width = frame.shape[:2]
        longest = max(width, height)
        if longest > max_side:
            scale = max_side / longest
            return resize(frame, max(1, round(width * scale)), max(1, round(height * scale)))
    return frame


class FrameClock:
    """Measures the real picture rate and the delay of the grabber, from the times pictures arrive."""

    def __init__(self, window: int = 30, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._times: deque[float] = deque(maxlen=window)

    def tick(self) -> None:
        self._times.append(self._clock())

    @property
    def fps(self) -> float:
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / span if span > 0 else 0.0

    @property
    def frame_ms(self) -> float:
        return 1000.0 / self.fps if self.fps else 0.0
