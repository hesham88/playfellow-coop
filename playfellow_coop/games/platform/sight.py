"""What one look at the picture says, locally, in about a millisecond a look on a small copy of the frame."""
from __future__ import annotations

from dataclasses import dataclass

import cv2
import numpy as np

SIZE = (160, 90)  # the small copy every look works on


def small_grey(frame: np.ndarray) -> np.ndarray:
    return cv2.cvtColor(cv2.resize(frame, SIZE, interpolation=cv2.INTER_AREA), cv2.COLOR_BGR2GRAY).astype(np.float32)


def camera_shift(before: np.ndarray, after: np.ndarray) -> tuple[float, float, float]:
    """(dx, dy, confidence) of the picture between two small greys, in shares of the view. dx > 0: the world moved left, so the
    player went right. Phase correlation, so it needs no landmarks; confidence near 0 means no steady motion could be found."""
    window = cv2.createHanningWindow(SIZE, cv2.CV_32F)
    (dx, dy), response = cv2.phaseCorrelate(after.copy(), before.copy(), window)  # it overwrites its inputs with the window
    return dx / SIZE[0], dy / SIZE[1], float(response)


@dataclass
class Cut:
    kind: str  # "none", "fade" (dark or bright screen: a death or a load), "new_scene" (a hard change: a new room)
    brightness: float


def read_cut(before: np.ndarray, after: np.ndarray, tracked: float = 0.0, dark: float = 18.0, bright: float = 238.0, hard: float = 45.0) -> Cut:
    """`tracked` is the camera measure's confidence: a big change the camera followed is scrolling, not a new scene."""
    level = float(after.mean())
    if level < dark or level > bright:
        return Cut("fade", level)
    if tracked < 0.12 and float(np.abs(after - before).mean()) > hard:
        return Cut("new_scene", level)
    return Cut("none", level)


def collectibles(frame: np.ndarray, lower=(20, 130, 170), upper=(34, 255, 255), min_area: int = 12, max_area: int = 900) -> list[tuple[float, float]]:
    """(x, y, shares of the view) of small round bright-yellow blobs, nearest first. The colour range is the card's to change."""
    hsv = cv2.cvtColor(frame, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    count, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    h, w = frame.shape[:2]
    found = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if min_area <= area <= max_area and 0.5 <= bw / max(bh, 1) <= 2.0 and area / float(bw * bh) > 0.45:
            found.append((float(cents[i][0]) / w, float(cents[i][1]) / h))
    return sorted(found, key=lambda p: abs(p[0] - 0.5) + abs(p[1] - 0.5))
