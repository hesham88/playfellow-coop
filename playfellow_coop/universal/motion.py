"""Pillar 2, moving things: what changed between two pictures, where the camera went, and which things are moving, from pixels alone.

`shift_between` is visual odometry for a flat scroll or a camera turn: phase correlation (FFT) finds how far the whole picture slid. `Odometry` adds the slides up into a position and
remembers which map cells were visited, so a game without a mini-map still gets one. `components` and `moving_blobs` find things that moved against the background, with no asset ids,
so they work on an enemy, a projectile or an item the model has never seen. Numpy only.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

Box = tuple[int, int, int, int]  # left, top, width, height


def grey(frame: np.ndarray) -> np.ndarray:
    return frame.astype(np.float32) @ np.array([0.299, 0.587, 0.114], dtype=np.float32) if frame.ndim == 3 else frame.astype(np.float32)


def shift_between(before: np.ndarray, after: np.ndarray, max_shift: int | None = None) -> tuple[int, int, float]:
    """How far the picture slid from `before` to `after`: (dx, dy, confidence). Content that moved right gives dx > 0; confidence is 0..1 (1 = a clean slide).
    A picture with no texture, or two different sizes, gives (0, 0, 0.0)."""
    a, b = grey(before), grey(after)
    if a.shape != b.shape or min(a.shape) < 8:
        return 0, 0, 0.0
    a, b = a - a.mean(), b - b.mean()
    if not a.any() or not b.any():
        return 0, 0, 0.0
    window = np.outer(np.hanning(a.shape[0]), np.hanning(a.shape[1])).astype(np.float32)  # no edge ringing
    fa, fb = np.fft.rfft2(a * window), np.fft.rfft2(b * window)
    cross = fb * np.conj(fa)
    cross /= np.maximum(np.abs(cross), 1e-9)
    surface = np.fft.irfft2(cross, s=a.shape)
    peak = np.unravel_index(int(np.argmax(surface)), surface.shape)
    height, width = a.shape
    dy = peak[0] if peak[0] <= height // 2 else peak[0] - height
    dx = peak[1] if peak[1] <= width // 2 else peak[1] - width
    if max_shift is not None and (abs(dx) > max_shift or abs(dy) > max_shift):
        return 0, 0, 0.0
    return int(dx), int(dy), float(min(1.0, max(0.0, surface[peak])))


class Odometry:
    """Adds up the slides into a position, and keeps a coarse map of where the view has been."""

    def __init__(self, cell: int = 32, min_confidence: float = 0.12, max_shift: int | None = None):
        self.cell, self.min_confidence, self.max_shift = cell, min_confidence, max_shift
        self.x = self.y = 0
        self.visited: set[tuple[int, int]] = {(0, 0)}
        self._last: np.ndarray | None = None
        self.last_confidence = 0.0

    def update(self, frame: np.ndarray) -> tuple[int, int]:
        """Call with each new picture. The view moved opposite to the content, so a scene sliding right means the camera went left. Returns the position."""
        if self._last is not None:
            dx, dy, confidence = shift_between(self._last, frame, self.max_shift)
            self.last_confidence = confidence
            if confidence >= self.min_confidence:
                self.x -= dx
                self.y -= dy
                self.visited.add((self.x // self.cell, self.y // self.cell))
        self._last = frame
        return self.x, self.y

    def seen(self, x: int, y: int) -> bool:
        return (x // self.cell, y // self.cell) in self.visited


@dataclass(frozen=True)
class Blob:
    box: Box
    area: int
    centre: tuple[float, float]


def components(mask: np.ndarray, min_area: int = 1) -> list[Blob]:
    """Connected groups (4-neighbour) of True pixels, found from row runs with a union-find: fast enough for a full window, no scipy."""
    height, width = mask.shape
    runs: list[tuple[int, int, int]] = []  # row, start, end (exclusive)
    row_runs: list[list[int]] = []
    for y in range(height):
        row = mask[y]
        if not row.any():
            row_runs.append([])
            continue
        edges = np.flatnonzero(np.diff(np.concatenate(([0], row.view(np.int8), [0]))))
        indexes = []
        for start, end in zip(edges[0::2], edges[1::2]):
            indexes.append(len(runs))
            runs.append((y, int(start), int(end)))
        row_runs.append(indexes)
    parent = list(range(len(runs)))

    def find(i):
        while parent[i] != i:
            parent[i] = parent[parent[i]]
            i = parent[i]
        return i

    for y in range(1, height):
        for i in row_runs[y]:
            _, s, e = runs[i]
            for j in row_runs[y - 1]:
                _, s2, e2 = runs[j]
                if s < e2 and s2 < e:
                    ri, rj = find(i), find(j)
                    if ri != rj:
                        parent[ri] = rj
    groups: dict[int, list[int]] = {}
    for i in range(len(runs)):
        groups.setdefault(find(i), []).append(i)
    blobs = []
    for members in groups.values():
        area = sum(runs[i][2] - runs[i][1] for i in members)
        if area < min_area:
            continue
        left = min(runs[i][1] for i in members)
        right = max(runs[i][2] for i in members)
        top = min(runs[i][0] for i in members)
        bottom = max(runs[i][0] for i in members) + 1
        cy = sum((runs[i][0] + 0.5) * (runs[i][2] - runs[i][1]) for i in members) / area
        cx = sum((runs[i][1] + runs[i][2]) / 2 * (runs[i][2] - runs[i][1]) for i in members) / area
        blobs.append(Blob((left, top, right - left, bottom - top), area, (cx, cy)))
    return sorted(blobs, key=lambda b: (b.box[1], b.box[0]))


def moving_blobs(before: np.ndarray, after: np.ndarray, threshold: int = 28, min_area: int = 6, compensate: bool = True) -> list[Blob]:
    """Things that moved: pixels that changed by more than `threshold`, grouped. With `compensate`, a whole-picture slide (camera or scroll) is undone first so the scenery
    does not count as moving."""
    if before.shape != after.shape:
        return []
    ref = before
    if compensate:
        dx, dy, confidence = shift_between(before, after)
        if confidence >= 0.3 and (dx or dy):
            ref = np.roll(before, (dy, dx), axis=(0, 1))
    delta = np.abs(after.astype(np.int16) - ref.astype(np.int16)).max(axis=2) if after.ndim == 3 else np.abs(after.astype(np.int16) - ref.astype(np.int16))
    return components(delta > threshold, min_area)


def motion_level(before: np.ndarray, after: np.ndarray, threshold: int = 12) -> float:
    """0..1: the share of the picture that changed. 0 = frozen (a loading screen or a pause), near 1 = a cut or a flash."""
    if before.shape != after.shape:
        return 1.0
    delta = np.abs(after[::4, ::4].astype(np.int16) - before[::4, ::4].astype(np.int16))
    return float((delta.max(axis=-1) > threshold).mean()) if delta.ndim == 3 else float((delta > threshold).mean())
