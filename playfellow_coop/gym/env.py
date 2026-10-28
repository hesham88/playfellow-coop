"""A Gymnasium-style environment over any arena game (the plain pack or the revamped glass games): pixels in, keys out, a dense and COMPLETE reward.

The engine's games already speak `reset(seed) -> obs` and `step(action) -> (obs, reward, terminated, truncated, info)`. This wrapper changes only the reward and adds the checks the
research asks of a gym (R3 section 4, R1 section 3.5):

  * the reward is the change in a 0..1 progress score (how far the game got, from its own `progress()` numbers, never how to win), so the return of an episode is the final progress;
  * the reward is COMPLETE: when the game is won the return is exactly 1.0 (a completion bonus makes up any rounding), and it is never more than 1.0;
  * it cannot be hacked: progress reaches 1.0 only together with the game's own win flag, and a win is only ever the game's own `is_won()`;
  * `clock="turn"` advances the world one tick per action (a paused clock); `clock="real"` advances game time by `dt` seconds per action (the world does not wait).

No attribute of the game's inner state is exposed to the policy: `step` returns the picture, the reward and a small info dict.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

import numpy as np

from playfellow_coop.gym.progress import PROGRESS


@dataclass
class Card:
    """What an episode scored, from the environment's own bookkeeping."""
    game: str
    seed: int
    won: bool
    lost: bool
    progress: float
    total_reward: float
    steps: int
    ticks: int


class PlayfellowGym:
    def __init__(self, key: str, make_game: Callable[[int], object], seed: int = 0, clock: str = "turn", dt: float = 0.05, max_steps: int | None = None):
        if key not in PROGRESS:
            raise KeyError(f"no progress score for game {key!r}")
        if clock not in ("turn", "real"):
            raise ValueError("clock is 'turn' or 'real'")
        self.key, self._make, self.seed, self.clock, self.dt, self.max_steps = key, make_game, seed, clock, dt, max_steps
        self.game = None
        self._p0: dict | None = None
        self._last = 0.0
        self.total = 0.0
        self.steps = 0
        self.action_space: list[str] = []

    # ---- the environment API -------------------------------------------------------------------------------------------------------
    def reset(self, seed: int | None = None) -> tuple[np.ndarray, dict]:
        if seed is not None:
            self.seed = seed
        self.game = self._make(self.seed)
        obs = np.asarray(self.game.render().convert("RGB"))
        self._p0 = dict(self.game.progress())
        self._last, self.total, self.steps = 0.0, 0.0, 0
        self.action_space = list(self.game.keys)
        return obs, self._info()

    def step(self, action) -> tuple[np.ndarray, float, bool, bool, dict]:
        if self.game is None:
            raise RuntimeError("call reset() first")
        game = self.game
        if self.clock == "real":
            game.step_realtime(action, self.dt)
        else:
            game.step(action)
        self.steps += 1
        progress = self._progress()
        reward = progress - self._last
        terminated = bool(game.done)
        if terminated and game.is_won() and progress < 1.0:
            reward += 1.0 - progress  # completion bonus: a won game always returns exactly 1.0
            progress = 1.0
        self._last = progress
        self.total += reward
        truncated = bool(game.ticks >= game.max_ticks) or (self.max_steps is not None and self.steps >= self.max_steps)
        obs = np.asarray(game.render().convert("RGB"))
        return obs, reward, terminated, truncated, self._info()

    def _progress(self) -> float:
        value = float(PROGRESS[self.key](self._p0, self.game.progress()))
        return min(1.0, max(0.0, value))

    def _info(self) -> dict:
        game = self.game
        return {"progress": self._last, "won": bool(game.is_won()), "lost": bool(game.is_lost()), "ticks": int(game.ticks), "steps": self.steps, "return": self.total}

    def card(self) -> Card:
        game = self.game
        return Card(self.key, self.seed, bool(game.is_won()), bool(game.is_lost()), self._last, self.total, self.steps, int(game.ticks))
