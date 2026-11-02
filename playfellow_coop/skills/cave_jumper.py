"""Navigate three cave rooms from pixels: jump the spikes, grab the jump boots, double-jump to the high key ledge, and unlock the door.

Reads rock tiles, spikes, door, boots, key, player, and HUD room/status directly from the pixels on both
the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned"), with no copied map.
"""
from __future__ import annotations

from collections import deque
from functools import lru_cache

import numpy as np
from PIL import Image, ImageDraw, ImageFont

from playfellow_coop.skills.base import Done, Frame

ROOM_W, ROOMS, ROWS = 16, 3, 10
TILE, TOP, JUMP = 40, 64, 3


def _patch(frame: Frame, col: int, gy: int, x_in: int = 8, y_in: int = 8) -> np.ndarray:
    x0, y0 = col * TILE + x_in, TOP + gy * TILE + y_in
    return frame[y0 : y0 + TILE - 2 * y_in, x0 : x0 + TILE - 2 * x_in]


@lru_cache(maxsize=1)
def _hud_templates() -> dict[tuple[int, bool, bool], np.ndarray]:
    try:
        f16 = ImageFont.truetype("arial.ttf", 16)
    except OSError:
        f16 = ImageFont.load_default()
    dummy = ImageDraw.Draw(Image.new("L", (1, 1)))
    out: dict[tuple[int, bool, bool], np.ndarray] = {}
    for r in (1, 2, 3):
        for b in ("no", "yes"):
            for k in ("no", "yes"):
                text = f"Room {r}/3    Boots: {b}    Key: {k}"
                w = max(1, dummy.textbbox((0, 0), text, font=f16)[2])
                im = Image.new("L", (w + 4, 22), 0)
                ImageDraw.Draw(im).text((0, 0), text, fill=255, font=f16)
                out[(r - 1, b == "yes", k == "yes")] = np.asarray(im, dtype=np.float32) / 255.0
    return out


def read_hud(frame: Frame) -> tuple[int, bool, bool]:
    """Read (room_index, has_boots, has_key) from the HUD line at y=36..58."""
    strip = frame[36:58, 12:340].astype(np.float32)
    bg = np.median(strip, axis=(0, 1))
    fg = np.linalg.norm(strip - bg, axis=2)
    fg = fg / max(float(fg.max()), 1.0)
    best: tuple[float, tuple[int, bool, bool]] | None = None
    for state, tmpl in _hud_templates().items():
        w = min(fg.shape[1], tmpl.shape[1])
        sub = fg[:, :w]
        t_sub = tmpl[:, :w]
        score = float((sub * t_sub).sum() - 0.5 * ((sub - t_sub) ** 2).sum())
        if best is None or score > best[0]:
            best = (score, state)
    assert best is not None
    return best[1]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Key Caves."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + ROWS * TILE, ROOM_W * TILE):
        return None
    rock = _patch(frame, 0, 0)
    rock_m = rock.mean(axis=(0, 1))
    sky_candidates = [
        _patch(frame, c, gy).mean(axis=(0, 1))
        for gy in range(1, ROWS - 1)
        for c in range(1, ROOM_W - 1)
    ]
    sky_m = min(sky_candidates, key=lambda m: float(m.mean()))
    if float(np.abs(rock_m - sky_m).sum()) < 12.0:
        return None
    if 80 <= rock_m[0] <= 105 and 65 <= rock_m[1] <= 85 and 105 <= rock_m[2] <= 135 and sky_m[0] < 35 and sky_m[1] < 30:
        return "arena"
    if float(rock.std(axis=(0, 1)).mean()) > 4.0 and 30 <= rock_m[0] <= 65 and 50 <= rock_m[2] <= 85:
        return "skinned"
    return None


def _boots_on_player(frame: Frame, col: int, gy: int, mode: str) -> bool:
    x0, y0 = col * TILE, TOP + gy * TILE
    if mode == "arena":
        feet = frame[y0 + 32 : y0 + 38, x0 + 10 : x0 + 30].mean(axis=(0, 1))
        return bool(feet[1] > 190 and feet[2] > 220 and feet[0] < 70)
    feet = frame[y0 + 22 : y0 + 36, x0 + 8 : x0 + 32]
    cyan = (feet[:, :, 0] < 65) & (feet[:, :, 1] > 195) & (feet[:, :, 2] > 225)
    return int(cyan.sum()) >= 35


