"""A 0..1 progress score for the open-source web 2048 (Gabriele Cirulli, MIT), plus a headless board that lets the gym host it without a browser.

    from bench.osg_progress import progress  # gym-compatible: progress(p0, p) -> 0..1

The score follows the gym's rules (playfellow_coop/gym/progress.py, env.py): it is how far the best tile has climbed toward
the game's own winning tile on a doubling (log2) scale, relative to the episode's first board. Doing nothing earns nothing
(the board is unchanged, so the climb is zero), the page's score number earns nothing (it is never read here: points can be
farmed by merging small tiles without ever nearing the win), and 1.0 comes only with the game's own win (a 2048 tile);
PlayfellowGym's completion bonus then makes a won episode return exactly 1.0, and any 1.0 without a win would be flagged
as reward hacking by gym/oracle.check_game. Recorded boards are enough to test every one of those properties.

One-line hook the architect's gym/progress.py needs (not made here, that file is his):
    "osg_2048": progress,   # with: from bench.osg_progress import progress as _osg_progress (name it as that module prefers)

The headless board below reuses the repo's own move logic (skills.tile_merge.move, the same slide the 2048 skill looks
ahead with) and the web game's palette, seeded spawns (a 2 at 90%, a 4 at 10%, as the web game does), so a SkillSmith
round can be rehearsed offline. The browser path in bench/osg_2048.py (the architect's) stays the measured web result.
"""
from __future__ import annotations

import math
import random

WIN_TILE = 2048
SIZE = 4
# The web game's own palette (bench/osg_2048.py, from its style/main.css): used only to draw the headless board.
PALETTE = {0: (205, 193, 180), 2: (238, 228, 218), 4: (237, 224, 200), 8: (242, 177, 121), 16: (245, 149, 99), 32: (246, 124, 95),
           64: (246, 94, 59), 128: (237, 207, 114), 256: (237, 204, 97), 512: (237, 200, 80), 1024: (237, 197, 63), 2048: (237, 194, 46)}


def _frac(a: float, b: float) -> float:
    return max(0.0, min(1.0, a / b)) if b else 0.0


def best_tile(board) -> int:
    return max((max(row) for row in board), default=0)


def progress(p0: dict, p: dict) -> float:
    """The gym-compatible score: p0 and p are progress() dicts ({best_tile, target, ...}). The score field, if present, is ignored on purpose."""
    start = max(2, int(p0.get("best_tile") or 2))
    now = max(2, int(p.get("best_tile") or 2))
    target = int(p.get("target") or WIN_TILE)
    if start >= target:
        return 1.0 if now >= target else 0.0
    return _frac(math.log2(now) - math.log2(start), math.log2(target) - math.log2(start))


def board_progress(initial, current) -> float:
    """The same score directly on two 4x4 boards (recorded boards need no game object)."""
    return progress({"best_tile": best_tile(initial), "target": WIN_TILE}, {"best_tile": best_tile(current), "target": WIN_TILE})


def _slide_row(row):
    """(slid row, points gained): each pair joins once, as in skills.tile_merge.slide_row."""
    tiles = [v for v in row if v]
    out, gain, i = [], 0, 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            out.append(tiles[i] * 2)
            gain += tiles[i] * 2
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    return out + [0] * (SIZE - len(out)), gain


def move_with_gain(board, key: str):
    """(board after the slide, points gained), before any new tile spawns. Mirrors skills.tile_merge.move."""
    grid = [r[:] for r in board]
    if key in ("up", "down"):
        grid = [list(c) for c in zip(*grid)]
    if key in ("right", "down"):
        grid = [r[::-1] for r in grid]
    gain = 0
    slid = []
    for row in grid:
        new_row, row_gain = _slide_row(row)
        slid.append(new_row)
        gain += row_gain
    grid = slid
    if key in ("right", "down"):
        grid = [r[::-1] for r in grid]
    if key in ("up", "down"):
        grid = [list(c) for c in zip(*grid)]
    return grid, gain


