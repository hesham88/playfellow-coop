"""Evaluation: three ways to know the buddy did well, used together.

  1. Code checks for clear rules (did it win, how far, in how many steps, were its plans valid, does what it said match what was measured).
  2. A model judge for qualities code cannot read (is the spoken line clear). It can be wrong, so its scores are kept next to the player's own review.
  3. The player's review for what neither sees (is it fun, is it confusing). Stored as a plain ledger.

Also here: a trajectory score (did the buddy choose the same tools in the same order as a recorded good run), golden-run conformance (replay a recorded run
offline and catch a regression when code or a model changes), and a scripted player for offline user simulation. Nothing in this file calls a model by itself:
the judge is handed a function to call, so a test uses a fake and a paid run is the owner's decision.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field, asdict
from pathlib import Path
from typing import Callable, Iterable

WIN_WORDS = re.compile(r"\b(i won|we won|you win|victory|level complete|all done)\b|فزت|فزنا|انتهينا", re.I)
LOSE_WORDS = re.compile(r"\b(i lost|game over|i crashed)\b|خسرت", re.I)


# ---- 1. code checks (each returns True or a short reason it failed, the shape Flow checks use)
def check_won(won: bool) -> bool | str:
    return True if won else "the game was not won"


def check_progress_at_least(progress: float | None, floor: float) -> bool | str:
    return True if progress is not None and progress >= floor else f"progress {progress} is below {floor}"


def check_steps_within(steps: int, limit: int) -> bool | str:
    return True if steps <= limit else f"{steps} steps is over the limit {limit}"


def check_plans_valid(invalid: int, turns: int) -> bool | str:
    return True if invalid == 0 else f"{invalid} of {turns} plans were not valid"


def check_claim_matches_measure(said: str, won: bool, lost: bool) -> bool | str:
    """Groundedness: a spoken claim must agree with what was measured. Saying 'I won' when the game was not won is a hallucination; so is 'game over' while it runs."""
    if WIN_WORDS.search(said or "") and not won:
        return "said it won, but the game was not won"
    if LOSE_WORDS.search(said or "") and not lost:
        return "said it lost, but the game was not lost"
    return True


# ---- trajectory
def trajectory_score(expected: list[str], actual: list[str]) -> float:
    """1.0 when the same tools were chosen in the same order; otherwise the share of positions that match, divided by the longer list's length."""
    if not expected and not actual:
        return 1.0
    longest = max(len(expected), len(actual))
    return sum(1 for a, b in zip(expected, actual) if a == b) / longest


# ---- 2. model judge
@dataclass
class JudgeResult:
    score: int | None  # 1 to 5, None when the judge's answer could not be read
    why: str = ""
    raw: str = ""


RUBRIC = ("You grade one short line a game buddy said to a player. Score 1 to 5 for clarity: does it say plainly what the buddy is doing or what happened, "
          "in simple words, with no wrong claim? Facts that are true: {facts}. Answer only JSON: {{\"score\": <1-5>, \"why\": \"<one short sentence>\"}}.\n"
          "Line: <<<{line}>>>")


class LlmJudge:
    def __init__(self, ask: Callable[[str], str]):
        self._ask = ask  # a function from the judge prompt to the judge's answer; a test passes a fake, a paid run passes the model
        self.calls = 0

    def clarity(self, line: str, facts: str = "") -> JudgeResult:
        self.calls += 1
        raw = self._ask(RUBRIC.format(line=line.replace("<<<", "").replace(">>>", "")[:300], facts=facts[:300] or "none given"))
        try:
            data = json.loads(raw[raw.find("{"): raw.rfind("}") + 1])
            score = int(data["score"])
            if not 1 <= score <= 5:
                raise ValueError
            return JudgeResult(score, str(data.get("why", ""))[:160], raw[:200])
        except (ValueError, KeyError, TypeError):
            return JudgeResult(None, "the judge's answer could not be read", raw[:200])


# ---- 3. the player's review ledger
@dataclass
class Review:
    item: str
    verdict: str  # "ok", "problem" or "unclear"
    note: str
    at: float = field(default_factory=time.time)


class HumanLedger:
    VERDICTS = ("ok", "problem", "unclear")

    def __init__(self, path: Path):
        self.path = Path(path)
        self.reviews: list[Review] = []
        if self.path.is_file():
            try:
                self.reviews = [Review(**r) for r in json.loads(self.path.read_text(encoding="utf-8"))]
            except (ValueError, TypeError):
                self.reviews = []

    def add(self, item: str, verdict: str, note: str = "") -> Review:
        if verdict not in self.VERDICTS:
            raise ValueError(f"verdict is one of {self.VERDICTS}")
        review = Review(item[:80], verdict, note[:300])
        self.reviews.append(review)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.path.write_text(json.dumps([asdict(r) for r in self.reviews], ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        return review

    def verdict_for(self, item: str) -> str | None:
        found = [r for r in self.reviews if r.item == item]
        return found[-1].verdict if found else None


# ---- golden conformance
@dataclass
class GoldenRun:
    game: str
    seed: int
    tool: str
    won: bool
    steps: int


def save_golden(path: Path, runs: Iterable[GoldenRun]) -> None:
    path = Path(path)
    if path.exists():
        raise FileExistsError(f"{path} exists: a golden file is never overwritten")
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps([asdict(r) for r in runs], indent=1), encoding="utf-8", newline="\n")


def conform(golden: list[GoldenRun], now: list[GoldenRun], step_tolerance: float = 0.25) -> list[str]:
    """Differences between a recorded good run set and a fresh one: a different tool, a lost win, or steps off by more than the tolerance. Empty means it conforms."""
    problems, fresh = [], {(r.game, r.seed): r for r in now}
    for old in golden:
        new = fresh.get((old.game, old.seed))
        if new is None:
            problems.append(f"{old.game} seed {old.seed}: not run")
            continue
        if new.tool != old.tool:
            problems.append(f"{old.game} seed {old.seed}: tool {new.tool} instead of {old.tool}")
        if old.won and not new.won:
            problems.append(f"{old.game} seed {old.seed}: no longer wins")
        if old.steps and abs(new.steps - old.steps) / old.steps > step_tolerance:
            problems.append(f"{old.game} seed {old.seed}: {new.steps} steps instead of about {old.steps}")
    return problems


# ---- user simulation
class ScriptedPlayer:
    """A player who says fixed things at fixed turns, so a session can be driven offline: {turn_number: "what the player says"}."""

    def __init__(self, script: dict[int, str]):
        self.script, self.turn = dict(script), 0

    def next_command(self) -> str | None:
        self.turn += 1
        return self.script.get(self.turn)
