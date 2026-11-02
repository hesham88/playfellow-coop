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

OBS_FORMAT = """The observation the skill receives (never pixels, never the game's inner state): one dict per step.
- self: [x, y] of the player, each in 0..1 across the screen (0,0 is the top-left corner; a value is a position, not a pixel count).
- "items" and "enemies": lists of [x, y, vx, vy] in the same 0..1 space; vx, vy are how far that thing moved since the step before.
- "hud": a dict of the numbers the screen itself shows; "t": the step number; "visible": whether the player was seen at all.
- "danger": 0..1, how close the nearest threat is; "escape": [dx, dy] pointing away from it, or None when there is no threat."""

# One worked example per game, written for this contract. An example is only ever shown for a DIFFERENT game than the one
# being written (see example_for): it teaches the shape of a good skill, never the answer for the game at hand.
EXAMPLE_SKILLS: dict[str, str] = {
    "snake": """import math

class GeneratedArenaSkill:
    def compute_action(self, obs):
        if obs.get("danger", 0) >= 0.5 and obs.get("escape"):
            ex, ey = obs["escape"]
            return {"move": [ex, ey], "buttons": [], "hold_ms": 0}
        items = obs.get("items") or []
        if items:
            sx, sy = obs["self"]
            dx, dy = items[0][0] - sx, items[0][1] - sy
            n = math.hypot(dx, dy) or 1.0
            return {"move": [dx / n, dy / n], "buttons": [], "hold_ms": 0}
        return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
""",
    "box_push": """class GeneratedArenaSkill:
    def __init__(self):
        self.t = 0

    def compute_action(self, obs):
        self.t += 1
        if obs.get("danger", 0) >= 0.5 and obs.get("escape"):
            ex, ey = obs["escape"]
            return {"move": [ex, ey], "buttons": [], "hold_ms": 0}
        items = obs.get("items") or []
        if items:
            sx, sy = obs["self"]
            step = [0.0, 0.0]
            axis = 0 if abs(items[0][0] - sx) >= abs(items[0][1] - sy) else 1
            step[axis] = 1.0 if items[0][axis] > (sx, sy)[axis] else -1.0
            return {"move": step, "buttons": [], "hold_ms": 0}
        return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
""",
}

PROGRESS_TEXT: dict[str, str] = {
    "snake": "progress is the share of the growth still to gain that has been gained: (length now - length at the start) / (target length - length at the start)",
    "box_push": "progress is the share of the levels finished, counting the boxes already on their goals inside the level being played",
    "slide_2048": "progress is how far the best tile has climbed toward the target tile, on a doubling (log2) scale",
    "lane_dash": "progress is the share of the goal coins collected so far",
    "maze_chase": "progress is 0.7 times the share of the coins collected, plus 0.3 once the key is held; winning is separate and is the game's own flag",
    "key_caves": "progress counts the rooms crossed, plus a half for holding the key and a quarter for the boots, over the number of rooms",
    "brick_breaker": "progress is the share of the levels finished, counting the bricks already cleared inside the level being played",
    "mini_chess": "progress is the share of the moves that had to be survived which have been survived",
}

MAX_PROMPT_TOKENS = 8000  # the fixed ceiling for one skill-writing prompt, counted with estimate_tokens


def estimate_tokens(text: str) -> int:
    """A rough token count (about four characters a token): the prompt limit is enforced on this, never on hope."""
    return len(text) // 4 + 1


def example_for(game: str) -> tuple[str, str]:
    """The worked example to show for `game`: always a skill written for a different game, so it can teach shape, never answers."""
    for name in sorted(EXAMPLE_SKILLS):
        if name != game:
            return name, EXAMPLE_SKILLS[name]
    raise ValueError("no example from a different game is available")


def progress_text(game: str) -> str:
    """What the gym's 0..1 progress score means for this game, in words; "not known" when the gym cannot score the game."""
    from playfellow_coop.gym.progress import PROGRESS

    if game not in PROGRESS:
        return "not known"
    return PROGRESS_TEXT.get(game, "progress is the gym's 0..1 score for this game")


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


def build_prompt(game: str, goal: str, trace: list[dict], lessons: list[str], retry_reason: str | None = None, max_trace: int = 60,
                 keys: tuple[str, ...] = (), progress: str | None = None, example: tuple[str, str] | None = None) -> str:
    if example is not None and example[0] == game:
        raise ValueError(f"the worked example is for {game} itself: an example may only ever come from a different game")
    sample = trace if len(trace) <= max_trace else [trace[i] for i in range(0, len(trace), max(1, len(trace) // max_trace))][:max_trace]
    parts = [CONTRACT, f"Game: {game}. Goal: {goal}."]
    if keys:
        parts.append("Allowed keys for this game (the only keys the skill's actions can ever become): " + ", ".join(keys))
    parts.append(OBS_FORMAT)
    parts.append("Progress measure for this game: " + (progress if progress is not None else progress_text(game)))
    if example is not None:
        parts.append(f"One worked example, a skill written for a different game ({example[0]}). Copy its shape, not its goal:\n```python\n{example[1]}```")
    parts.append("Lessons already learned about this game:\n" + ("\n".join(lessons) if lessons else "(none yet)"))
    parts.append("Recorded observations (raw, in order):\n" + json.dumps(sample, separators=(",", ":")))
    if retry_reason:
        parts.append(f"Your previous code was rejected: {retry_reason}\nWrite the class again and fix exactly that.")
    parts.append("Answer with the code only, in one python code block.")
    prompt = "\n\n".join(parts)
    trace_index = len(parts) - (3 if retry_reason else 2)  # the trace part: only the closing line (and a retry note) follow it
    while estimate_tokens(prompt) > MAX_PROMPT_TOKENS and sample:  # the limit is fixed: the trace, never the contract, gives way
        sample = sample[::2]
        parts[trace_index] = "Recorded observations (raw, in order):\n" + json.dumps(sample, separators=(",", ":"))
        prompt = "\n\n".join(parts)
    return prompt


class Synthesizer:
    def __init__(self, ask: Callable[[str], str], library: SkillLibrary, budget: Budget, cost_per_call_usd: float = 0.05,
                 keys: tuple[str, ...] = (), progress: str | None = None, example: tuple[str, str] | None = None):
        self.ask, self.library, self.budget, self.cost = ask, library, budget, cost_per_call_usd
        self.keys, self.progress, self.example = tuple(keys), progress, example

    def propose(self, game: str, goal: str, trace: list[dict]) -> Attempt:
        """One proposal, with one retry that carries the checker's reason. Nothing is stored here."""
        if self.example is not None and self.example[0] == game:
            raise ValueError(f"the worked example is for {game} itself: an example may only ever come from a different game")
        reasons: list[str] = []
        retry = None
        for _ in range(2):
            self.budget.spend(self.cost)
            answer = self.ask(build_prompt(game, goal, trace, self.library.experience(game), retry,
                                           keys=self.keys, progress=self.progress, example=self.example))
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
