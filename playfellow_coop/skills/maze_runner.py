"""Collect all coins, grab the key, evade the chaser, and unlock the exit door from the picture alone.

Reads walls, floor cells, coins, key, chaser, player, and door directly from the pixels on both
the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned"), with no copied map.
"""
from __future__ import annotations

from collections import deque

import numpy as np

from playfellow_coop.skills.base import Done, Frame

COLS, ROWS = 12, 9
TILE, TOP, INSET = 48, 64, 12
STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _cell_box(frame: Frame, gx: int, gy: int) -> np.ndarray:
    x0, y0 = gx * TILE, TOP + gy * TILE
    return frame[y0 : y0 + TILE, x0 : x0 + TILE]


def _cell_patch(frame: Frame, gx: int, gy: int) -> np.ndarray:
    x0, y0 = gx * TILE + INSET, TOP + gy * TILE + INSET
    return frame[y0 : y0 + TILE - 2 * INSET, x0 : x0 + TILE - 2 * INSET]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Maze Chase."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + ROWS * TILE, COLS * TILE):
        return None
    wall_corner = _cell_box(frame, 0, 0)[2:8, 2:8].mean(axis=(0, 1))
    wall_mid = _cell_patch(frame, 0, 0).mean(axis=(0, 1))
    floor_corners = []
    for gy in range(1, ROWS - 1):
        for gx in range(1, COLS - 1):
            c = _cell_box(frame, gx, gy)[2:7, 2:7].mean(axis=(0, 1))
            if float(np.abs(c - wall_corner).sum()) > 18.0:
                floor_corners.append(c)
    if not floor_corners:
        return None
    floor = np.median(np.stack(floor_corners), axis=0)
    if 50 <= wall_mid[0] <= 75 and 50 <= wall_mid[1] <= 75 and 75 <= wall_mid[2] <= 100 and floor.mean() > 200:
        return "arena"
    if 35 <= wall_mid[0] <= 70 and 45 <= wall_mid[1] <= 80 and 75 <= wall_mid[2] <= 120 and 30 <= floor[0] <= 60 and 55 <= floor[2] <= 90:
        return "skinned"
    return None


def read_board(frame: Frame, look: str | None = None):
    """Read (look_name, walls, door_pos, player, chaser, items, door_open) from the picture."""
    mode = look if isinstance(look, str) else detect_look(frame)
    if mode is None:
        return None
    wall0 = _cell_box(frame, 0, 0).astype(np.float32)
    walls: set[tuple[int, int]] = set()
    door_pos: tuple[int, int] | None = None
    door_open = False
    player: tuple[int, int] | None = None
    chaser: tuple[int, int] | None = None
    items: set[tuple[int, int]] = set()

    for gy in range(ROWS):
        for gx in range(COLS):
            cell = _cell_box(frame, gx, gy)
            corner = cell[2:7, 2:7].mean(axis=(0, 1))
            patch = cell[INSET : TILE - INSET, INSET : TILE - INSET]
            mean = patch.mean(axis=(0, 1))
            mx = patch.max(axis=(0, 1))

            if mode == "arena":
                if corner[0] < 95 and corner[1] < 95 and corner[2] < 115:
                    walls.add((gx, gy))
                    continue
                ring = cell[5:10, 5:10].mean(axis=(0, 1))
                if ring.mean() < 195:
                    if (ring[0] > 115 and ring[2] < 70) or (ring[1] > 165 and ring[0] < 95):
                        door_pos = (gx, gy)
                        door_open = bool(ring[1] > 165 and ring[0] < 95)
                        continue
                if mean[2] > 210 and mean[0] < 90:
                    player = (gx, gy)
                elif mean[0] > 190 and mean[1] < 95 and mean[2] < 95:
                    chaser = (gx, gy)
                elif mean[0] > 210 and mean[1] > 170 and mean[2] < 165:
                    items.add((gx, gy))
            else:
                if float(np.abs(cell.astype(np.float32) - wall0).mean()) < 2.5 or (corner[0] > 60 and corner[2] > 95):
                    walls.add((gx, gy))
                    continue
                if corner[0] < 38 and mean[2] > 115 and mean[0] < 70:
                    door_pos = (gx, gy)
                    door_open = bool(mean[1] > 105 and mean[2] > 150)
                    continue
                if mean[2] > 170 and mean[1] > 135:
                    player = (gx, gy)
                elif int(mx[2]) - int(mx[1]) > 75 and int(mx[0]) > 110 and mean[1] < 75:
                    chaser = (gx, gy)
                elif int(mx[0]) > 215 and int(mx[1]) > 175 and (mean[0] - mean[2]) > 30:
                    items.add((gx, gy))

    return mode, walls, door_pos, player, chaser, items, door_open


def _bfs_step(start: tuple[int, int], goals: set[tuple[int, int]], blocked: set[tuple[int, int]]) -> str | None:
    if start in goals:
        return None
    queue = deque([(start, None)])
    seen = {start}
    while queue:
        cell, first_key = queue.popleft()
        if cell in goals:
            return first_key
        for key, (dx, dy) in STEPS.items():
            nxt = (cell[0] + dx, cell[1] + dy)
            if 0 <= nxt[0] < COLS and 0 <= nxt[1] < ROWS and nxt not in blocked and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, first_key or key))
    return None


class EscapeMaze:
    name = "escape_maze"
    about = "Collect every coin and the key while avoiding the chaser, then walk through the exit door."
    max_steps = 400
    looks = ("arena", "skinned")

    def __init__(self, look=None):
        self.look = look
        self.reset()

    def reset(self) -> None:
        self.detected_look: str | None = None
        self.known_items: set[tuple[int, int]] = set()
        self.last_door: tuple[int, int] | None = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        seen = read_board(frame)
        if seen is None:
            raise Done("unreadable maze_chase picture")
        mode, walls, door_pos, player, chaser, visible_items, door_open = seen
        self.detected_look = mode
        if player is None:
            raise Done("no player in the picture")
        if door_pos is not None:
            self.last_door = door_pos
        door = door_pos or self.last_door

        self.known_items.update(visible_items)
        self.known_items.discard(player)
        # Keep any item currently covered by the chaser; drop items that are no longer on the board
        self.known_items = set(visible_items) | ({chaser} & self.known_items if chaser is not None else set())

        goals = set(self.known_items)
        if not goals or (door_open and not visible_items):
            goals = {door} if door is not None else set()

        base_blocked = set(walls)
        if door is not None and door not in goals:
            base_blocked.add(door)

        if chaser is not None:
            chaser_zone = {chaser} | {(chaser[0] + dx, chaser[1] + dy) for dx, dy in STEPS.values()}
            key = _bfs_step(player, goals, base_blocked | (chaser_zone - {player}))
            if key is not None:
                return key
            key = _bfs_step(player, goals, base_blocked | {chaser})
            if key is not None:
                return key
        key = _bfs_step(player, goals, base_blocked)
        if key is not None:
            return key
        return "right"
