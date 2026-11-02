"""Walk the first-person Ray Maze from pixels: read the corner minimap and 3D view, shoot all five red targets, and exit.

Reads both the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned").
"""
from __future__ import annotations

from collections import deque

import numpy as np

from playfellow_coop.skills.base import Done, Frame

MAZE = (
    "##########",
    "#P..#..T.#",
    "#.#.#.##.#",
    "#.#...#..#",
    "#T#.#A#.##",
    "#...#...T#",
    "###.###.##",
    "#T....#..#",
    "#..A#.T..E",
    "##########",
)
FACINGS = ((0, -1), (1, 0), (0, 1), (-1, 0))  # N, E, S, W
VIEW_W, VIEW_H, TOP, MAP_CELL = 480, 300, 64, 9
WALLS = {(x, y) for y, row in enumerate(MAZE) for x, c in enumerate(row) if c == "#"}
INITIAL_TARGETS = [(1, 4), (7, 1), (8, 5), (1, 7), (6, 8)]
INITIAL_AMMO = [(5, 4), (3, 8)]
EXIT = (9, 8)


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Ray Maze."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + VIEW_H, VIEW_W):
        return None
    # Corner minimap cell (0,0) is wall (90, 90, 120) and exit cell (9,8) is green (90, 220, 120)
    w0 = frame[TOP + 6 + 1 : TOP + 6 + 8, 6 + 1 : 6 + 8].mean(axis=(0, 1))
    ex = frame[TOP + 6 + 8 * MAP_CELL + 1 : TOP + 6 + 9 * MAP_CELL - 1, 6 + 9 * MAP_CELL + 1 : 6 + 10 * MAP_CELL - 1].mean(axis=(0, 1))
    if not (80 <= w0[0] <= 100 and 80 <= w0[1] <= 100 and 110 <= w0[2] <= 130):
        return None
    if not (ex[1] > 190 and ex[0] < 110):
        return None
    sky = frame[TOP + 1 : TOP + 6, 120:200]
    if float(sky.std(axis=(0, 1)).mean()) < 1.0 and 20 <= sky.mean(axis=(0, 1))[0] <= 30:
        return "arena"
    return "skinned"


def read_minimap(frame: Frame) -> tuple[int, int, int] | None:
    """Read (x, y, facing) from the lime arrow on the top-left minimap."""
    mm = frame[TOP + 6 : TOP + 6 + 10 * MAP_CELL, 6 : 6 + 10 * MAP_CELL]
    mask = (mm[:, :, 1] > 220) & (mm[:, :, 0] > 150) & (mm[:, :, 2] < 90)
    ys, xs = np.where(mask)
    if len(xs) < 10:
        return None
    ymin, ymax = int(ys.min()), int(ys.max())
    xmin, xmax = int(xs.min()), int(xs.max())
    if (ymax - ymin) > (xmax - xmin):
        facing = 0 if int((ys == ymin).sum()) < int((ys == ymax).sum()) else 2
    else:
        facing = 1 if int((xs == xmax).sum()) < int((xs == xmin).sum()) else 3
    gx = int(round((float(xs.mean()) - 4.0) / MAP_CELL))
    gy = int(round((float(ys.mean()) - 4.0) / MAP_CELL))
    return gx, gy, facing


