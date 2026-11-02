"""Navigate three cave rooms from pixels: jump the spikes, grab the jump boots, double-jump to the high key ledge, and unlock the door.

Reads both the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned").
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done, Frame

WORLD = (
    "################################################",
    "#..............................................#",
    "#..............................................#",
    "#........................................K.....#",
    "#.......................................####...#",
    "#..............................................#",
    "#..............................................#",
    "#..............................................#",
    "#D..P................^^^.....B.................#",
    "################################################",
)
ROOM_W, ROOMS, ROWS = 16, 3, 10
TILE, TOP = 40, 64


def _patch(frame: Frame, col: int, gy: int, x_in: int = 8, y_in: int = 8) -> np.ndarray:
    x0, y0 = col * TILE + x_in, TOP + gy * TILE + y_in
    return frame[y0 : y0 + TILE - 2 * y_in, x0 : x0 + TILE - 2 * x_in]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Key Caves."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + ROWS * TILE, ROOM_W * TILE):
        return None
    rock = _patch(frame, 0, 0)
    sky = _patch(frame, 2, 2)
    rock_m, sky_m = rock.mean(axis=(0, 1)), sky.mean(axis=(0, 1))
    if np.abs(rock_m - sky_m).sum() < 12.0:
        return None
    if 80 <= rock_m[0] <= 105 and 65 <= rock_m[1] <= 85 and 105 <= rock_m[2] <= 135 and sky_m[0] < 35 and sky_m[1] < 30:
        return "arena"
    if float(rock.std(axis=(0, 1)).mean()) > 4.0 and 30 <= rock_m[0] <= 65 and 50 <= rock_m[2] <= 85:
        return "skinned"
    return None


def _detect_room(frame: Frame) -> int:
    rock0 = _patch(frame, 0, 0)
    ledge = _patch(frame, 8, 4)
    if float(np.abs(ledge.astype(float) - rock0.astype(float)).mean()) < 3.0:
        return 2
    spikes = sum(
        int(frame[TOP + 8 * TILE + 14 : TOP + 8 * TILE + 38, c * TILE + 4 : c * TILE + 36].max()) > 210
        for c in (5, 6, 7)
    )
    if spikes >= 2:
        return 1
    return 0


def _find_player(frame: Frame, mode: str, room: int) -> tuple[int, int] | None:
    best_cell = None
    best_score = 0.0
    first = room * ROOM_W
    for gy in range(1, ROWS - 1):
        for col in range(ROOM_W):
            if WORLD[gy][first + col] == "#":
                continue
            if room == 0 and (col, gy) == (1, 8):
                continue
            x0, y0 = col * TILE, TOP + gy * TILE
            upper = frame[y0 + 5 : y0 + 19, x0 + 10 : x0 + 30]
            mean = upper.mean(axis=(0, 1))
            if mode == "arena":
                if mean[2] > 210 and mean[0] > 100 and mean[1] < 120:
                    score = float(mean[2])
                    if score > best_score:
                        best_score, best_cell = score, (col, gy)
            else:
                mx = upper.max(axis=(0, 1))
                if int(mx[2]) > 215 and int(mx[1]) > 185 and mean[2] > 140:
                    score = float(mean[2] + mean[1])
                    if score > best_score:
                        best_score, best_cell = score, (col, gy)
    return best_cell


def _boots_on_player(frame: Frame, col: int, gy: int, mode: str) -> bool:
    x0, y0 = col * TILE, TOP + gy * TILE
    if mode == "arena":
        feet = frame[y0 + 32 : y0 + 38, x0 + 10 : x0 + 30].mean(axis=(0, 1))
        return bool(feet[1] > 190 and feet[2] > 220 and feet[0] < 70)
    feet = frame[y0 + 22 : y0 + 36, x0 + 8 : x0 + 32]
    cyan = (feet[:, :, 0] < 65) & (feet[:, :, 1] > 195) & (feet[:, :, 2] > 225)
    return int(cyan.sum()) >= 35


def _key_visible_in_room2(frame: Frame) -> bool:
    x0, y0 = 9 * TILE, TOP + 3 * TILE
    patch = frame[y0 + 8 : y0 + 28, x0 + 8 : x0 + 34]
    gold = (patch[:, :, 0] > 200) & (patch[:, :, 1] > 150) & (patch[:, :, 2] < 95)
    return int(gold.sum()) >= 15


class UnlockCaves:
    name = "unlock_caves"
    about = "Cross the cave rooms, jump the spikes for the boots, double-jump to the key on the ledge, and unlock the door."
    max_steps = 400
    looks = ("arena", "skinned")

    def __init__(self, look=None):
        self.look = look
        self.reset()

    def reset(self) -> None:
        self.detected_look: str | None = None
        self.has_boots = False
        self.has_key = False

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable key_caves picture")
        self.detected_look = mode
        room = _detect_room(frame)
        local = _find_player(frame, mode, room)
        if local is None:
            raise Done("no player in the picture")
        col, y = local
        x = room * ROOM_W + col
        if (x, y) == (29, 8) or _boots_on_player(frame, col, y, mode):
            self.has_boots = True
        if (x, y) == (41, 3) or (room == 2 and not _key_visible_in_room2(frame)):
            self.has_key = True
            self.has_boots = True

        # Phase 3: has the key -> head left back to the door at (1, 8) and press 'z' at (2, 8)
        if self.has_key:
            if x <= 2 and y == 8:
                return "z"
            if x == 24 and y == 8:
                return "space"
            return "left"

        # Phase 1: before boots -> walk right, jump over spikes 21..23 from x=20
        if not self.has_boots:
            if x == 20 and y == 8:
                return "space"
            return "right"

        # Phase 2: has boots, needs key at (41, 3) on ledge (40..43, 4)
        if x < 39:
            if x == 20 and y == 8:
                return "space"
            return "right"
        if x == 39:
            if y == 8 or y == 6:
                return "space"
            if y <= 3:
                return "right"
            return None
        if x < 41 and y <= 3:
            return "right"
        return "left"
