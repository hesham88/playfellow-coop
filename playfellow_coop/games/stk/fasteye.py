"""The fast local eye for bananas and nitro tanks: ten looks a second, no model in the loop.

SAM names things well but answers in 2-3 s (3 Nov), and something on the road at 20 m/s is passed in under 2 s. The rules
come from crops of the 3 Nov Intermediate race video (what was and was not a banana or a nitro tank):

  banana   a LARGE yellow-to-green blob (the game's banana is yellow with a green tint) lying on the road, with little black
           around it; the false hits were small yellow next to black (the racers' beaks and feet, a Tux icon), the countdown
           clock and lights, and the 'Go!' letters - so blobs under 120 px or with much black nearby are not bananas
  nitro    a SMALL dark-blue blob in the middle of the road (the game's nitro tank); the false hits were purple coral at the
           sides and whole karts - so only the road's middle third and blobs under 450 px count
"""
from __future__ import annotations

import cv2
import numpy as np

BAND = (0.30, 0.66)  # the road ahead, above the buddy's own kart
SIDE = (0.20, 0.80)  # the road's width across the view


def _blobs(frame: np.ndarray, lower, upper, min_area: int, max_area: int, side=SIDE):
    h, w = frame.shape[:2]
    y0, y1, x0, x1 = int(h * BAND[0]), int(h * BAND[1]), int(w * side[0]), int(w * side[1])
    region = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    mask = cv2.inRange(hsv, lower, upper)
    count, _, stats, cents = cv2.connectedComponentsWithStats(mask)
    grey = cv2.cvtColor(region, cv2.COLOR_BGR2GRAY)
    out = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if not min_area <= area <= max_area:
            continue
        pad = max(bw, bh) // 2 + 4
        around = grey[max(y - pad, 0):y + bh + pad, max(x - pad, 0):x + bw + pad]
        black = float((around < 35).mean()) if around.size else 0.0
        out.append(((x0 + cents[i][0]) / w, cents[i][1] / (y1 - y0), int(area), black, bw / max(bh, 1)))
    return out


def bananas(frame: np.ndarray) -> list[tuple[float, float, int]]:
    """(x across the view 0-1, nearness 0-1, area px) of bananas on the road ahead."""
    found = _blobs(frame, (22, 110, 120), (42, 255, 255), 45, 6000)
    hits = [(x, n, a) for x, n, a, black, aspect in found if black < 0.12 and 0.5 <= aspect <= 4.0]
    if len(hits) > 3:  # dizzy stars after a hit, or an explosion: many yellow blobs at once, never bananas
        return []
    return hits


def gifts(frame: np.ndarray) -> list[tuple[float, float, int]]:
    """(x across the view 0-1, nearness 0-1, area px) of gift boxes ahead: a bright, saturated cyan block with white ribbon
    inside its box (Abyss' floor lights are paler and carry no white)."""
    h, w = frame.shape[:2]
    y0, y1, x0, x1 = int(h * BAND[0]), int(h * BAND[1]), int(w * SIDE[0]), int(w * SIDE[1])
    region = frame[y0:y1, x0:x1]
    hsv = cv2.cvtColor(region, cv2.COLOR_BGR2HSV)
    cyan = cv2.inRange(hsv, (86, 170, 170), (104, 255, 255))
    white = cv2.inRange(hsv, (0, 0, 215), (180, 45, 255))
    count, _, stats, cents = cv2.connectedComponentsWithStats(cyan)
    out = []
    for i in range(1, count):
        x, y, bw, bh, area = stats[i]
        if not 60 <= area <= 5000 or not 0.5 <= bw / max(bh, 1) <= 2.2:
            continue
        box_white = white[y:y + bh, x:x + bw].mean() / 255.0
        fill = area / float(bw * bh)
        if box_white < 0.03 or fill < 0.35:
            continue
        out.append(((x0 + cents[i][0]) / w, cents[i][1] / (y1 - y0), int(area)))
    return out


def nitro_tanks(frame: np.ndarray) -> list[tuple[float, float, int]]:
    """(x across the view 0-1, nearness 0-1, area px) of nitro tanks in the middle of the road ahead."""
    found = _blobs(frame, (106, 150, 60), (128, 255, 235), 12, 450, side=(0.33, 0.67))
    return [(x, n, a) for x, n, a, black, aspect in found if 0.3 <= aspect <= 2.5]


def dodge(found: list[tuple[float, float, int]], push: float = 0.35) -> float:
    """A steering bias (radians, + = left) away from the nearest banana in the kart's path, or 0."""
    in_path = [b for b in found if abs(b[0] - 0.5) < 0.18 and b[1] > 0.12]
    if not in_path:
        return 0.0
    nearest = max(in_path, key=lambda b: b[1])
    return push if nearest[0] >= 0.5 else -push


def collect(found: list[tuple[float, float, int]], pull: float = 0.14) -> float:
    """A steering bias (radians, + = left) toward the nearest nitro tank ahead, or 0."""
    if not found:
        return 0.0
    target = max(found, key=lambda b: b[1])
    return float(np.clip(-(target[0] - 0.5) * 1.25, -pull, pull))
