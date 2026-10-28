"""LSIAP: Level, Speed, Intelligence, Accuracy, Overall performance (research R3 section 4), as numbers a report can carry.

A single success rate hides why an agent failed. These measures separate a wrong plan (Intelligence) from a mis-click (Accuracy) from a stall (Speed) from not getting deep enough (Level).
The formulas follow the sources named in the research (Crafter's log-space geometric mean, A2Z dependency weights, the VideoGameBench real-time gap, SmartPlay's capability scores, Glicko-2).
"""
from __future__ import annotations

import math
from typing import Sequence

import numpy as np


# ---- Level --------------------------------------------------------------------------------------------------------------------------
def level_progression(unlock_rates: Sequence[float]) -> float:
    """Crafter's score: the geometric mean of milestone success rates in log space, exp(mean(ln(1 + s_i))) - 1, with s_i in percent (0..100). It is pulled down by ANY milestone that is
    never reached, so farming the shallow ones does not hide missing depth."""
    if not unlock_rates:
        raise ValueError("no milestones")
    return float(math.exp(np.mean([math.log(1.0 + float(s)) for s in unlock_rates])) - 1.0)


def downstream_counts(depends_on: dict[str, Sequence[str]]) -> dict[str, int]:
    """For each rule, how many other rules (directly or through others) depend on it. `depends_on[rule]` lists the rules it needs."""
    needs = {k: set(v) for k, v in depends_on.items()}
    counts = {k: 0 for k in needs}
    for rule in needs:
        stack, seen = list(needs[rule]), set()
        while stack:
            dep = stack.pop()
            if dep in seen:
                continue
            seen.add(dep)
            counts[dep] = counts.get(dep, 0) + 1
            stack.extend(needs.get(dep, ()))
    return counts


def dependency_weighted_score(completeness: dict[str, float], depends_on: dict[str, Sequence[str]], alpha: float = 1.0, invariant_pass_rate: float = 1.0) -> float:
    """A2Z-style: a milestone's weight is 1 + alpha * (downstream rules / the largest downstream count), so a foundation that breaks everything above it counts up to (1 + alpha) times a
    leaf. The weighted mean completeness is multiplied by the invariant-preservation pass rate, which punishes rule violations."""
    counts = downstream_counts(depends_on)
    top = max(counts.values()) if counts and max(counts.values()) > 0 else 1
    total = weight_sum = 0.0
    for rule, done in completeness.items():
        w = 1.0 + alpha * counts.get(rule, 0) / top
        total += w * float(done)
        weight_sum += w
    return (total / weight_sum if weight_sum else 0.0) * invariant_pass_rate


# ---- Speed --------------------------------------------------------------------------------------------------------------------------
def real_time_gap(lite_score: float, full_score: float) -> float:
    """The VideoGameBench diagnostic: how much of the paused (Lite) score is lost on the live (Full) clock, (lite - full) / lite. 0 when Lite scored nothing."""
    return 0.0 if lite_score <= 0 else (lite_score - full_score) / lite_score


def budget_overruns(latencies_ms: Sequence[float], budget_ms: float) -> float:
    """The share of control cycles that took longer than their budget (200 ms for the 5 Hz loop, 33.3 ms per 30 Hz chunk, 16.7 ms for the 60 Hz reflex)."""
    return 0.0 if not latencies_ms else sum(1 for v in latencies_ms if v > budget_ms) / len(latencies_ms)


def relative_human_action_efficiency(agent_actions: int, human_actions: int) -> float:
    """RHAE: how many actions the agent needed relative to a human to finish the level (1.0 = as efficient; above 1 uses more actions, below uses fewer)."""
    return float("inf") if human_actions <= 0 else agent_actions / human_actions


# ---- Intelligence -------------------------------------------------------------------------------------------------------------------
def capability_scores(game_scores: dict[str, float], challenge: dict[str, dict[str, float]]) -> dict[str, float]:
    """SmartPlay: for each capability c, the degree-weighted average of the human-normalised score over the games, sum_g(deg[g][c] * score[g]) / sum_g(deg[g][c]). `challenge[game][capability]`
    is how much that game exercises that capability."""
    capabilities = {c for degs in challenge.values() for c in degs}
    out = {}
    for c in sorted(capabilities):
        weights = [(challenge[g].get(c, 0.0), game_scores[g]) for g in game_scores if g in challenge and challenge[g].get(c, 0.0) > 0]
        total = sum(w for w, _ in weights)
        out[c] = sum(w * s for w, s in weights) / total if total else 0.0
    return out