def read_room_tiles(frame: Frame, mode: str, room: int):
    """Read (rocks, spikes, door_pos, boots_pos, key_pos, player_pos, player_col_gy) from the 16x10 room picture."""
    rock0 = frame[TOP + 2 : TOP + 12, 2 : 12].astype(np.float32)
    first = room * ROOM_W
    rocks: set[tuple[int, int]] = set()
    spikes: set[tuple[int, int]] = set()
    door_pos: tuple[int, int] | None = None
    boots_pos: tuple[int, int] | None = None
    key_pos: tuple[int, int] | None = None
    player_pos: tuple[int, int] | None = None
    player_local: tuple[int, int] | None = None
    best_p_score = 0.0

    for gy in range(ROWS):
        for col in range(ROOM_W):
            wx = first + col
            x0, y0 = col * TILE, TOP + gy * TILE
            cell = frame[y0 : y0 + TILE, x0 : x0 + TILE]
            corner = cell[2:12, 2:12].astype(np.float32)
            if float(np.abs(corner - rock0).mean()) < 2.5:
                rocks.add((wx, gy))
                continue

            if mode == "arena":
                top_b = cell[3:10, 10:30].mean(axis=(0, 1))
                if (top_b[0] > 130 and 70 < top_b[1] < 110 and top_b[2] < 60) or (top_b[1] > 175 and top_b[0] < 110):
                    door_pos = (wx, gy)
                    continue
            else:
                c_m = cell[2:8, 2:8].mean(axis=(0, 1))
                mid_m = cell[10:30, 10:30].mean(axis=(0, 1))
                if 28 <= c_m[0] <= 37 and 40 <= c_m[1] <= 51 and 62 <= c_m[2] <= 73 and mid_m[2] > 115 and mid_m[0] < 70:
                    door_pos = (wx, gy)
                    continue

            upper = cell[5:19, 10:30]
            u_mean = upper.mean(axis=(0, 1))
            is_player = False
            if mode == "arena":
                if u_mean[2] > 210 and u_mean[0] > 100 and u_mean[1] < 120:
                    is_player = True
                    score = float(u_mean[2])
                    if score > best_p_score:
                        best_p_score, player_pos, player_local = score, (wx, gy), (col, gy)
            else:
                u_mx = upper.max(axis=(0, 1))
                if int(u_mx[2]) > 215 and int(u_mx[1]) > 185 and u_mean[2] > 135:
                    is_player = True
                    score = float(u_mean[2] + u_mean[1])
                    if score > best_p_score:
                        best_p_score, player_pos, player_local = score, (wx, gy), (col, gy)
            if is_player:
                continue

            k_patch = cell[8:28, 8:34]
            gold = (k_patch[:, :, 0] > 200) & (k_patch[:, :, 1] > 150) & (k_patch[:, :, 2] < 95)
            if int(gold.sum()) >= 12:
                key_pos = (wx, gy)
                continue

            top_spike = cell[8:15, 4:36].max(axis=(0, 1))
            if int(top_spike[0]) > 210 and int(top_spike[1]) > 210 and int(top_spike[2]) > 210:
                spikes.add((wx, gy))
                continue

            bot_patch = cell[18:35, 8:32]
            cyan = (bot_patch[:, :, 0] < 80) & (bot_patch[:, :, 1] > 195) & (bot_patch[:, :, 2] > 225)
            if int(cyan.sum()) >= 25:
                boots_pos = (wx, gy)

    return rocks, spikes, door_pos, boots_pos, key_pos, player_pos, player_local


