"""Ask a model for a controller, check it, and run the whole pipeline (research R1 section 3.3 steps 1 to 3, R2 section 4.1).

`ask(prompt) -> str` is any callable (a Muse Wonder or Spark call in a real run, a fake in tests). The prompt gives the model the raw structured trace, not a summary (the Meta-Harness
ablation behind the research: raw traces lifted optimisation accuracy from 34 to 50 percent), the observation and action contracts, and the rules the AST gate enforces. A refused answer
is sent back once with the exact reason; a second refusal ends the attempt. The model never sees secrets, and its code never runs in this process.
"""
from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Callable

from playfellow_coop.skillsmith import ast_gate
from playfellow_coop.skillsmith.library import Receipt, SkillLibrary
from playfellow_coop.skillsmith.promote import Budget
from playfellow_coop.skillsmith.verify import Verification, verify

CONTRACT = """You write ONE Python class for a real-time game controller that runs about sixty times a second.

class GeneratedArenaSkill:
    def compute_action(self, obs): ...

`obs` is a dict: "self": [x, y] and "enemies", "items": lists of [x, y, vx, vy], all in 0..1; "hud": dict of numbers; "t": step number; "danger": 0..1; "escape": [dx, dy] the direction
away from the nearest threat; "progress_dir": [dx, dy] when known. Return {"move": [dx, dy] each in -1..1, "buttons": [from jump, attack, use, guard, dash, item, confirm, cancel, fire,
special], "hold_ms": 0..3000}. Keep state on self. Rules (enforced by a checker; breaking one rejects the code): import only math, numpy, typing, dataclasses; no open, eval, exec,
getattr, print, dunder names or attributes; no while loops (use bounded for loops over range); no code at the top level except imports, constants and the class; under 800 syntax nodes."""


@dataclass
class Attempt:
    code: str | None
    reasons: list[str]
    verification: Verification | None = None
    receipt: Receipt | None = None


def extract_code(text: str) -> str | None:
    """The Python in a model's answer: the first fenced block, or the whole text when it already starts like code."""
    match = re.search(r"```(?:python)?\s*\n(.*?)```", text or "", re.S)
    if match:
        return match.group(1).strip("\n") + "\n"
    stripped = (text or "").strip()
    return stripped + "\n" if stripped.startswith(("class ", "import ", "from ")) else None


def build_prompt(game: str, goal: str, trace: list[dict], lessons: list[str], retry_reason: str | None = None, max_trace: int = 60) -> str:
    sample = trace if len(trace) <= max_trace else [trace[i] for i in range(0, len(trace), max(1, len(trace) // max_trace))][:max_trace]
    parts = [CONTRACT, f"Game: {game}. Goal: {goal}.", "Lessons already learned about this game:\n" + ("\n".join(lessons) if lessons else "(none yet)"),
             "Recorded observations (raw, in order):\n" + json.dumps(sample, separators=(",", ":"))]
    if retry_reason:
        parts.append(f"Your previous code was rejected: {retry_reason}\nWrite the class again and fix exactly that.")
    parts.append("Answer with the code only, in one python code block.")
    return "\n\n".join(parts)


class Synthesizer:
    def __init__(self, ask: Callable[[str], str], library: SkillLibrary, budget: Budget, cost_per_call_usd: float = 0.05):
        self.ask, self.library, self.budget, self.cost = ask, library, budget, cost_per_call_usd

    def propose(self, game: str, goal: str, trace: list[dict]) -> Attempt:
        """One proposal, with one retry that carries the checker's reason. Nothing is stored here."""
        reasons: list[str] = []
        retry = None
        for _ in range(2):
            self.budget.spend(self.cost)
            answer = self.ask(build_prompt(game, goal, trace, self.library.experience(game), retry))
            code = extract_code(answer)
            if code is None:
                retry = "the answer contained no code block"
                reasons.append(retry)
                continue
            ok, why = ast_gate.check(code)
            if ok:
                return Attempt(code, reasons)
            retry = why
            reasons.append(why)
        return Attempt(None, reasons)

    def build(self, game: str, goal: str, name: str, trace: list[dict], trial: Callable[[], tuple[float, float]] | None = None, limit_ms: float = 20.0) -> Attempt:
        """Propose, verify with the three gates, and store only a skill that passed everything. The lesson (pass or fail) is written to EXPERIENCE.md with its evidence."""
        attempt = self.propose(game, goal, trace)
        if attempt.code is None:
            self.library.note(game, "the model's code was rejected twice by the static gate", "; ".join(attempt.reasons)[:200])
            return attempt
        attempt.verification = verify(attempt.code, trace, trial, limit_ms=limit_ms)
        if attempt.verification.passed:
            attempt.receipt = self.library.add(game, name, attempt.code, attempt.verification)
            self.library.note(game, f"skill {name} passed all gates", attempt.verification.summary()[:200])
        else:
            self.library.note(game, f"skill {name} failed verification", attempt.verification.summary()[:200])
        return attempt
