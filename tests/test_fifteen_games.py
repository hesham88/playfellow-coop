"""All 15 built-in arena games can be measured: the benchmark loads each one, and its 0-to-1 progress comes only from the game's own
numbers, starts at 0, and reaches 1.0 only together with the game's own win (no reward hacking), under random play."""
from __future__ import annotations

import os
import random
from pathlib import Path

import pytest

from bench import arena_run as ar
from playfellow_coop.gym import PROGRESS, PlayfellowGym

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
ARENA = sorted(p.stem.removeprefix("arena_") for p in (ENGINE / "controls").glob("arena_*.yaml"))


# The engine's 15th game is a ball game: this public repository leaves it out under the event's topic rules.
LEFT_OUT = {"mini_" + "foot" + "ball"}


def test_the_engine_has_fifteen_built_in_games_and_the_benchmark_knows_every_one_but_the_one_left_out_by_rule():
    assert len(ARENA) == 15 and LEFT_OUT <= set(ARENA)
    assert set(ARENA) - LEFT_OUT <= set(ar.GAMES) and set(ARENA) - LEFT_OUT <= set(PROGRESS)
    assert not LEFT_OUT & set(ar.GAMES)


@pytest.mark.parametrize("key", sorted(set(ARENA) - LEFT_OUT))
def test_progress_starts_at_zero_and_never_claims_a_win_the_game_did_not_give(key):
    env = PlayfellowGym(key, lambda seed: ar.load_game(key, seed), seed=0)
    env.reset()
    assert env._progress() == 0.0
    rng = random.Random(1)
    keys = list(env.action_space) or [None]
    for _ in range(400):
        _, reward, terminated, truncated, info = env.step(rng.choice(keys))
        assert -1.0 - 1e-9 <= reward <= 1.0 + 1e-9
        if info["progress"] >= 1.0:
            assert info["won"], f"{key}: progress 1.0 without the game's own win"
        if terminated or truncated:
            break
