"""The three offline gates a model-written skill must pass before it may touch a game (research R1 section 3.3, R2 section 4.1).

A skill is replayed against a recorded trace of observations (what the perception tier saw: the avatar, enemies, items, the HUD, a danger level and the direction to safety):

  Gate A  latency and schema: every step answers inside the limit, nothing raises, every answer is a valid action.
  Gate B  counterfactual threat avoidance and anti-deadlock: where the trace says "danger", the skill's move must point away from it (a positive dot product with the safe direction)
          most of the time, and across the whole trace its choices must not be one single direction (a wall lock).
  Gate C  a short live trial, judged by a callable (a vision model comparing the HUD before and after, or the game's own score in a gym): the score must improve.

`guided_progress` is the teacher-forcing measure from TeleTune: on steps where the recording knows which way made progress, how often does the skill's move agree with it.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Callable

from playfellow_coop.skillsmith.sandbox import NEUTRAL, SandboxedSkill

DANGER_LEVEL = 0.5
SAFE_SHARE = 0.7  # of the dangerous steps, this share of moves must point away


@dataclass
class GateResult:
    name: str
    passed: bool
    detail: str = ""
    value: float | None = None


@dataclass
class Verification:
    passed: bool
    gates: dict[str, GateResult] = field(default_factory=dict)
    progress: float | None = None
    p99_ms: float = 0.0

    def summary(self) -> str:
        return "; ".join(f"{g.name}: {'ok' if g.passed else 'FAILED'} ({g.detail})" for g in self.gates.values())


def _dot(a, b) -> float:
    return float(a[0]) * float(b[0]) + float(a[1]) * float(b[1])


def _entropy(moves: list[tuple[float, float]]) -> float:
    """Shannon entropy (bits) of the skill's moves, each snapped to one of nine directions."""
    if not moves:
        return 0.0
    counts: dict[tuple[int, int], int] = {}
    for dx, dy in moves:
        key = (0 if abs(dx) < 0.3 else (1 if dx > 0 else -1), 0 if abs(dy) < 0.3 else (1 if dy > 0 else -1))
        counts[key] = counts.get(key, 0) + 1
    total = len(moves)
    return -sum((n / total) * math.log2(n / total) for n in counts.values())


def replay(code: str, trace: list[dict], step_timeout_ms: float = 50.0) -> tuple[list[dict], SandboxedSkill]:
    """Step the skill through every observation of the trace inside the sandbox. Returns its actions and the (closed) sandbox with its latencies."""
    actions: list[dict] = []
    skill = SandboxedSkill(code, step_timeout_ms=step_timeout_ms)
    try:
        for obs in trace:
            actions.append(skill.step(obs))
            if skill.faulted:
                break
    finally:
        skill.close()
    return actions, skill


def gate_a(actions: list[dict], skill: SandboxedSkill, trace_len: int, limit_ms: float) -> GateResult:
    if skill.faulted:
        return GateResult("A", False, f"faulted: {skill.fault}")
    if len(actions) < trace_len:
        return GateResult("A", False, f"answered {len(actions)} of {trace_len} steps")
    p99 = skill.percentile_ms(99.0)
    if p99 > limit_ms:
        return GateResult("A", False, f"p99 latency {p99:.1f} ms is over the {limit_ms:.1f} ms limit", p99)
    return GateResult("A", True, f"p99 {p99:.1f} ms over {trace_len} steps, no errors", p99)


def gate_b(actions: list[dict], trace: list[dict]) -> GateResult:
    dangerous = [(a, o) for a, o in zip(actions, trace) if float(o.get("danger", 0.0)) >= DANGER_LEVEL and o.get("escape")]
    if dangerous:
        away = sum(1 for a, o in dangerous if _dot(a["move"], o["escape"]) > 0)
        share = away / len(dangerous)
        if share < SAFE_SHARE:
            return GateResult("B", False, f"moved away from danger on only {share:.0%} of {len(dangerous)} dangerous steps (need {SAFE_SHARE:.0%})", share)
    else:
        share = 1.0
    entropy = _entropy([tuple(a["move"]) for a in actions])
    if entropy <= 0.0 and len(actions) > 20:
        return GateResult("B", False, "one single move for the whole trace (a wall lock)", entropy)
    return GateResult("B", True, f"safe on {share:.0%} of {len(dangerous)} dangerous steps, move entropy {entropy:.2f} bits", share)


def guided_progress(actions: list[dict], trace: list[dict]) -> float | None:
    """Teacher forcing: on steps where the recording says which direction made progress (`progress_dir`), the share where the skill's move agrees. None when the trace has none."""
    pairs = [(a, o["progress_dir"]) for a, o in zip(actions, trace) if o.get("progress_dir")]
    if not pairs:
        return None
    return sum(1 for a, d in pairs if _dot(a["move"], d) > 0) / len(pairs)


def gate_c(trial: Callable[[], tuple[float, float]] | None, min_gain: float) -> GateResult:
    if trial is None:
        return GateResult("C", True, "no live trial requested")
    before, after = trial()
    gain = after - before
    if gain < min_gain:
        return GateResult("C", False, f"the live trial gained {gain:+.3f} (need at least {min_gain:+.3f})", gain)
    return GateResult("C", True, f"the live trial gained {gain:+.3f}", gain)


def verify(code: str, trace: list[dict], trial: Callable[[], tuple[float, float]] | None = None, limit_ms: float = 20.0, min_gain: float = 0.0,
           step_timeout_ms: float = 50.0) -> Verification:
    """Run A, then B (only if A passed), then C (only if both passed). The first failure stops the run: a skill that is late or unsafe never reaches the live game."""
    actions, skill = replay(code, trace, step_timeout_ms)
    result = Verification(False)
    a = gate_a(actions, skill, len(trace), limit_ms)
    result.gates["A"], result.p99_ms = a, skill.percentile_ms(99.0)
    if not a.passed:
        return result
    result.progress = guided_progress(actions, trace)
    b = gate_b(actions, trace)
    result.gates["B"] = b
    if not b.passed:
        return result
    c = gate_c(trial, min_gain)
    result.gates["C"] = c
    result.passed = c.passed
    return result


__all__ = ["GateResult", "Verification", "verify", "replay", "guided_progress", "NEUTRAL"]
