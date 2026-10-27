"""Per-stage timing for one turn, and the summary the speed bench writes.

Only stages that really exist are measured: capture, shrink, mark, encode, request, parse_and_check, key_down, skill (a whole skill run: many steps from one decision). A stage that was never
timed is reported as "not measured", never as zero. Nothing here is typed in: every number comes from time.perf_counter()."""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from typing import Callable, Iterator

STAGES = ("capture", "shrink", "mark", "encode", "request", "parse_and_check", "key_down", "skill")
NOT_MEASURED = "not measured"


class StageTimer:
    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self._clock = clock
        self.turns: list[dict[str, float]] = []
        self._current: dict[str, float] | None = None

    def now(self) -> float:
        return self._clock()

    def begin_turn(self) -> None:
        self._current = {}

    def end_turn(self) -> dict[str, float]:
        done, self._current = self._current or {}, None
        self.turns.append(done)
        return done

    @contextmanager
    def stage(self, name: str) -> Iterator[None]:
        if name not in STAGES:
            raise ValueError(f"unknown stage {name!r}")
        start = self._clock()
        try:
            yield
        finally:
            self.add(name, self._clock() - start)

    def add(self, name: str, seconds: float) -> None:
        """Add a duration measured elsewhere (for example inside the brain). Two additions to one stage in a turn are summed."""
        if name not in STAGES:
            raise ValueError(f"unknown stage {name!r}")
        if self._current is not None:
            self._current[name] = self._current.get(name, 0.0) + seconds

    def summary(self) -> dict[str, dict | str]:
        """p50, p90 and p95 (nearest rank) of every stage that has at least one sample; the others say so."""
        out: dict[str, dict | str] = {}
        for name in STAGES:
            samples = sorted(t[name] for t in self.turns if name in t)
            out[name] = ({"n": len(samples), "p50": _rank(samples, 0.50), "p90": _rank(samples, 0.90), "p95": _rank(samples, 0.95)}
                         if samples else NOT_MEASURED)
        return out


def _rank(sorted_samples: list[float], fraction: float) -> float:
    return sorted_samples[max(0, math.ceil(fraction * len(sorted_samples)) - 1)]
