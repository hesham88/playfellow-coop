"""Tools and execution flow, part two: a small graph that does the work, runs independent checks in parallel, feeds failures back, and stops at a retry limit.

    act  ->  [check A, check B, ...] in parallel  ->  all passed?  yes: done
                                                                    no : feedback goes back to `act`; after `retry_limit` retries, stop and ask the player

A node is any function. A check returns True (passed) or a short string (why it failed); a crashing check counts as failed with its error as the reason. The
result says how it ended and keeps the whole path, so a person can read what happened.
"""
from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass, field
from typing import Any, Callable

DONE, HELP = "done", "help"

# The five ways an agent loop ends (cookbook, basic agent loop). Only the first is success.
COMPLETE, ITERATION_CAP, BUDGET, CANNOT, CANCELLED = "complete", "iteration_cap", "budget_spent", "cannot_solve", "cancelled"
DOOM_LOOP = "doom_loop"  # the same call repeated without anything changing


class LoopGuard:
    """Bounds a loop so a stuck run cannot go on without limit. `check` is called once per iteration and returns the reason to stop, or None to go on.

    Doom loop: the same signature (for example the skill chosen, how it stopped, and a hash of the picture) three times in a row means nothing is changing; stop and ask for help.
    """

    def __init__(self, max_iterations: int = 50, max_usd: float | None = None, repeat_limit: int = 3):
        if max_iterations < 1 or repeat_limit < 2:
            raise ValueError("max_iterations is at least 1 and repeat_limit at least 2")
        self.max_iterations, self.max_usd, self.repeat_limit = max_iterations, max_usd, repeat_limit
        self._last, self._same = None, 0

    def check(self, iteration: int, spent_usd: float = 0.0, signature=None, cancelled: bool = False, cannot: bool = False, complete: bool = False) -> str | None:
        if complete:
            return COMPLETE
        if cancelled:
            return CANCELLED
        if cannot:
            return CANNOT
        if self.max_usd is not None and spent_usd >= self.max_usd:
            return BUDGET
        if iteration >= self.max_iterations:
            return ITERATION_CAP
        if signature is not None:
            self._same = self._same + 1 if signature == self._last else 1
            self._last = signature
            if self._same >= self.repeat_limit:
                return DOOM_LOOP
        return None


@dataclass
class FlowResult:
    status: str  # "done" or "help" (the retry limit was reached: ask the player)
    attempts: int
    path: list[dict] = field(default_factory=list)
    reason: str = ""
    context: dict = field(default_factory=dict)  # what the steps left behind (for example the skill's result), for the caller to read


class Flow:
    def __init__(self, act: Callable[[dict], Any], checks: dict[str, Callable[[dict], Any]], retry_limit: int = 1, finished: Callable[[dict], bool] | None = None):
        if retry_limit < 0 or retry_limit > 5:
            raise ValueError("retry_limit is 0 to 5")
        self.act, self.checks, self.retry_limit = act, dict(checks), retry_limit
        self.finished = finished  # True when there is nothing left to do (for example the game is over): that is done, whatever the checks say

    def run(self, context: dict | None = None) -> FlowResult:
        ctx = dict(context or {})
        result = FlowResult(HELP, 0, context=ctx)
        for attempt in range(1, self.retry_limit + 2):
            result.attempts = attempt
            try:
                outcome = self.act(ctx)
            except Exception as error:
                outcome = None
                result.path.append({"attempt": attempt, "act": f"crashed:{type(error).__name__}"})
                ctx["feedback"] = f"the last attempt crashed ({type(error).__name__})"
                continue
            ctx["outcome"] = outcome
            verdicts = self._parallel(ctx)
            result.path.append({"attempt": attempt, "act": "ran", "checks": verdicts})
            if self.finished and self.finished(ctx):
                result.status, result.reason = DONE, "finished"
                return result
            failed = {name: why for name, why in verdicts.items() if why is not True}
            if not failed:
                result.status = DONE
                return result
            ctx["feedback"] = "; ".join(f"{name}: {why}" for name, why in failed.items())
        result.status, result.reason = HELP, ctx.get("feedback", "the retry limit was reached")
        return result

    def _parallel(self, ctx: dict) -> dict:
        def one(item):
            name, check = item
            try:
                verdict = check(ctx)
                return name, True if verdict is True else (str(verdict) or "failed")
            except Exception as error:
                return name, f"crashed:{type(error).__name__}"

        if not self.checks:
            return {}
        with ThreadPoolExecutor(max_workers=len(self.checks)) as pool:
            return dict(pool.map(one, self.checks.items()))
