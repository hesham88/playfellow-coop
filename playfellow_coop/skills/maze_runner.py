"""Collect all coins, grab the key, evade the chaser, and unlock the exit door from the picture alone.

Reads both the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned").
"""
from __future__ import annotations

from collections import deque

import numpy as np

from playfellow_coop.skills.base import Done, Frame

MAZE = (
    "############",
    "#P...#....c#",
    "#.##.#.##..#",
    "#c#..c..#..#",
    "#.#.###.#.##",
    "#...#k...G.#",
    "#.###.###..#",
    "#c.......c.D",
    "############",
)
COLS, ROWS = 12, 9
TILE, TOP, INSET = 48, 64, 12
DOOR = (11, 7)
WALLS = {(x, y) for y, row in enumerate(MAZE) for x, c in enumerate(row) if c == "#"}
INITIAL_ITEMS = {(x, y) for y, row in enumerate(MAZE) for x, c in enumerate(row) if c in ("c", "k")}
STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}


def _cell_patch(frame: Frame, gx: int, gy: int) -> np.ndarray:
    x0, y0 = gx * TILE + INSET, TOP + gy * TILE + INSET
    return frame[y0 : y0 + TILE - 2 * INSET, x0 : x0 + TILE - 2 * INSET]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Maze Chase."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + ROWS * TILE, COLS * TILE):
        return None
    wall = _cell_patch(frame, 0, 0).mean(axis=(0, 1))
    floors = [_cell_patch(frame, gx, gy).mean(axis=(0, 1)) for gx, gy in ((2, 1), (3, 1), (6, 1), (8, 1))]
    floor = np.median(np.stack(floors), axis=0)
    if np.abs(wall - floor).sum() < 15.0:
        return None
    if 50 <= wall[0] <= 75 and 50 <= wall[1] <= 75 and 75 <= wall[2] <= 100 and floor.mean() > 200:
        return "arena"
    if 35 <= wall[0] <= 70 and 45 <= wall[1] <= 80 and 75 <= wall[2] <= 120 and 30 <= floor[0] <= 60 and 55 <= floor[2] <= 90:
        return "skinned"
    return None


def read_board(frame: Frame, look: str | None = None):
    """Read (look_name, player, chaser, items, door_open) from the picture."""
    mode = look if isinstance(look, str) else detect_look(frame)
    if mode is None:
        return None
    player = None
    chaser = None
    items: set[tuple[int, int]] = set()
    for gy in range(ROWS):
        for gx in range(COLS):
            if (gx, gy) in WALLS or (gx, gy) == DOOR:
                continue
            patch = _cell_patch(frame, gx, gy)
            mean = patch.mean(axis=(0, 1))
            mx = patch.max(axis=(0, 1))
            if mode == "arena":
                if mean[2] > 210 and mean[0] < 90:
                    player = (gx, gy)
                elif mean[0] > 190 and mean[1] < 95 and mean[2] < 95:
                    chaser = (gx, gy)
                elif mean[0] > 210 and mean[1] > 170 and mean[2] < 165:
                    items.add((gx, gy))
            else:
                if mean[2] > 170 and mean[1] > 135:
                    player = (gx, gy)
                elif int(mx[2]) - int(mx[1]) > 75 and int(mx[0]) > 110 and mean[1] < 75:
                    chaser = (gx, gy)
                elif int(mx[0]) > 215 and int(mx[1]) > 175 and (mean[0] - mean[2]) > 30:
                    items.add((gx, gy))
    door_patch = _cell_patch(frame, DOOR[0], DOOR[1]).mean(axis=(0, 1))
    door_open = (door_patch[1] > 160 and door_patch[0] < 100) if mode == "arena" else (door_patch[1] > 105)
    return mode, player, chaser, items, door_open


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
        self.unvisited: set[tuple[int, int]] = set(INITIAL_ITEMS)
        self. customised = False

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        seen = read_board(frame)
        if seen is None:
            raise Done("unreadable maze_chase picture")
        mode, player, chaser, visible_items, door_open = seen
        self.detected_look = mode
        if player is None:
            raise Done("no player in the picture")
        self.unvisited.discard(player)
        # If the chaser is temporarily standing on an unvisited item cell, keep that cell in the goal set
        goals = set(visible_items)
        if chaser is not None and chaser in self.unvisited:
            goals.add(chaser)
        if not goals or (door_open and not visible_items):
            goals = {DOOR}
        base_blocked = set(WALLS)
        if DOOR not in goals:
            base_blocked.add(DOOR)
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
