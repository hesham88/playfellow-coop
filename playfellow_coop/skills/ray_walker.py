"""Walk the first-person Ray Maze from pixels: read the corner minimap, HUD line, and 3D view, shoot all five red targets, and exit.

Reads walls, exit, player pose, targets, and ammo directly from the pixels on both
the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned"), with no copied map.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from playfellow_coop.skills.base import Done, Frame

FACINGS = ((0, -1), (1, 0), (0, 1), (-1, 0))  # N, E, S, W
VIEW_W, VIEW_H, TOP, MAP_CELL, GRID = 480, 300, 64, 9, 10


@lru_cache(maxsize=1)
def _hud_templates() -> dict[tuple[int, int], np.ndarray]:
    try:
        f16 = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        f16 = ImageFont.load_default()
    dummy = ImageDraw.Draw(Image.new("L", (1, 1)))
    out: dict[tuple[int, int], np.ndarray] = {}
    for h in range(10):
        for a in range(12):
            text = f"Targets {h}/5    Ammo {a}    "
            w = max(1, dummy.textbbox((0, 0), text, font=f16)[2])
            im = Image.new("L", (w, 22), 0)
            ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f16)
            out[(h, a)] = np.asarray(im, dtype=np.float32) / 255.0
    return out


def read_hud(frame: Frame) -> tuple[int, int, int]:
    """Read (hits, total_targets, ammo) from the HUD line at y=36..58."""
    strip = frame[36:58, 12:260].astype(np.float32)
    bg = np.median(strip, axis=(0, 1))
    fg = np.linalg.norm(strip - bg, axis=2)
    fg = fg / max(float(fg.max()), 1.0)
    best: tuple[float, int, int] | None = None
    for (h, a), tmpl in _hud_templates().items():
        w = min(fg.shape[1], tmpl.shape[1])
        sub = fg[:, :w]
        t_sub = tmpl[:, :w]
        score = float((sub * t_sub).sum() - 0.5 * ((sub - t_sub) ** 2).sum())
        if best is None or score > best[0]:
            best = (score, h, a)
    assert best is not None
    return best[1], 5, best[2]


def read_minimap_full(frame: Frame) -> tuple[int, int, int, set[tuple[int, int]], tuple[int, int]] | None:
    """Read (x, y, facing, walls, exit_cell) from the 10x10 top-left minimap."""
    mm = frame[TOP + 6 : TOP + 6 + GRID * MAP_CELL, 6 : 6 + GRID * MAP_CELL]
    arrow = (mm[:, :, 1] > 220) & (mm[:, :, 0] > 150) & (mm[:, :, 2] < 90)
    ys, xs = np.where(arrow)
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

    walls: set[tuple[int, int]] = set()
    exit_cell: tuple[int, int] | None = None
    for cy in range(GRID):
        for cx in range(GRID):
            y0, x0 = cy * MAP_CELL, cx * MAP_CELL
            cell = mm[y0 : y0 + MAP_CELL - 1, x0 : x0 + MAP_CELL - 1]
            c_arrow = arrow[y0 : y0 + MAP_CELL - 1, x0 : x0 + MAP_CELL - 1]
            non_arrow = cell[~c_arrow]
            if len(non_arrow) == 0:
                continue
            m = np.median(non_arrow, axis=0)
            if 75 <= m[0] <= 105 and 75 <= m[1] <= 105 and 105 <= m[2] <= 135:
                walls.add((cx, cy))
            elif m[1] > 180 and m[0] < 115:
                exit_cell = (cx, cy)
    if exit_cell is None:
        return None
    return gx, gy, facing, walls, exit_cell


def read_minimap(frame: Frame) -> tuple[int, int, int] | None:
    """Read (x, y, facing) from the lime arrow on the top-left minimap."""
    full = read_minimap_full(frame)
    if full is None:
        return None
    return full[0], full[1], full[2]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Ray Maze."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + VIEW_H, VIEW_W):
        return None
    w0 = frame[TOP + 6 + 1 : TOP + 6 + 8, 6 + 1 : 6 + 8].mean(axis=(0, 1))
    if not (80 <= w0[0] <= 100 and 80 <= w0[1] <= 100 and 110 <= w0[2] <= 130):
        return None
    if read_minimap_full(frame) is None:
        return None
    sky = frame[TOP + 1 : TOP + 6, 120:200]
    if float(sky.std(axis=(0, 1)).mean()) < 1.0 and 20 <= sky.mean(axis=(0, 1))[0] <= 30:
        return "arena"
    return "skinned"


def target_ahead_in_view(frame: Frame) -> bool:
    """True when a red target bullseye/circle is visible in the centre of the first-person viewport."""
    centre = frame[TOP + VIEW_H // 2 - 22 : TOP + VIEW_H // 2 + 12, VIEW_W // 2 - 16 : VIEW_W // 2 + 16]
    red = (centre[:, :, 0] > 190) & (centre[:, :, 1] < 85) & (centre[:, :, 2] < 85)
    return int(red.sum()) >= 6


def ammo_ahead_in_view(frame: Frame) -> bool:
    """True when a yellow ammo box is visible in the lower-centre of the first-person viewport."""
    centre = frame[TOP + VIEW_H // 2 + 2 : TOP + VIEW_H // 2 + 48, VIEW_W // 2 - 16 : VIEW_W // 2 + 16]
    yel = (centre[:, :, 0] > 210) & (centre[:, :, 1] > 175) & (centre[:, :, 2] < 95)
    return int(yel.sum()) >= 6


def _ray_cells(pos: tuple[int, int], d: int, blocked: set[tuple[int, int]]) -> list[tuple[int, int]]:
    dx, dy = FACINGS[d]
    x, y = pos[0] + dx, pos[1] + dy
    out: list[tuple[int, int]] = []
    while 0 <= x < GRID and 0 <= y < GRID and (x, y) not in blocked:
        out.append((x, y))
        x, y = x + dx, y + dy
    return out


def _turn_toward(facing: int, want: int) -> str:
    return "right" if (facing + 1) % 4 == want else "left"


class ClearRayMaze:
    name = "clear_ray_maze"
    about = "Navigate the 3D maze using the corner map, HUD, and viewport, shoot all five red targets, collecting ammo, and walk out the exit."
    max_steps = 300
    looks = ("arena", "skinned")

    def __init__(self, look=None):
        self.look = look
        self.reset()

    def reset(self) -> None:
        self.detected_look: str | None = None
        self.visited: set[tuple[int, int]] = set()
        self.clear_cells: set[tuple[int, int]] = set()
        self.known_targets: set[tuple[int, int]] = set()
        self.ammo_rays: set[tuple[int, int]] = set()
        self.last_pos: tuple[int, int] | None = None
        self.last_step_target: tuple[int, int] | None = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def _bfs_dists(self, start: tuple[int, int], blocked: set[tuple[int, int]]) -> dict[tuple[int, int], tuple[int, tuple[int, int] | None]]:
        q: deque[tuple[tuple[int, int], int, tuple[int, int] | None]] = deque([(start, 0, None)])
        out: dict[tuple[int, int], tuple[int, tuple[int, int] | None]] = {start: (0, None)}
        while q:
            curr, dist, first = q.popleft()
            for dx, dy in FACINGS:
                nxt = (curr[0] + dx, curr[1] + dy)
                if 0 <= nxt[0] < GRID and 0 <= nxt[1] < GRID and nxt not in blocked and nxt not in out:
                    nf = first or nxt
                    out[nxt] = (dist + 1, nf)
                    q.append((nxt, dist + 1, nf))
        return out

    def _step_to(self, pos: tuple[int, int], facing: int, nxt: tuple[int, int]) -> str:
        self.last_step_target = nxt
        dx, dy = nxt[0] - pos[0], nxt[1] - pos[1]
        want_dir = FACINGS.index((dx, dy))
        diff = (want_dir - facing) % 4
        return ("w", "d", "s", "a")[diff]

    def _move_toward(self, pos: tuple[int, int], facing: int, goals: set[tuple[int, int]], blocked: set[tuple[int, int]]) -> str:
        dists = self._bfs_dists(pos, blocked)
        best: tuple[int, tuple[int, int]] | None = None
        for g in goals:
            if g in dists and g != pos:
                d, first = dists[g]
                if first is not None and (best is None or d < best[0]):
                    best = (d, first)
        if best is not None:
            return self._step_to(pos, facing, best[1])
        return "left"

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable ray_maze picture")
        self.detected_look = mode
        mm = read_minimap_full(frame)
        if mm is None:
            raise Done("no player on minimap")
        px, py, facing, walls, exit_cell = mm
        hits, total_targets, ammo = read_hud(frame)
        pos = (px, py)
        hard_blocked = walls | {exit_cell}

        if self.last_pos == pos and self.last_step_target is not None and self.last_step_target not in hard_blocked:
            self.known_targets.add(self.last_step_target)
        self.last_pos = pos
        self.last_step_target = None

        self.visited.add(pos)
        self.clear_cells.add(pos)
        self.known_targets.discard(pos)
        self.ammo_rays.discard(pos)

        t_ahead = target_ahead_in_view(frame)
        a_ahead = ammo_ahead_in_view(frame)
        rc = _ray_cells(pos, facing, hard_blocked)

        if t_ahead:
            if ammo > 0:
                return "space"
        else:
            for c in rc:
                self.clear_cells.add(c)
                self.known_targets.discard(c)
        if a_ahead:
            for c in rc:
                if c not in self.visited:
                    self.ammo_rays.add(c)
                    break

        if hits >= total_targets:
            adj = None
            exit_dir = 1
            for d, (dx, dy) in enumerate(FACINGS):
                nb = (exit_cell[0] - dx, exit_cell[1] - dy)
                if 0 <= nb[0] < GRID and 0 <= nb[1] < GRID and nb not in hard_blocked:
                    adj = nb
                    exit_dir = d
                    break
            if adj is None:
                return "w"
            if pos == adj:
                away = (exit_dir + 2) % 4
                if facing != away:
                    return _turn_toward(facing, away)
                return "s"
            return self._move_toward(pos, facing, {adj}, hard_blocked)

        walk_blocked = hard_blocked | self.known_targets
        all_walkable = {(gx, gy) for gy in range(GRID) for gx in range(GRID) if (gx, gy) not in hard_blocked}

        if ammo == 0:
            goals = (self.ammo_rays - self.visited - self.known_targets) or (all_walkable - self.visited - self.known_targets)
            return self._move_toward(pos, facing, goals, walk_blocked)

        if a_ahead and ammo < (total_targets - hits) and rc and rc[0] not in walk_blocked and not t_ahead:
            return self._step_to(pos, facing, rc[0])

        uncleared = (all_walkable - self.clear_cells) | self.known_targets
        best = None
        dists = self._bfs_dists(pos, walk_blocked)
        for c, (dist, first_step) in dists.items():
            for d in range(4):
                r = _ray_cells(c, d, hard_blocked)
                if any(u in uncleared for u in r):
                    turns = 0 if d == facing else (2 if (d - facing) % 4 == 2 else 1)
                    has_known = 0 if any(u in self.known_targets for u in r) else 1
                    cost = (has_known, dist * 2 + turns)
                    if best is None or cost < best[0]:
                        best = (cost, c, d, first_step)
        if best is not None:
            _, c, d, first_step = best
            if c == pos:
                return _turn_toward(facing, d)
            assert first_step is not None
            return self._step_to(pos, facing, first_step)

        goals = all_walkable - self.visited - self.known_targets
        return self._move_toward(pos, facing, goals, walk_blocked)
