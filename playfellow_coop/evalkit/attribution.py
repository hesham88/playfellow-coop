"""Who did the playing? The honest attribution protocol (research R1 section 3.5, R2 section 6).

Reported wins mix the model's ability with the help scaffolded around it. Every evaluation therefore carries:

  * Action Origin Share: for every input tick, who produced it: a human-written local skill, a model-written local skill, a direct model chunk, or the fallback (neutral) action;
  * a label that follows from the shares: any human-written help makes the row [Assisted: Human Local Skill]; model-written help with no human help is
    [Autonomous: Model-Synthesized Skill]; nothing local at all is [Model Alone];
  * Marginal Model Lift (what the model adds over the local floor that plays with no model) and Autonomous Skill Lift (what model-written skills add over raw model control);
  * the Live-Clock Penalty (how much of the paused-clock score is lost when the world does not wait) and the action-age distribution (P50 and P99 of the time from looking to acting).
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass
from typing import Iterable, Sequence

ORIGINS = ("human_skill", "model_skill", "model_chunk", "fallback")


@dataclass
class Shares:
    human_skill: float = 0.0
    model_skill: float = 0.0
    model_chunk: float = 0.0
    fallback: float = 0.0

    def as_text(self) -> str:
        return f"{self.human_skill:.0%} human skill / {self.model_skill:.0%} model skill / {self.model_chunk:.0%} model chunk / {self.fallback:.0%} fallback"


def origin_share(ticks: Iterable[str]) -> Shares:
    """The share of input ticks by origin. Unknown origins are an error: an untagged tick would hide who was playing."""
    counts = Counter(ticks)
    unknown = set(counts) - set(ORIGINS)
    if unknown:
        raise ValueError(f"unknown action origin(s): {sorted(unknown)}")
    total = sum(counts.values())
    if total == 0:
        return Shares()
    return Shares(**{o: counts.get(o, 0) / total for o in ORIGINS})


def label(shares: Shares) -> str:
    if shares.human_skill > 0:
        return "[Assisted: Human Local Skill]"
    if shares.model_skill > 0:
        return "[Autonomous: Model-Synthesized Skill]"
    return "[Model Alone]"


def marginal_model_lift(system_win_rate: float, local_floor_win_rate: float) -> float:
    """What the model adds over the local controller playing alone (zero model calls)."""
    return system_win_rate - local_floor_win_rate


def autonomous_skill_lift(synthesized_win_rate: float, raw_model_win_rate: float) -> float:
    """What model-written skills add over the same model controlling directly."""
    return synthesized_win_rate - raw_model_win_rate


def live_clock_penalty(paused_score: float, live_score: float) -> float:
    """The share of the paused-clock score lost when the clock runs: (paused - live) / paused. 0 when the paused score is 0."""
    return 0.0 if paused_score <= 0 else (paused_score - live_score) / paused_score


def action_age_ms(observed_at: Sequence[float], applied_at: Sequence[float]) -> tuple[float, float]:
    """(P50, P99) of the time between the observation an action was based on and the moment it was applied, in milliseconds (inputs in seconds)."""
    ages = sorted((b - a) * 1000.0 for a, b in zip(observed_at, applied_at))
    if not ages:
        return 0.0, 0.0
    pick = lambda q: ages[min(len(ages) - 1, int(round(q * (len(ages) - 1))))]  # noqa: E731
    return pick(0.5), pick(0.99)


def row(game: str, win_rate: float, shares: Shares, extra: str = "") -> str:
    """One leaderboard line: the win rate is never shown without who produced the actions."""
    return f"{game}: win rate {win_rate:.0%} {label(shares)} [Action share: {shares.as_text()}]" + (f" {extra}" if extra else "")
