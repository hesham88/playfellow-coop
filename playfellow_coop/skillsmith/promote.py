"""When a candidate skill may replace the current one (TORSI and Harness² "Compose", research R2 section 4.1) and how much the search may spend.

The rules, each one a lesson from the papers: a candidate is promoted only if its score on the VALIDATION tasks strictly improves on the current skill; the held-out TEST tasks are never used
to choose (evolving on the evaluation set encodes its shortcuts, and a second round of optimisation can regress: 76.4 to 59.1 percent in the study the research cites); the search has a hard
spend cap (the research repository has none); and a second selection round on the same tasks is refused unless the validation set is new.
"""
from __future__ import annotations

from dataclasses import dataclass, field


class BudgetExceeded(Exception):
    pass


class HeldOutLeak(Exception):
    pass


@dataclass
class Budget:
    max_usd: float
    max_calls: int
    spent_usd: float = 0.0
    calls: int = 0

    def spend(self, usd: float, calls: int = 1) -> None:
        """Record a spend BEFORE the work it pays for is accepted: refuses when it would pass either cap."""
        if self.spent_usd + usd > self.max_usd + 1e-12 or self.calls + calls > self.max_calls:
            raise BudgetExceeded(f"the search budget (${self.max_usd:.2f}, {self.max_calls} calls) would be exceeded")
        self.spent_usd += usd
        self.calls += calls

    @property
    def left_usd(self) -> float:
        return max(0.0, self.max_usd - self.spent_usd)


def assert_disjoint(validation_seeds, test_seeds) -> None:
    """The held-out split is sacred: no seed may appear in both."""
    overlap = set(validation_seeds) & set(test_seeds)
    if overlap:
        raise HeldOutLeak(f"seeds {sorted(overlap)} are in both the validation and the held-out test set")


@dataclass
class Decision:
    promote: bool
    chosen: str | None
    reason: str
    scores: dict[str, float] = field(default_factory=dict)


@dataclass
class Selector:
    """Chooses among candidates by validation score only. `used` remembers validation sets already spent, so the same tasks cannot be mined twice."""
    used: set = field(default_factory=set)

    def choose(self, current: str, scores: dict[str, float], validation_seeds, test_seeds=()) -> Decision:
        """`scores`: validation score per candidate name, including `current`. A candidate must beat the current skill strictly; ties keep the current one."""
        assert_disjoint(validation_seeds, test_seeds)
        key = tuple(sorted(validation_seeds))
        if key in self.used:
            return Decision(False, None, "this validation set was already used to select a skill; use new tasks", dict(scores))
        self.used.add(key)
        if current not in scores:
            raise ValueError("the current skill must be scored on the same validation tasks")
        better = {n: s for n, s in scores.items() if n != current and s > scores[current]}
        if not better:
            return Decision(False, None, "no candidate strictly beats the current skill on validation", dict(scores))
        best = max(better, key=lambda n: (better[n], n))
        return Decision(True, best, f"{best} scored {better[best]:.3f} against {scores[current]:.3f}", dict(scores))
