"""The gym: a Gymnasium-style environment with a dense, complete reward, and oracles that win every game from pixels, so the reward is proven reachable before any paid run."""
from __future__ import annotations

import numpy as np
import pytest

from bench import arena_run as ar
from playfellow_coop.gym import PROGRESS, PlayfellowGym, check_game, run_oracle
from playfellow_coop.skills.registry import SKILLS


class FakeGame:
    """A tiny scripted game for the contract tests: progress goes 0, 0.25, 0.5, 0.75 and the win comes with a progress number just under 1 (so the completion bonus matters)."""
    keys = ["up"]
    max_ticks = 50

    def __init__(self, seed=0, win_at=4, final_progress=0.97):
        self.seed, self.ticks, self.win_at, self.final = seed, 0, win_at, final_progress
        self.score = 0

    def render(self):
        from PIL import Image
        return Image.new("RGB", (8, 8), (self.ticks * 10 % 255, 0, 0))

    def progress(self):
        if self.ticks >= self.win_at:
            return {"coins": self.final * 100, "goal_coins": 100}
        return {"coins": self.ticks * 25 * 0.97, "goal_coins": 100}

    def is_won(self):
        return self.ticks >= self.win_at

    def is_lost(self):
        return False

    @property
    def done(self):
        return self.is_won() or self.is_lost()

    def step(self, action):
        if not self.done:
            self.ticks += 1

    def step_realtime(self, action=None, dt=0.05):
        self.step(action)


def test_contract_reset_step_and_the_completion_bonus_make_a_won_game_return_exactly_one():
    env = PlayfellowGym("lane_dash", lambda seed: FakeGame(seed))
    obs, info = env.reset(seed=3)
    assert obs.shape == (8, 8, 3) and obs.dtype == np.uint8 and info["progress"] == 0.0 and env.action_space == ["up"] and env.seed == 3
    total, last = 0.0, None
    for _ in range(10):
        obs, reward, terminated, truncated, info = env.step("up")
        total += reward
        last = (terminated, truncated, info)
        if terminated:
            break
    assert last[0] and not last[1] and last[2]["won"] and last[2]["progress"] == 1.0
    assert total == pytest.approx(1.0) and env.card().total_reward == pytest.approx(1.0) and env.card().won
    with pytest.raises(RuntimeError):
        PlayfellowGym("lane_dash", lambda seed: FakeGame(seed)).step("up")
    with pytest.raises(KeyError):
        PlayfellowGym("no_such_game", lambda seed: FakeGame(seed))
    with pytest.raises(ValueError):
        PlayfellowGym("lane_dash", lambda seed: FakeGame(seed), clock="warp")


def test_the_real_clock_and_the_step_cap_and_truncation():
    env = PlayfellowGym("lane_dash", lambda seed: FakeGame(seed, win_at=100), clock="real", max_steps=3)
    env.reset()
    results = [env.step("up") for _ in range(3)]
    assert results[-1][3] and not results[-1][2]  # truncated by the cap, not terminated


def test_progress_is_a_known_score_for_every_arena_game_and_stays_between_zero_and_one():
    assert set(PROGRESS) >= {"snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"}
    for key in ("snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"):
        env = PlayfellowGym(key, lambda seed, key=key: ar.load_game(key, seed))
        env.reset(seed=0)
        rng = np.random.default_rng(0)
        for _ in range(80):
            _, reward, terminated, truncated, info = env.step(env.action_space[int(rng.integers(len(env.action_space)))])
            assert 0.0 <= info["progress"] <= 1.0 and -1.0 <= reward <= 1.0
            if terminated or truncated:
                break
        assert env.card().total_reward <= 1.0 + 1e-9


@pytest.mark.parametrize("key", ["snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"])
def test_the_oracle_wins_every_seed_from_pixels_and_the_reward_is_complete_and_cannot_be_hacked(key):
    report = check_game(key, lambda seed, key=key: ar.load_game(key, seed), seeds=range(2))
    assert report.complete, report.problems
    assert all(abs(r - 1.0) < 1e-9 for r in report.returns) and report.wins == 2


def test_a_broken_reward_is_reported_not_hidden():
    class Cheat(FakeGame):
        def progress(self):
            return {"coins": 100, "goal_coins": 100}  # progress says 1.0 from the first step while the game is not won

    env = PlayfellowGym("lane_dash", lambda seed: Cheat(seed, win_at=5))
    env.reset()
    _, reward, terminated, _, info = env.step("up")
    assert info["progress"] == 1.0 and not info["won"] and not terminated  # the checker in oracle.py flags exactly this
    report_game = Cheat
    problems = []
    env.reset()
    for _ in range(2):
        env.step("up")
    card = env.card()
    if card.progress >= 1.0 and not card.won:
        problems.append("reward hacking")
    assert problems == ["reward hacking"] and report_game is Cheat
    assert run_oracle is not None and SKILLS
