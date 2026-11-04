"""Fast looks at a flight frame, from the positions and colours in the game's own interface file (data/_ui/interfaces.txt, "hud").

Top right anchored: shield ring radius 60 and hull ring radius 55 around (-75, 155); bars fuel x -54, energy x -34, heat x -14, y 233..425.
Top left anchored: radar centre (128, 128), radius 110, scale .025 (1 pixel = 40 world units); target rings around (75, 315).
Radar colours: player (.2,1,0), friendly (.4,.6,1), unfriendly (.8,.8,.3), hostile (.85,.3,.2), selected target (1,1,1).
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

import numpy as np

RADAR_CENTRE = (128, 128)
RADAR_RADIUS = 110
WORLD_PER_PIXEL = 40.0
RING_ANGLES = np.radians(np.arange(0, 360, 2))


@dataclass
class Contact:
    x: float
    y: float
    kind: str  # hostile, unfriendly, friendly, target

    @property
    def distance(self) -> float:
        """World units from the ship (radar pixels times the radar scale)."""
        return math.hypot(self.x, self.y) * WORLD_PER_PIXEL


@dataclass
class Hud:
    bright: bool  # the HUD is lit: nothing is covering the flight view
    shields: float
    hull: float
    energy: float
    heat: float
    fuel: float
    target_shields: float
    target_hull: float
    has_target: bool
    contacts: list[Contact] = field(default_factory=list)

    def of(self, kind: str) -> list[Contact]:
        return [c for c in self.contacts if c.kind == kind]

    @property
    def nearest_hostile(self) -> Contact | None:
        return min(self.of("hostile") + self.of("target"), key=lambda c: c.distance, default=None)


def _ring(frame: np.ndarray, cx: float, cy: float, radii: tuple[int, ...], match) -> float:
    """The share of the circle lit in the ring's colour; the sprite behind it is grey or black, the ring itself coloured."""
    h, w = frame.shape[:2]
    lit = np.zeros(len(RING_ANGLES), dtype=bool)
    for r in radii:
        xs = np.clip((cx + r * np.sin(RING_ANGLES)).astype(int), 0, w - 1)
        ys = np.clip((cy - r * np.cos(RING_ANGLES)).astype(int), 0, h - 1)
        lit |= match(frame[ys, xs].astype(int))
    return float(lit.mean())


def _is_shield(p: np.ndarray) -> np.ndarray:
    return (p[:, 0] > p[:, 2] + 40) & (p[:, 0] > 120)


def _is_hull(p: np.ndarray) -> np.ndarray:
    return (p[:, 2] > p[:, 0] + 30) & (p[:, 1] > p[:, 0] + 15) & (p[:, 2] > 110)


def _bar(frame: np.ndarray, x: int, y_top: int = 233, y_bottom: int = 425) -> float:
    """How full a vertical HUD bar is: lit rows as a share of its length."""
    if x < 0 or y_bottom >= frame.shape[0]:
        return 0.0
    column = frame[y_top:y_bottom, x].astype(int).max(axis=1)
    return float((column > 70).mean())


def contacts(frame: np.ndarray) -> list[Contact]:
    """Radar blips by colour, as small blobs relative to the ship at the radar's centre."""
    import cv2

    cx, cy = RADAR_CENTRE
    box = frame[cy - RADAR_RADIUS:cy + RADAR_RADIUS, cx - RADAR_RADIUS:cx + RADAR_RADIUS].astype(int)
    if box.shape[0] < 2 * RADAR_RADIUS or box.shape[1] < 2 * RADAR_RADIUS:
        return []
    b, g, r = box[:, :, 0], box[:, :, 1], box[:, :, 2]
    masks = {"hostile": (r > 150) & (g < 110) & (b < 90) & (r > g + 70),
             "unfriendly": (r > 140) & (g > 140) & (b < 110),
             "friendly": (b > 170) & (g > 100) & (g < 190) & (r < 140),
             "target": (r > 215) & (g > 215) & (b > 215)}
    found = []
    yy, xx = np.ogrid[:box.shape[0], :box.shape[1]]
    inside = (xx - RADAR_RADIUS) ** 2 + (yy - RADAR_RADIUS) ** 2 <= (RADAR_RADIUS - 1) ** 2
    for kind, mask in masks.items():
        count, _, stats, centres = cv2.connectedComponentsWithStats(np.uint8(mask & inside), connectivity=8)
        for i in range(1, count):
            if stats[i, cv2.CC_STAT_AREA] > 90:  # a star's or planet's disc, not a ship
                continue
            found.append(Contact(float(centres[i][0] - RADAR_RADIUS), float(centres[i][1] - RADAR_RADIUS), kind))
    return found


def is_bright(frame: np.ndarray) -> bool:
    """A panel over the flight view dims the HUD; a lit shield or hull ring means it is uncovered."""
    h, w = frame.shape[:2]
    if w < 300 or h < 300:
        return False
    return _ring(frame, w - 75, 155, (60, 61), _is_shield) > 0.02 or _ring(frame, w - 75, 155, (55, 56), _is_hull) > 0.02


def read_hud(frame: np.ndarray) -> Hud:
    h, w = frame.shape[:2]
    target_shields = _ring(frame, 75, 315, (60, 61), _is_shield)
    target_hull = _ring(frame, 75, 315, (55, 56), _is_hull)
    return Hud(is_bright(frame), _ring(frame, w - 75, 155, (60, 61), _is_shield), _ring(frame, w - 75, 155, (55, 56), _is_hull),
               _bar(frame, w - 34), _bar(frame, w - 14), _bar(frame, w - 54), target_shields, target_hull, target_shields > 0.01 or target_hull > 0.01, contacts(frame))


class Speedometer:
    """The ship's own speed from how the starfield slides between looks (the camera follows the ship). Scale calibrated in world units a second."""

    def __init__(self, scale: float = 1.0):
        self.scale, self.last, self.last_t, self.speed = scale, None, 0.0, 0.0

    def update(self, frame: np.ndarray, now: float) -> float:
        import cv2

        h, w = frame.shape[:2]
        crop = frame[h // 2 + 60:min(h // 2 + 316, h), w // 2 - 128:w // 2 + 128]  # below the ship, clear of the HUD
        gray = np.float32(cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY))
        if self.last is not None and gray.shape == self.last.shape and now > self.last_t:
            (dx, dy), response = cv2.phaseCorrelate(self.last, gray)
            if response > 0.05:
                self.speed = 0.6 * self.speed + 0.4 * math.hypot(dx, dy) / (now - self.last_t) * self.scale
        self.last, self.last_t = gray, now
        return self.speed