def subproblem_f1(predicted: set, actual: set) -> float:
    """F1 of the agent's answers to an intermediate strategic question (which enemies are threats, what the ally will do) against the truth."""
    if not predicted and not actual:
        return 1.0
    hit = len(predicted & actual)
    if hit == 0:
        return 0.0
    precision, recall = hit / len(predicted), hit / len(actual)
    return 2 * precision * recall / (precision + recall)


def glicko2_update(rating: float, rd: float, volatility: float, results: Sequence[tuple[float, float, float]], tau: float = 0.5) -> tuple[float, float, float]:
    """One Glicko-2 rating period (Glickman). `results`: (opponent rating, opponent rd, score) with score 1 win, 0.5 draw, 0 loss. Returns (rating, rd, volatility)."""
    scale = 173.7178
    mu, phi = (rating - 1500.0) / scale, rd / scale
    if not results:
        return rating, min(350.0, math.sqrt(phi * phi + volatility * volatility) * scale), volatility
    g = lambda p: 1.0 / math.sqrt(1.0 + 3.0 * p * p / math.pi ** 2)  # noqa: E731
    expected = lambda m, mj, pj: 1.0 / (1.0 + math.exp(-g(pj) * (m - mj)))  # noqa: E731
    mus = [((r - 1500.0) / scale, d / scale, s) for r, d, s in results]
    v = 1.0 / sum(g(pj) ** 2 * expected(mu, mj, pj) * (1 - expected(mu, mj, pj)) for mj, pj, _ in mus)
    delta = v * sum(g(pj) * (s - expected(mu, mj, pj)) for mj, pj, s in mus)
    a = math.log(volatility ** 2)

    def f(x):
        ex = math.exp(x)
        return ex * (delta ** 2 - phi ** 2 - v - ex) / (2 * (phi ** 2 + v + ex) ** 2) - (x - a) / tau ** 2

    big_a = a
    if delta ** 2 > phi ** 2 + v:
        big_b = math.log(delta ** 2 - phi ** 2 - v)
    else:
        k = 1
        while f(a - k * tau) < 0:
            k += 1
        big_b = a - k * tau
    fa, fb = f(big_a), f(big_b)
    for _ in range(100):
        if abs(big_b - big_a) <= 1e-6:
            break
        c = big_a + (big_a - big_b) * fa / (fb - fa)
        fc = f(c)
        if fc * fb <= 0:
            big_a, fa = big_b, fb
        else:
            fa /= 2.0
        big_b, fb = c, fc
    new_vol = math.exp(big_a / 2.0)
    phi_star = math.sqrt(phi ** 2 + new_vol ** 2)
    phi_new = 1.0 / math.sqrt(1.0 / phi_star ** 2 + 1.0 / v)
    mu_new = mu + phi_new ** 2 * sum(g(pj) * (s - expected(mu, mj, pj)) for mj, pj, s in mus)
    return mu_new * scale + 1500.0, phi_new * scale, new_vol


# ---- Accuracy -----------------------------------------------------------------------------------------------------------------------
def action_compliance(emitted: Sequence[str], allowed: set[str]) -> float:
    """The share of emitted actions that are on the game's controls: 1.0 means no Action Space Violation (no habit keys from other games)."""
    return 1.0 if not emitted else sum(1 for a in emitted if a in allowed) / len(emitted)


def iou(a: tuple[float, float, float, float], b: tuple[float, float, float, float]) -> float:
    """Intersection over union of two boxes (left, top, right, bottom): the grounding accuracy of a located element."""
    left, top = max(a[0], b[0]), max(a[1], b[1])
    right, bottom = min(a[2], b[2]), min(a[3], b[3])
    inter = max(0.0, right - left) * max(0.0, bottom - top)
    union = (a[2] - a[0]) * (a[3] - a[1]) + (b[2] - b[0]) * (b[3] - b[1]) - inter
    return 0.0 if union <= 0 else inter / union


def seam_smoothness(chunks: Sequence[Sequence[Sequence[float]]]) -> float:
    """The largest jump in any action component between the last step of one chunk and the first of the next: near zero means the chunks join smoothly (no spike at the seam)."""
    worst = 0.0
    for before, after in zip(chunks, chunks[1:]):
        if before and after:
            worst = max(worst, max(abs(x - y) for x, y in zip(before[-1], after[0])))
    return worst
