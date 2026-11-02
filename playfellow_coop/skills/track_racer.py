"""Play Top Racer from pixels: read car position, track cones, and corner zones directly from the picture.

No copied game state or cheats: reads player car and obstacles from pixels on both the unskinned
arena and glass skin looks, and drives with zero spin-outs.
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done

Frame = np.ndarray

COLS, ROWS = 14, 9
CELLS = 2 * (COLS - 1) + 2 * (ROWS - 1)  # 42 cells
TILE, MARGIN, LANE_GAP = 48, 14, 14
TOP = 78
WIDTH, HEIGHT = 700, 524

CORNERS = (0, COLS - 1, COLS - 1 + ROWS - 1, 2 * (COLS - 1) + ROWS - 1)
CORNER_ZONE = {(c + d) % CELLS for c in CORNERS for d in (-1, 0, 1)}


def cell_xy(cell: int) -> tuple[int, int]:
    cell %= CELLS
    if cell < COLS - 1:
        return cell, 0
    cell -= COLS - 1
    if cell < ROWS - 1:
        return COLS - 1, cell
    cell -= ROWS - 1
    if cell < COLS - 1:
        return COLS - 1 - cell, ROWS - 1
    return 0, ROWS - 1 - (cell - (COLS - 1))


def inward(cell: int) -> tuple[int, int]:
    x, y = cell_xy(cell)
    if y == 0 and x < COLS - 1:
        return 0, 1
    if x == COLS - 1 and y < ROWS - 1:
        return -1, 0
    if y == ROWS - 1 and x > 0:
        return 0, -1
    return 1, 0


def get_spot(cell: int, lane: int) -> tuple[int, int]:
    x, y = cell_xy(cell)
    dx, dy = inward(cell)
    return (MARGIN + x * TILE + TILE // 2 + dx * (lane - 1) * LANE_GAP,
            TOP + y * TILE + TILE // 2 + dy * (lane - 1) * LANE_GAP)


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if not Top Racer."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (HEIGHT, WIDTH):
        return None
    if frame.std() < 5.0:
        return None
    if int(frame[0, 0, 0]) == 16 and int(frame[0, 0, 1]) == 16 and int(frame[0, 0, 2]) == 32:
        return "arena"
    if int(frame[0, 0, 0]) <= 12 and int(frame[0, 0, 2]) <= 28:
        return "skinned"
    return None


def read_racer(frame: Frame, look: str) -> tuple[tuple[int, int], set[tuple[int, int]]]:
    """Read ((cell, lane), cones_set) from the picture."""
    best_spot = (3, 1)
    best_score = 1e9

    for cell in range(CELLS):
        for lane in range(3):
            cx, cy = get_spot(cell, lane)
            if look == "arena":
                patch = frame[cy - 4 : cy + 5, cx - 4 : cx + 5]
                diff = float(np.abs(patch.astype(float) - [124, 92, 255]).sum(axis=-1).min())
            else:
                diff = float(np.abs(frame[cy - 21, cx].astype(float) - [234, 240, 255]).sum())
            if diff < best_score:
                best_score = diff
                best_spot = (cell, lane)

    cones: set[tuple[int, int]] = set()
    for cell in range(CELLS):
        for lane in range(3):
            cx, cy = get_spot(cell, lane)
            patch = frame[cy - 4 : cy + 5, cx - 4 : cx + 5]
            diff = np.abs(patch.astype(int) - [255, 120, 0]).sum(axis=-1)
            if (diff < 35).any():
                cones.add((cell, lane))

    return best_spot, cones


class DriveRacer:
    name = "drive_racer"
    about = "Drive three laps in Top Racer from pixels, braking for corners and dodging cones to finish first."
    max_steps = 450

    def __init__(self, look: str | None = None):
        self.look = look
        self.detected_look: str | None = None
        self.reset()

    def reset(self) -> None:
        self.detected_look = None
        self.speed = 0
        self.boosts = 3
        self.boost_ticks = 0

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable top_racer picture")
        self.detected_look = mode

        (cell, lane), cones = read_racer(frame, mode)

        # Hazard detection in next 3 cells ahead
        hazard = False
        for dist in (1, 2, 3):
            ahead_cell = (cell + dist) % CELLS
            if (ahead_cell, lane) in cones:
                hazard = True
                break

        action: str | None = None
        if hazard:
            cone_lanes = {l for dist in (1, 2, 3) for (c, l) in cones if c == (cell + dist) % CELLS}
            best_lane = min([l for l in (0, 1, 2) if l not in cone_lanes], default=1)
            if best_lane < lane:
                action = "left"
            elif best_lane > lane:
                action = "right"

        if action is None:
            next_in_corner = ((cell + 1) % CELLS) in CORNER_ZONE
            in_corner = cell in CORNER_ZONE

            if in_corner:
                if self.speed < 2:
                    action = "up"
                elif self.speed > 2:
                    action = "down"
            elif next_in_corner:
                if self.speed > 2:
                    action = "down"
                elif self.speed < 2:
                    action = "up"
            else:
                if self.speed < 4:
                    action = "up"
                else:
                    dist_to_corner = min((c - cell) % CELLS for c in CORNER_ZONE)
                    if self.boosts > 0 and not self.boost_ticks and dist_to_corner >= 8 and not hazard:
                        action = "space"

        # Update speed tracking
        if action == "up":
            self.speed = min(4, self.speed + 1)
        elif action == "down":
            self.speed = max(0, min(self.speed, 4) - 2)
            self.boost_ticks = 0
        elif action == "space" and self.boosts > 0 and not self.boost_ticks:
            self.boosts -= 1
            self.boost_ticks = 4
            self.speed = 6

        if self.boost_ticks:
            self.boost_ticks -= 1
            if not self.boost_ticks:
                self.speed = 4

        return action
