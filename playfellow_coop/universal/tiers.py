"""Three loops, one router: who decides right now (research R1 sections 1.2 and 2.3, R4 section 8.1, SPIKE's event-triggered dual controller).

  REFLEX     the local skill, about 60 times a second, no model
  TACTICAL   a small fast model, about 5 times a second, picking tactics and emitting chunks
  STRATEGIC  the big model, event-triggered (about once every few seconds at most), diagnosing, replanning, writing new skills

`Router.observe` takes a few signals computed locally every tick and answers which loop should act. Stable play stays on the reflex loop; novelty, stalled progress, repeated actions or a skill
fault wake the tactical loop; the tactical loop failing again and again wakes the strategic one. Every escalation has a cooldown so the expensive loops are not woken by every flicker, and the
router de-escalates only after a calm stretch. `ReactiveOverride` is the safety valve for skipped frames: when a threat gets close it flushes the skip queue at once.
"""
from __future__ import annotations

from dataclasses import dataclass, field

REFLEX, TACTICAL, STRATEGIC = "reflex", "tactical", "strategic"


@dataclass
class Signals:
    novelty: float = 0.0  # 0..1 appearance change against the running average of play (the cut / new screen signal)
    progress_delta: float = 0.0  # change in the goal measure since the last tick (0 = stalled)
    repeat_count: int = 0  # the same action on the same state this many times in a row
    skill_fault: bool = False  # the local skill raised, timed out or said it cannot see
    tactical_failed: bool = False  # the last tactical decision did not help (no progress after it)
    ended: bool = False  # the end-of-game detector fired


@dataclass
class Decision:
    tier: str
    reasons: list[str] = field(default_factory=list)
    changed: bool = False


class Router:
    def __init__(self, novelty_level: float = 0.35, stall_ticks: int = 90, repeat_limit: int = 12, calm_ticks: int = 120, tactical_cooldown: int = 12, strategic_cooldown: int = 150,
                 failures_before_strategic: int = 3):
        self.novelty_level, self.stall_ticks, self.repeat_limit, self.calm_ticks = novelty_level, stall_ticks, repeat_limit, calm_ticks
        self.tactical_cooldown, self.strategic_cooldown, self.failures_needed = tactical_cooldown, strategic_cooldown, failures_before_strategic
        self.tier = REFLEX
        self._stalled = 0
        self._calm = 0
        self._failures = 0
        self._since_tactical = tactical_cooldown
        self._since_strategic = strategic_cooldown
        self.counts = {REFLEX: 0, TACTICAL: 0, STRATEGIC: 0}

    def observe(self, s: Signals) -> Decision:
        self._since_tactical += 1
        self._since_strategic += 1
        self._stalled = 0 if s.progress_delta > 0 else self._stalled + 1
        reasons: list[str] = []
        if s.novelty >= self.novelty_level:
            reasons.append("novelty")
        if self._stalled >= self.stall_ticks:
            reasons.append("stalled")
        if s.repeat_count >= self.repeat_limit:
            reasons.append("repeating")
        if s.skill_fault:
            reasons.append("skill_fault")
        if s.ended:
            reasons.append("ended")
        if s.tactical_failed:
            self._failures += 1
        elif s.progress_delta > 0:
            self._failures = 0
        want = REFLEX
        if reasons and self._since_tactical >= self.tactical_cooldown:
            want = TACTICAL
        if (s.ended or self._failures >= self.failures_needed) and self._since_strategic >= self.strategic_cooldown:
            want = STRATEGIC
        if want == REFLEX and self.tier != REFLEX:
            self._calm = self._calm + 1 if not reasons else 0
            if self._calm < self.calm_ticks:
                want = self.tier  # stay awake until play has been calm for a while
            else:
                self._calm = 0
        elif want != REFLEX:
            self._calm = 0
        if want == TACTICAL:
            self._since_tactical = 0
        if want == STRATEGIC:
            self._since_strategic = 0
            self._since_tactical = 0
            self._failures = 0
        changed = want != self.tier
        self.tier = want
        self.counts[want] += 1
        return Decision(want, reasons, changed)

    def share(self) -> dict[str, float]:
        total = sum(self.counts.values()) or 1
        return {k: v / total for k, v in self.counts.items()}


class ReactiveOverride:
    """Flushes a queue of skipped frames or planned chunks when something dangerous comes close, so a long skip never blinds the agent."""

    def __init__(self, danger_distance: float = 0.12, flow_spike: float = 0.5):
        self.danger_distance, self.flow_spike = danger_distance, flow_spike

    def should_flush(self, nearest_threat: float | None, flow_level: float = 0.0) -> bool:
        """`nearest_threat`: distance to the closest enemy or projectile in 0..1 screen units (None when none is tracked); `flow_level`: 0..1 motion near the avatar."""
        if nearest_threat is not None and nearest_threat <= self.danger_distance:
            return True
        return flow_level >= self.flow_spike
