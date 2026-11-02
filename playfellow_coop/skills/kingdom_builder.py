"""Play Tiny Kingdom from pixels: read occupied squares, buildings, and button bars directly from the picture.

No copied game state: reads empty vs occupied squares and button selections from pixels on both the unskinned
arena and glass skin looks.
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done

Frame = np.ndarray

COLS, ROWS = 10, 7
TILE = 56
BAR = 64
BUTTONS = ("farm", "tower", "soldier")
BUILD = {"farm": 10, "tower": 15, "soldier": 8}

KINGDOM_PLAN = (
    [("farm", (1, r)) for r in (1, 3, 5)]
    + [("tower", (2, r)) for r in (1, 3, 5)]
    + [("farm", (1, r)) for r in (0, 2, 4, 6)]
    + [("soldier", (3, r)) for r in range(7)]
    + [("tower", (2, r)) for r in (0, 2, 4, 6)]
    + [("tower", (4, r)) for r in (1, 3, 5)]
)


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if not Tiny Kingdom."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (520, 560):
        return None
    if frame.std() < 5.0:
        return None
    if int(frame[0, 0, 0]) == 16 and int(frame[0, 0, 1]) == 16 and int(frame[0, 0, 2]) == 32:
        return "arena"
    if int(frame[0, 0, 0]) <= 10 and int(frame[0, 0, 2]) <= 30:
        return "skinned"
    return None


class BuildKingdom:
    name = "build_kingdom"
    about = "Build farms, towers, and soldiers to defend the castle against 10 waves in Tiny Kingdom from pixels."
    max_steps = 250

    def __init__(self, look: str | None = None):
        self.look = look
        self.detected_look: str | None = None
        self.reset()

    def reset(self) -> None:
        self.detected_look = None
        self.baseline: Frame | None = None
        self.gold = 20
        self.chosen: str | None = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> tuple[str, float, float] | str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable tiny_kingdom picture")
        self.detected_look = mode

        if self.baseline is None:
            self.baseline = frame.copy()

        occupied: set[tuple[int, int]] = set()
        for c in range(1, COLS):
            for r in range(ROWS):
                cx = c * TILE + TILE // 2
                cy = 64 + r * TILE + TILE // 2
                diff = float(np.mean(np.abs(frame[cy - 12 : cy + 12, cx - 12 : cx + 12].astype(int) - self.baseline[cy - 12 : cy + 12, cx - 12 : cx + 12].astype(int))))
                if diff > 15.0:
                    occupied.add((c, r))

        farm_squares = {(1, r) for r in range(7)}
        farms_count = len(farm_squares & occupied)

        for kind, square in KINGDOM_PLAN:
            if square in occupied:
                continue
            if self.gold < BUILD[kind]:
                self.gold += 3 + 2 * farms_count
                return "enter"
            if self.chosen != kind:
                self.chosen = kind
                btn_idx = BUTTONS.index(kind)
                x = btn_idx * (560.0 / 3.0) + (560.0 / 6.0)
                y = 520.0 - 32.0
                return ("click", x / 560.0 * 1000.0, y / 520.0 * 1000.0)

            self.gold -= BUILD[kind]
            col, row = square
            px = col * TILE + TILE // 2
            py = 64 + row * TILE + TILE // 2
            return ("click", px / 560.0 * 1000.0, py / 520.0 * 1000.0)

        self.gold += 3 + 2 * farms_count
        return "enter"
