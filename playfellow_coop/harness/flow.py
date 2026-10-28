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