def target_ahead_in_view(frame: Frame) -> bool:
    """True when a red target bullseye/circle is visible in the centre of the first-person viewport."""
    centre = frame[TOP + VIEW_H // 2 - 20 : TOP + VIEW_H // 2 + 20, VIEW_W // 2 - 16 : VIEW_W // 2 + 16]
    red = (centre[:, :, 0] > 190) & (centre[:, :, 1] < 85) & (centre[:, :, 2] < 85)
    return int(red.sum()) >= 8


def _line_of_sight(pos: tuple[int, int], target: tuple[int, int], blocked: set[tuple[int, int]]) -> int | None:
    """If `pos` has a clear cardinal line of sight to `target`, return the required facing (0..3), else None."""
    px, py = pos
    tx, ty = target
    if (px, py) == (tx, ty):
        return None
    for fi, (dx, dy) in enumerate(FACINGS):
        x, y = px + dx, py + dy
        while (x, y) not in WALLS and (x, y) != EXIT:
            if (x, y) == (tx, ty):
                return fi
            if (x, y) in blocked:
                break
            x, y = x + dx, y + dy
    return None


def _bfs_next_cell(start: tuple[int, int], goal_fn, blocked: set[tuple[int, int]]) -> tuple[int, int] | None:
    queue = deque([(start, [])])
    seen = {start}
    while queue:
        cell, path = queue.popleft()
        if goal_fn(cell):
            return path[0] if path else cell
        for dx, dy in FACINGS:
            nxt = (cell[0] + dx, cell[1] + dy)
            if 0 <= nxt[0] < 10 and 0 <= nxt[1] < 10 and nxt not in blocked and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, path + [nxt]))
    return None


def _turn_toward(facing: int, want: int) -> str:
    if (facing + 1) % 4 == want:
        return "right"
    return "left"


def _step_key(facing: int, step_dir: int) -> str:
    diff = (step_dir - facing) % 4
    return ("w", "d", "s", "a")[diff]


class ClearRayMaze:
    name = "clear_ray_maze"
    about = "Navigate the 3D maze using the corner map and viewport, shoot all five red targets, collecting ammo, and walk out the exit."
    max_steps = 300
    looks = ("arena", "skinned")

    def __init__(self, look=None):
        self.look = look
        self.reset()

    def reset(self) -> None:
        self.detected_look: str | None = None
        self.targets: list[tuple[int, int]] = list(INITIAL_TARGETS)
        self.ammo_boxes: list[tuple[int, int]] = list(INITIAL_AMMO)
        self.ammo = 3

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable ray_maze picture")
        self.detected_look = mode
        pose = read_minimap(frame)
        if pose is None:
            raise Done("no player on minimap")
        x, y, facing = pose
        pos = (x, y)
        if pos in self.ammo_boxes:
            self.ammo_boxes.remove(pos)
            self.ammo += 2

        # Check if we are currently aligned with any remaining target in line of sight
        blocked_targets = set(self.targets)
        for t in list(self.targets):
            los = _line_of_sight(pos, t, blocked_targets - {t})
            if los == facing:
                if target_ahead_in_view(frame) and self.ammo > 0:
                    self.ammo -= 1
                    self.targets.remove(t)
                    return "space"
                if not target_ahead_in_view(frame):
                    # Target was already cleared from the picture
                    self.targets.remove(t)

        # If a red target is directly ahead in the viewport right now and we have ammo, shoot it
        if target_ahead_in_view(frame) and self.ammo > 0:
            self.ammo -= 1
            return "space"

        # Decide next objective: if ammo == 0 and ammo boxes remain, go to nearest ammo box;
        # else if targets remain, go to a vantage point for the next target (picking up ammo box on the way if needed);
        # else walk to EXIT (9, 8).
        if self.targets:
            if self.ammo == 0 and self.ammo_boxes:
                goal_ammo = self.ammo_boxes[0]
                nxt = _bfs_next_cell(pos, lambda c: c == goal_ammo, WALLS | {EXIT} | set(self.targets))
            else:
                target = self.targets[0]
                los = _line_of_sight(pos, target, set(self.targets) - {target})
                if los is not None:
                    return _turn_toward(facing, los)
                nxt = _bfs_next_cell(
                    pos,
                    lambda c: _line_of_sight(c, target, set(self.targets) - {target}) is not None,
                    WALLS | {EXIT} | set(self.targets),
                )
        else:
            if pos == (8, 8):
                if facing != 3:
                    return _turn_toward(facing, 3)
                return "s"
            nxt = _bfs_next_cell(pos, lambda c: c == (8, 8), WALLS | {EXIT})

        if nxt is None or nxt == pos:
            return "w"
        dx, dy = nxt[0] - x, nxt[1] - y
        want_dir = FACINGS.index((dx, dy))
        return _step_key(facing, want_dir)
