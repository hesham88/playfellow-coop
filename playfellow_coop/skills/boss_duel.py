"""Beat the Action Quest boss from pixels: step out of telegraphed red danger squares and strike when safe.

Reads both the public engine's plain look ("arena") and the Lightfolk glass skin ("skinned").
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done, Frame

COLS, ROWS = 13, 9
TILE, TOP = 44, 64
MOVES = {"w": (0, -1), "s": (0, 1), "a": (-1, 0), "d": (1, 0)}


def _interior(frame: Frame, gx: int, gy: int, inset: int = 8) -> np.ndarray:
    x0, y0 = gx * TILE + inset, TOP + gy * TILE + inset
    return frame[y0 : y0 + TILE - 2 * inset, x0 : x0 + TILE - 2 * inset]


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if the picture is not Action Quest."""
    if frame.ndim != 3 or frame.shape[:2] != (TOP + ROWS * TILE, COLS * TILE):
        return None
    corners = [_interior(frame, gx, gy) for gx, gy in ((0, 0), (12, 0), (0, 8), (12, 8))]
    stds = [float(c.std(axis=(0, 1)).mean()) for c in corners]
    means = [c.mean(axis=(0, 1)) for c in corners]
    med = np.median(np.stack(means), axis=0)
    # Require that the board has a hero or boss distinct from the corner floor
    board_std = float(frame[TOP:, :].std())
    if board_std < 8.0:
        return None
    if min(stds) < 1.0 and 35 <= med[0] <= 46 and 38 <= med[1] <= 50 and 50 <= med[2] <= 66:
        return "arena"
    if min(stds) > 3.0 and 20 <= med[0] <= 45 and 30 <= med[1] <= 55 and 40 <= med[2] <= 70:
        return "skinned"
    return None


def read_board(frame: Frame):
    """Read (mode, hero, boss, danger_set) from the picture."""
    mode = detect_look(frame)
    if mode is None:
        return None
    danger: set[tuple[int, int]] = set()
    hero: tuple[int, int] | None = None
    boss: tuple[int, int] | None = None
    best_boss_score = -1.0
    for gy in range(ROWS):
        for gx in range(COLS):
            x0, y0 = gx * TILE, TOP + gy * TILE
            bl = frame[y0 + 36 : y0 + 41, x0 + 2 : x0 + 6].mean(axis=(0, 1))
            br = frame[y0 + 36 : y0 + 41, x0 + 38 : x0 + 42].mean(axis=(0, 1))
            if (bl[0] > 115 and bl[1] < 68 and bl[0] - bl[1] > 55) or (br[0] > 115 and br[1] < 68 and br[0] - br[1] > 55):
                danger.add((gx, gy))
            cx, cy = x0 + TILE // 2, y0 + TILE // 2
            if int(frame[cy, cx].min()) > 240:
                for fx, fy in ((1, 0), (-1, 0), (0, 1), (0, -1)):
                    if int(frame[cy + fy * 10, cx + fx * 10].min()) > 240:
                        hero = (gx, gy)
                        break
    for gy in range(ROWS):
        for gx in range(COLS):
            if (gx, gy) == hero:
                continue
            x0, y0 = gx * TILE, TOP + gy * TILE
            mid = frame[y0 + 14 : y0 + 28, x0 + 14 : x0 + 30].mean(axis=(0, 1))
            if mode == "arena":
                if mid[0] > 200 and 95 < mid[1] < 150 and mid[2] < 65:
                    score = float(mid[0] - mid[2])
                    if score > best_boss_score:
                        best_boss_score, boss = score, (gx, gy)
            else:
                sh = frame[y0 + 35 : y0 + 39, x0 + 18 : x0 + 26].mean(axis=(0, 1))
                if sh.max() < 22 and mid[2] > 95:
                    score = float(mid[2] - sh.mean())
                    if score > best_boss_score:
                        best_boss_score, boss = score, (gx, gy)
    return mode, hero, boss, danger


class BeatBoss:
    name = "beat_boss"
    about = "Dodge red telegraphed boss attacks, close the gap when the floor is safe, and strike the boss down."
    max_steps = 600
    looks = ("arena", "skinned")

    def __init__(self, look=None):
        self.look = look
        self.reset()

    def reset(self) -> None:
        self.detected_look: str | None = None
        self.last_boss: tuple[int, int] = (9, 4)

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        seen = read_board(frame)
        if seen is None:
            raise Done("unreadable action_quest picture")
        mode, hero, boss, danger = seen
        self.detected_look = mode
        if hero is None:
            raise Done("no hero in the picture")
        if boss is not None:
            self.last_boss = boss
        bx, by = self.last_boss
        hx, hy = hero

        # 1. If standing on a red danger tile, immediately step to a safe tile (or further away from the danger zone)
        if hero in danger:
            best_key = None
            best_rank = None
            for key, (dx, dy) in MOVES.items():
                nx, ny = hx + dx, hy + dy
                if not (0 <= nx < COLS and 0 <= ny < ROWS) or (nx, ny) == (bx, by):
                    continue
                in_danger = 1 if (nx, ny) in danger else 0
                # Count how many neighbors of (nx, ny) are also safe, and prefer moving away from boss
                dist_boss = abs(nx - bx) + abs(ny - by)
                rank = (in_danger, -dist_boss)
                if best_rank is None or rank < best_rank:
                    best_rank, best_key = rank, key
            if best_key is not None:
                return best_key
            return "l"

        # 2. If safe and within strike range (Chebyshev distance <= 1), light attack with 'j'
        if max(abs(hx - bx), abs(hy - by)) <= 1:
            return "j"

        # 3. If danger is active elsewhere on the board, wait outside danger at a safe staging spot
        if danger:
            best_key = None
            best_rank = None
            for key, (dx, dy) in MOVES.items():
                nx, ny = hx + dx, hy + dy
                if not (0 <= nx < COLS and 0 <= ny < ROWS) or (nx, ny) == (bx, by) or (nx, ny) in danger:
                    continue
                cheb = max(abs(nx - bx), abs(ny - by))
                rank = (abs(cheb - 3), abs(nx - bx) + abs(ny - by))
                if best_rank is None or rank < best_rank:
                    best_rank, best_key = rank, key
            return best_key

        # 4. Danger is empty: step toward a diagonal/adjacent strike spot next to the boss
        best_key = None
        best_rank = None
        for key, (dx, dy) in MOVES.items():
            nx, ny = hx + dx, hy + dy
            if not (0 <= nx < COLS and 0 <= ny < ROWS) or (nx, ny) == (bx, by) or (nx, ny) in danger:
                continue
            cheb = max(abs(nx - bx), abs(ny - by))
            manh = abs(nx - bx) + abs(ny - by)
            # Prefer diagonal adjacency (cheb == 1 and manh == 2) so charges cannot trigger
            diag_bonus = 0 if (cheb == 1 and manh == 2) else 1
            rank = (cheb, diag_bonus, manh)
            if best_rank is None or rank < best_rank:
                best_rank, best_key = rank, key
        return best_key or "j"
