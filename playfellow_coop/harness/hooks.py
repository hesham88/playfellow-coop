"""Control-loop hooks: rules the loop enforces on itself, not suggestions in a prompt (Harness², research R5).

A rule written in the system prompt is a polite request a busy model can ignore, and every word of it is paid for at every step. A hook is code in the loop. Two kinds cover what the paper's
agents wrote for themselves:

  watchdog         counts steps, wall-clock seconds and dollars; when a limit is reached it forces the episode to wrap up (the agent that reasoned until the time ran out)
  completion gate  refuses a "finished" until every check passes (the agent that must not stop before the spreadsheet has no blank formulas); the checks are code or the game's own state,
                   never the model grading itself (a self-written checker reported a pass three times while the real test failed)

Hooks are declared as plain data (`from_spec`), so they can live in a file the improvement loop edits without that file being executable code. The loop asks `before_step(state)` every step
and `before_finish(state)` when the agent wants to stop.
"""
from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Callable

FORCE_FINISH = "force_finish"
CONTINUE = "continue"


@dataclass
class Watchdog:
    max_steps: int | None = None
    max_seconds: float | None = None
    max_usd: float | None = None
    clock: Callable[[], float] = time.monotonic
    started: float | None = None

    def check(self, state: dict) -> str | None:
        """None while inside the limits; the reason when one is reached."""
        if self.started is None:
            self.started = self.clock()
        if self.max_steps is not None and int(state.get("step", 0)) >= self.max_steps:
            return f"step limit {self.max_steps} reached"
        if self.max_seconds is not None and self.clock() - self.started >= self.max_seconds:
            return f"time limit {self.max_seconds:g} s reached"
        if self.max_usd is not None and float(state.get("spent_usd", 0.0)) >= self.max_usd:
            return f"spend limit ${self.max_usd:g} reached"
        return None


@dataclass
class Check:
    name: str
    test: Callable[[dict], bool]
    why: str = ""


@dataclass
class CompletionGate:
    checks: list[Check] = field(default_factory=list)

    def allow(self, state: dict) -> tuple[bool, list[str]]:
        """(True, []) when every check passes; else (False, the reasons the agent may not stop yet)."""
        failed = []
        for c in self.checks:
            try:
                ok = bool(c.test(state))
            except Exception:  # a check that crashes must refuse, never wave the agent through
                ok = False
            if not ok:
                failed.append(f"{c.name}: {c.why or 'not satisfied'}")
        return (not failed), failed


@dataclass
class ControlHooks:
    watchdog: Watchdog | None = None
    gate: CompletionGate | None = None
    forced: str | None = None
    blocked: int = 0

    def before_step(self, state: dict) -> str:
        """FORCE_FINISH when the watchdog fired (the loop must now wrap up and write its final answer), else CONTINUE."""
        if self.watchdog is not None:
            reason = self.watchdog.check(state)
            if reason:
                self.forced = reason
                return FORCE_FINISH
        return CONTINUE

    def before_finish(self, state: dict) -> tuple[bool, list[str]]:
        """May the agent stop now? A forced finish may always stop (the watchdog already decided); otherwise the completion gate must pass."""
        if self.forced is not None or self.gate is None:
            return True, []
        ok, why = self.gate.allow(state)
        if not ok:
            self.blocked += 1
        return ok, why


# ---- hooks as data ------------------------------------------------------------------------------------------------------------------
STATE_CHECKS = {
    "won": lambda s: bool(s.get("won")),
    "no_blank_fields": lambda s: not s.get("blank_fields"),
    "progress_at_least": None,  # built with a parameter below
}


def from_spec(spec: dict) -> ControlHooks:
    """{"watchdog": {"max_steps": 600, "max_seconds": 120, "max_usd": 0.2}, "gate": [{"check": "won"}, {"check": "progress_at_least", "value": 0.9}]}. Unknown checks are an error, so a
    typo can never turn a gate into an open door."""
    wd = spec.get("watchdog")
    watchdog = Watchdog(wd.get("max_steps"), wd.get("max_seconds"), wd.get("max_usd")) if wd else None
    checks = []
    for item in spec.get("gate", []):
        name = item.get("check")
        if name == "progress_at_least":
            floor = float(item["value"])
            checks.append(Check(name, lambda s, f=floor: float(s.get("progress", 0.0)) >= f, f"progress must reach {floor}"))
        elif name in STATE_CHECKS and STATE_CHECKS[name] is not None:
            checks.append(Check(name, STATE_CHECKS[name], f"{name} is not true yet"))
        else:
            raise ValueError(f"unknown completion check {name!r}")
    return ControlHooks(watchdog, CompletionGate(checks) if checks else None)