class Osg2048Game:
    """The web 2048's rules headlessly: slide and merge, spawn on a changed board only, win at 2048, lost when no move changes the board."""

    keys = ("left", "right", "up", "down")
    max_ticks = 2000
    pixel_size = (208, 208)

    def __init__(self, seed: int = 0):
        self.seed = int(seed)
        self._rng = random.Random(self.seed * 2654435761 + 12345)
        self.board = [[0] * SIZE for _ in range(SIZE)]
        self.score = 0
        self.moves = 0
        self.ticks = 0
        self._spawn()
        self._spawn()

    def _spawn(self) -> None:
        empties = [(x, y) for y in range(SIZE) for x in range(SIZE) if not self.board[y][x]]
        if not empties:
            return
        x, y = empties[self._rng.randrange(len(empties))]
        self.board[y][x] = 4 if self._rng.random() < 0.1 else 2

    @property
    def best(self) -> int:
        return best_tile(self.board)

    def is_won(self) -> bool:
        return self.best >= WIN_TILE

    def is_lost(self) -> bool:
        if self.is_won():
            return False
        return all(move_with_gain(self.board, key)[0] == self.board for key in self.keys)

    @property
    def done(self) -> bool:
        return self.is_won() or self.is_lost() or self.ticks >= self.max_ticks

    def progress(self) -> dict:
        return {"best_tile": self.best, "target": WIN_TILE, "score": self.score, "moves": self.moves,
                "empty": sum(row.count(0) for row in self.board), "won": self.is_won()}

    def step(self, action) -> None:
        if self.done:
            return
        self.ticks += 1
        if action not in self.keys:
            return
        moved, gain = move_with_gain(self.board, action)
        if moved == self.board:
            return  # a move that changes nothing adds no tile (the web game's rule)
        self.board = moved
        self.score += gain
        self.moves += 1
        self._spawn()

    def step_realtime(self, action=None, dt: float = 0.05) -> None:
        self.step(action)

    def render(self):
        from PIL import Image

        image = Image.new("RGB", self.pixel_size, PALETTE[0])
        cell = self.pixel_size[0] // SIZE
        for y in range(SIZE):
            for x in range(SIZE):
                colour = PALETTE.get(self.board[y][x], PALETTE[2048])
                for dy in range(2, cell - 2):
                    for dx in range(2, cell - 2):
                        image.putpixel((x * cell + dx, y * cell + dy), colour)
        return image


class OsgGymEnv:
    """A PlayfellowGym-shaped host for the headless board: dense progress reward, exactly 1.0 on a win, never above 1.0."""

    def __init__(self, seed: int = 0):
        self.key = "osg_2048"
        self.seed = int(seed)
        self.game: Osg2048Game | None = None
        self._p0: dict | None = None
        self._last = 0.0
        self.total = 0.0
        self.steps = 0
        self.action_space = list(Osg2048Game.keys)

    def reset(self, seed: int | None = None):
        import numpy as np

        if seed is not None:
            self.seed = int(seed)
        self.game = Osg2048Game(self.seed)
        self._p0 = dict(self.game.progress())
        self._last, self.total, self.steps = 0.0, 0.0, 0
        self.action_space = list(self.game.keys)
        return np.asarray(self.game.render().convert("RGB")), self._info()

    def step(self, action):
        import numpy as np

        if self.game is None:
            raise RuntimeError("call reset() first")
        self.game.step(action)
        self.steps += 1
        value = progress(self._p0, self.game.progress()) if self._p0 else 0.0
        value = min(1.0, max(0.0, float(value)))
        reward = value - self._last
        terminated = bool(self.game.done)
        if terminated and self.game.is_won() and value < 1.0:
            reward += 1.0 - value
            value = 1.0
        self._last = value
        self.total += reward
        truncated = bool(self.game.ticks >= self.game.max_ticks)
        return np.asarray(self.game.render().convert("RGB")), reward, terminated, truncated, self._info()

    def _info(self) -> dict:
        game = self.game
        return {"progress": self._last, "won": bool(game.is_won()), "lost": bool(game.is_lost()),
                "ticks": int(game.ticks), "steps": self.steps, "return": self.total}

    def card(self):
        from playfellow_coop.gym.env import Card

        game = self.game
        return Card(self.key, self.seed, bool(game.is_won()), bool(game.is_lost()), self._last, self.total,
                    self.steps, int(game.ticks))


def make_env(seed: int) -> OsgGymEnv:
    return OsgGymEnv(seed)
