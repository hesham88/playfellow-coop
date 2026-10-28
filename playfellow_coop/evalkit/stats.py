"""Statistics a benchmark report must carry (research R3 section 4.5, R1 section 3.5): the rliable methodology in plain numpy, Glass's delta, harness lift and budgeted success.

A handful of episodes averaged arithmetically is fragile: one lucky run moves the mean. rliable's answer (Agarwal et al.): normalise each run against random and human play, aggregate with
the interquartile mean (the mean of the middle half), report the optimality gap (how far from human level, lower is better), the probability that one method beats another, and a stratified
bootstrap confidence interval that resamples runs inside each task. Everything here is deterministic given a seed.
"""
from __future__ import annotations

import math
from typing import Callable, Sequence

import numpy as np


def human_normalized(score: float, random_score: float, human_score: float) -> float:
    """(score - random) / (human - random). 0 is random play, 1 is human level; above 1 is better than the human baseline. A baseline with no spread gives 0."""
    spread = human_score - random_score
    return 0.0 if spread == 0 else (score - random_score) / spread


def iqm(values: Sequence[float]) -> float:
    """Interquartile mean: drop the lowest and highest quarter, average the middle half (partial values at the cut are weighted, as in scipy's trimmed mean)."""
    x = np.sort(np.asarray(values, dtype=float))
    n = len(x)
    if n == 0:
        raise ValueError("iqm of nothing")
    cut = 0.25 * n
    whole = int(math.floor(cut))
    frac = cut - whole
    weights = np.ones(n)
    weights[:whole] = 0.0
    weights[n - whole:] = 0.0
    if frac > 0:
        weights[whole] = 1.0 - frac
        weights[n - whole - 1] = 1.0 - frac
    return float((x * weights).sum() / weights.sum())


def optimality_gap(scores: Sequence[float], target: float = 1.0) -> float:
    """The mean shortfall from `target` (human level), counting only shortfalls: mean(max(target - s, 0)). Lower is better; 0 means every run reached the target."""
    return float(np.mean(np.maximum(target - np.asarray(scores, dtype=float), 0.0)))


def probability_of_improvement(x: Sequence[float], y: Sequence[float]) -> float:
    """P(X > Y) with ties counting half: the chance that a random run of method X beats a random run of method Y."""
    a, b = np.asarray(x, dtype=float), np.asarray(y, dtype=float)
    greater = (a[:, None] > b[None, :]).sum()
    equal = (a[:, None] == b[None, :]).sum()
    return float((greater + 0.5 * equal) / (len(a) * len(b)))


def stratified_bootstrap(scores_by_task: dict[str, Sequence[float]], statistic: Callable[[np.ndarray], float] = iqm, reps: int = 2000, confidence: float = 0.95,
                         seed: int = 0) -> tuple[float, float, float]:
    """(point estimate, lower, upper). Each replicate resamples the runs WITHIN every task (so each task keeps its weight), pools them, and applies `statistic`."""
    rng = np.random.default_rng(seed)
    tasks = {k: np.asarray(v, dtype=float) for k, v in scores_by_task.items() if len(v)}
    if not tasks:
        raise ValueError("no runs to bootstrap")
    point = float(statistic(np.concatenate(list(tasks.values()))))
    draws = np.empty(reps)
    for i in range(reps):
        pooled = np.concatenate([v[rng.integers(0, len(v), len(v))] for v in tasks.values()])
        draws[i] = statistic(pooled)
    low, high = np.quantile(draws, [(1 - confidence) / 2, 1 - (1 - confidence) / 2])
    return point, float(low), float(high)


def glass_delta(scores: Sequence[float], control: Sequence[float]) -> float:
    """Glass's delta: (mean(scores) - mean(control)) / std(control). The control is random play, so the effect is measured in units of how much random play varies. When the control
    never varies (std 0) the result is +inf if the system is better, -inf if worse, 0 if equal."""
    a, c = np.asarray(scores, dtype=float), np.asarray(control, dtype=float)
    spread = float(c.std(ddof=1)) if len(c) > 1 else 0.0
    diff = float(a.mean() - c.mean())
    if spread == 0.0:
        return 0.0 if diff == 0 else math.copysign(math.inf, diff)
    return diff / spread


def harness_lift(system: float, raw: float) -> float:
    """What the harness adds over the same model with no help: system - raw."""
    return system - raw


def budgeted_success_rate(episodes: Sequence[dict], budget_usd: float) -> float:
    """Share of episodes that won AND stayed inside the dollar budget (each episode: {"won": bool, "cost_usd": float}). A win that overspent is not a success."""
    if not episodes:
        return 0.0
    return sum(1 for e in episodes if e.get("won") and float(e.get("cost_usd", 0.0)) <= budget_usd) / len(episodes)


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a win rate."""
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)