def _step_physics(
    x: int,
    y: int,
    rise: int,
    jumps: int,
    has_boots: bool,
    action: str | None,
    solid: set[tuple[int, int]],
    spikes: set[tuple[int, int]],
) -> tuple[int, int, int, int] | None:
    nx, ny, nrise, njumps = x, y, rise, jumps
    on_g = (nx, ny + 1) in solid
    if action in ("left", "right"):
        tx = nx + (1 if action == "right" else -1)
        if (tx, ny) not in solid:
            nx = tx
            if (nx, ny) in spikes:
                return None
    elif action == "space":
        if on_g:
            nrise, njumps = JUMP, 1
        elif has_boots and njumps < 2:
            nrise, njumps = JUMP, 2

    if nrise > 0:
        if (nx, ny - 1) in solid:
            nrise = 0
        else:
            ny -= 1
            nrise -= 1
    elif (nx, ny + 1) not in solid:
        ny += 1
    if (nx, ny + 1) in solid and nrise == 0:
        njumps = 0
    if (nx, ny) in spikes or not (0 <= nx < ROOM_W * ROOMS and 0 <= ny < ROWS):
        return None
    return nx, ny, nrise, njumps


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
        w_total = ROOM_W * ROOMS
        self.rocks: set[tuple[int, int]] = (
            {(x, 0) for x in range(w_total)}
            | {(x, ROWS - 1) for x in range(w_total)}
            | {(0, y) for y in range(ROWS)}
            | {(w_total - 1, y) for y in range(ROWS)}
        )
        self.spikes: set[tuple[int, int]] = set()
        self.door_pos: tuple[int, int] | None = None
        self.boots_pos: tuple[int, int] | None = None
        self.key_pos: tuple[int, int] | None = None
        self.has_boots = False
        self.has_key = False
        self.rise = 0
        self.jumps = 0

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable key_caves picture")
        self.detected_look = mode
        room, hud_boots, hud_key = read_hud(frame)
        r_rocks, r_spikes, r_door, r_boots, r_key, player, player_local = read_room_tiles(frame, mode, room)
        if player is None or player_local is None:
            raise Done("no player in the picture")

        first = room * ROOM_W
        self.rocks = {pt for pt in self.rocks if not (first <= pt[0] < first + ROOM_W)} | r_rocks
        self.spikes = {pt for pt in self.spikes if not (first <= pt[0] < first + ROOM_W)} | r_spikes
        if r_door is not None:
            self.door_pos = r_door
        if r_boots is not None:
            self.boots_pos = r_boots
        if r_key is not None:
            self.key_pos = r_key

        x, y = player
        col, gy = player_local
        if hud_boots or _boots_on_player(frame, col, gy, mode) or (self.boots_pos is not None and (x, y) == self.boots_pos):
            self.has_boots = True
        if hud_key or (self.key_pos is not None and (x, y) == self.key_pos):
            self.has_key = True
            self.has_boots = True

        solid = set(self.rocks)
        if self.door_pos is not None:
            solid.add(self.door_pos)
        if (x, y + 1) in solid and self.rise == 0:
            self.jumps = 0

        if self.has_key and self.door_pos is not None and y == self.door_pos[1] and abs(x - self.door_pos[0]) == 1:
            return "z"

        if not self.has_boots:
            if self.boots_pos is not None:
                goal_fn = lambda sx, sy: (sx, sy) == self.boots_pos
            else:
                target_x = min(ROOM_W * ROOMS - 2, (room + 1) * ROOM_W + 1)
                goal_fn = lambda sx, sy: sx >= target_x and (sx, sy + 1) in solid
        elif not self.has_key:
            if self.key_pos is not None:
                goal_fn = lambda sx, sy: (sx, sy) == self.key_pos
            else:
                target_x = min(ROOM_W * ROOMS - 2, (room + 1) * ROOM_W + 1)
                goal_fn = lambda sx, sy: sx >= target_x and (sx, sy + 1) in solid
        else:
            if self.door_pos is not None:
                dp = self.door_pos
                goal_fn = lambda sx, sy: sy == dp[1] and abs(sx - dp[0]) == 1
            else:
                goal_fn = lambda sx, sy: sx <= 2 and (sx, sy + 1) in solid

        start = (x, y, self.rise, self.jumps)
        q: deque[tuple[tuple[int, int, int, int], str | None]] = deque([(start, None)])
        seen = {start}
        chosen: str | None = "right"
        found = False
        while q:
            st, first_act = q.popleft()
            if goal_fn(st[0], st[1]) and st != start:
                chosen = first_act
                found = True
                break
            for act in ("right", "left", "space", None):
                nxt = _step_physics(st[0], st[1], st[2], st[3], self.has_boots, act, solid, self.spikes)
                if nxt is not None and nxt not in seen:
                    seen.add(nxt)
                    q.append((nxt, act if not found and st == start else first_act))

        nxt_st = _step_physics(x, y, self.rise, self.jumps, self.has_boots, chosen, solid, self.spikes)
        if nxt_st is not None:
            self.rise, self.jumps = nxt_st[2], nxt_st[3]
        return chosen
