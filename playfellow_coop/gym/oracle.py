"""The oracle: the best local controller we have for each game, driven through the gym with pictures only, and the checks that a gym's reward is complete.

An oracle is not a cheat: it reads the same pixels a player does (`playfellow_coop.skills`), and its job is to show that the environment CAN be won and that the reward then says so. The
checks (`check_game`) are what the owner asked for before any paid trial: on every seed the oracle wins, the return is exactly 1.0, the reward never exceeds the bounds, progress reaches 1.0
only with the game's own win, and a policy that does nothing earns nothing.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from playfellow_coop.gym.env import Card, PlayfellowGym
from playfellow_coop.skills.base import Done
from playfellow_coop.skills.registry import SKILLS


@dataclass
class Report:
    game: str
    seeds: int
    wins: int = 0
    returns: list[float] = field(default_factory=list)
    problems: list[str] = field(default_factory=list)
    cards: list[Card] = field(default_factory=list)

    @property
    def complete(self) -> bool:
        return not self.problems and self.wins == self.seeds


def run_oracle(env: PlayfellowGym, skill, max_steps: int | None = None) -> Card:
    """Play one episode with `skill` from pixels, for as long as the game itself allows (its own tick limit). Returns the environment's own card."""
    obs, _ = env.reset()
    skill.reset()
    rewards: list[float] = []
    for _ in range(max_steps or int(env.game.max_ticks) + 1):
        try:
            key = skill.next_key(obs)
        except Done:
            break
        obs, reward, terminated, truncated, info = env.step(key)
        rewards.append(reward)
        if terminated or truncated:
            break
    env._rewards = rewards  # kept for the checks below
    return env.card()


def check_game(key: str, make_game: Callable[[int], object], seeds=range(3), look=None, max_steps: int | None = None, clock: str = "turn") -> Report:
    report = Report(key, len(list(seeds)))
    for seed in seeds:
        env = PlayfellowGym(key, make_game, seed=seed, clock=clock)
        skill = SKILLS[key](look) if look is not None else SKILLS[key]()
        card = run_oracle(env, skill, max_steps)
        rewards = env._rewards
        report.cards.append(card)
        report.returns.append(card.total_reward)
        if card.won:
            report.wins += 1
            if abs(card.total_reward - 1.0) > 1e-9:
                report.problems.append(f"seed {seed}: won but the return is {card.total_reward:.6f}, not 1.0")
        else:
            report.problems.append(f"seed {seed}: the oracle did not win (progress {card.progress:.2f}, lost={card.lost}, steps={card.steps})")
        if card.total_reward > 1.0 + 1e-9:
            report.problems.append(f"seed {seed}: the return {card.total_reward:.6f} is above 1.0")
        if card.progress >= 1.0 and not card.won:
            report.problems.append(f"seed {seed}: progress reached 1.0 without the game's own win (reward hacking)")
        if any(r < -1.0 - 1e-9 or r > 1.0 + 1e-9 for r in rewards):
            report.problems.append(f"seed {seed}: a single reward is outside -1..1")
        idle = PlayfellowGym(key, make_game, seed=seed, clock=clock)
        idle.reset()
        for _ in range(60):
            _, reward, terminated, truncated, _ = idle.step(None)
            if terminated or truncated:
                break
        if idle.card().won:
            report.problems.append(f"seed {seed}: doing nothing wins the game")
    return report
