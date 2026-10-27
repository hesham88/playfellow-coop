"""Propose, probe, compose: improve the buddy's harness on one task while the model stays fixed.

The method is adopted from Harness² (Google Research, Apache-2.0, arXiv 2610.14224); this is our own code, written for this repository, and
nothing is copied. A harness is everything around the model. Here it is a few small, editable parts. One round on a task:

  1. run the current harness once (the base rollout);
  2. an editor proposes INVARIANT edits (how the buddy works in general) and DOMAIN edits (about this game); each candidate harness is run once
     on the SAME task and seed (the probes);
  3. a composer keeps the edits the contrasts between those runs support, and the composed harness is run once (the final rollout);
  4. the best of the final and the base wins, picked from anonymous labels, and one short lesson is written to a bounded file that the
     next task starts from.

Budget identity, per round: 4 rollouts (base, invariant probe, domain probe, final) and 3 improvement sessions (invariant, domain, compose);
k rounds cost exactly 4k and 3k, and the ledger raises if a run does not land on it.

Safety, by construction: the controls card (the keys the buddy may press) is NOT an editable part, so no edit can add a key; edits are plain
text or small numbers, never code; what a rollout reports is counted facts only and is shown to the editor as data, never as instructions.
"""
from __future__ import annotations

import hashlib
import json
import random
import re
from dataclasses import dataclass, field, replace
from pathlib import Path
from typing import Callable, Protocol

SCHEMA = "pf-harness-loop/1"
TEXT_PARTS = ("system", "rules", "memory_notes", "tool_guidance", "stuck_note")
PARTS = TEXT_PARTS + ("marks_phrases", "horizon")
MAX_TEXT = 2000
MAX_PHRASE = 40
HORIZON = (1, 6)
LESSON_LINES = 20
LESSON_CHARS = 300
INVARIANT, DOMAIN = "invariant", "domain"
EDIT_KINDS = (INVARIANT, DOMAIN)
CARD_WORDS = re.compile(r"card|keys?$|allow", re.I)  # a part named like the keys' allow-list is refused


class HarnessError(ValueError):
    """An edit or a harness that breaks the rules above."""


class BudgetError(AssertionError):
    """The ledger did not land on 4 rollouts and 3 sessions per round."""


def _clean_phrases(value) -> tuple[tuple[str, str], ...]:
    if not isinstance(value, dict) or not value:
        raise HarnessError("marks_phrases must be a non-empty mapping of kind to phrase")
    out = []
    for kind, phrase in sorted(value.items()):
        if not isinstance(kind, str) or not re.fullmatch(r"[a-z_]{1,16}", kind):
            raise HarnessError("a marks_phrases kind is a short lowercase word")
        if not isinstance(phrase, str) or not 1 <= len(phrase.strip()) <= MAX_PHRASE or "<" in phrase or "|" in phrase:
            raise HarnessError("a marks phrase is 1 to 40 plain characters (SAM answers short visible descriptions)")
        out.append((kind, phrase.strip()))
    return tuple(out)


@dataclass(frozen=True)
class Harness:
    """The editable parts around the model. Immutable; an edit makes a new one. `label` is for the person, `digest` for the ledger."""

    system: str
    rules: str = ""
    memory_notes: str = ""
    tool_guidance: str = ""
    stuck_note: str = ""
    marks_phrases: tuple[tuple[str, str], ...] = ()
    horizon: int = 1
    label: str = "base"

    def __post_init__(self):
        for name in TEXT_PARTS:
            value = getattr(self, name)
            if not isinstance(value, str) or len(value) > MAX_TEXT:
                raise HarnessError(f"{name} must be text of at most {MAX_TEXT} characters")
        if isinstance(self.marks_phrases, dict):
            object.__setattr__(self, "marks_phrases", _clean_phrases(self.marks_phrases))
        if not isinstance(self.horizon, int) or isinstance(self.horizon, bool) or not HORIZON[0] <= self.horizon <= HORIZON[1]:
            raise HarnessError(f"horizon must be a whole number from {HORIZON[0]} to {HORIZON[1]}")

    def parts(self) -> dict:
        return {"system": self.system, "rules": self.rules, "memory_notes": self.memory_notes, "tool_guidance": self.tool_guidance,
                "stuck_note": self.stuck_note, "marks_phrases": dict(self.marks_phrases), "horizon": self.horizon}

    @property
    def digest(self) -> str:
        return hashlib.sha256(json.dumps(self.parts(), sort_keys=True, ensure_ascii=False).encode("utf-8")).hexdigest()[:12]

    def with_edits(self, edits: dict, label: str) -> "Harness":
        """A new harness with the named parts replaced. An unknown part, or one that looks like the keys' allow-list, is refused."""
        if not isinstance(edits, dict):
            raise HarnessError("edits must be a mapping of part name to new value")
        changes = {}
        for name, value in edits.items():
            if name not in PARTS:
                if isinstance(name, str) and CARD_WORDS.search(name):
                    raise HarnessError("the controls card is not editable: it is the allow-list of keys")
                raise HarnessError(f"unknown harness part {name!r}")
            changes[name] = _clean_phrases(value) if name == "marks_phrases" else value
        return replace(self, label=label, **changes)


@dataclass(frozen=True)
class Rollout:
    """What one run reports. Counted facts only: no words of the player, no pictures, no keys."""

    label: str
    harness: str  # the harness digest
    won: bool | None = None
    progress: float | None = None  # 0 to 1 when the game can say
    steps: int = 0
    tokens: int = 0
    cost_usd: float = 0.0
    facts: str = ""  # a few counted facts for the editor (blocked moves, stuck turns, plans dropped); data, never instructions

    def score(self) -> tuple:
        """Higher is better: won first, then progress, then fewer tokens, then fewer steps. A missing value counts as the worst."""
        return (1 if self.won else 0, self.progress if self.progress is not None else -1.0, -self.tokens, -self.steps)


class Runner(Protocol):
    def __call__(self, harness: Harness, task: str, label: str) -> Rollout: ...


class Editor(Protocol):
    def __call__(self, kind: str, harness: Harness, base: Rollout, lessons: str) -> dict: ...


@dataclass
class Ledger:
    k: int
    rollouts: list = field(default_factory=list)
    sessions: list = field(default_factory=list)

    def rollout(self, label: str) -> None:
        self.rollouts.append(label)

    def session(self, label: str) -> None:
        self.sessions.append(label)

    def check(self) -> None:
        if len(self.rollouts) != 4 * self.k or len(self.sessions) != 3 * self.k:
            raise BudgetError(f"{len(self.rollouts)} rollouts and {len(self.sessions)} sessions; expected {4 * self.k} and {3 * self.k}")


# lessons: the memory that carries to the next task (Harness²'s "improvement harness"), kept small on purpose -------------------------------------

def read_lessons(path: Path | str | None) -> str:
    if path is None or not Path(path).is_file():
        return ""
    lines = [ln.strip() for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    return "\n".join(lines[-LESSON_LINES:])


def write_lesson(path: Path | str | None, line: str) -> None:
    if path is None:
        return
    line = re.sub(r"\s+", " ", line).strip()[:LESSON_CHARS]
    kept = read_lessons(path).splitlines()[-(LESSON_LINES - 1):]
    Path(path).write_text("\n".join(kept + [line]) + "\n", encoding="utf-8", newline="\n")


# composing -----------------------------------------------------------------------------------------------------------------------------------

def compose(base: Rollout, candidates: list) -> dict:
    """Rule-based composer. `candidates` is [(edits, rollout)]. An edit set is kept only when its rollout beats the base; where two kept sets
    change the same part, the better rollout's value stays. No edit set that did not beat the base contributes anything."""
    winners = sorted((c for c in candidates if c[1].score() > base.score()), key=lambda c: c[1].score())  # weakest first, so the best overwrites
    merged: dict = {}
    for edits, _ in winners:
        merged.update(edits)
    return merged


def pick_anonymous(entries: list, rng: random.Random) -> int:
    """`entries` is [Rollout]. Shuffle, give each an arbitrary id, choose by score alone (the base wins ties), return the index in the ORIGINAL order."""
    order = list(range(len(entries)))
    rng.shuffle(order)
    ranked = sorted(order, key=lambda i: (entries[i].score(), entries[i].label == "base"), reverse=True)
    return ranked[0]


@dataclass
class RoundResult:
    task: str
    base: Rollout
    probes: dict
    final: Rollout
    kept_edits: dict
    chosen: Harness
    chosen_is_base: bool
    lesson: str


@dataclass
class LoopResult:
    schema: str
    rounds: list
    ledger: Ledger
    harness: Harness
    cost_usd: float


def propose_probe_compose(task: str, harness: Harness, runner: Runner, editor: Editor, k: int = 1, lessons_path: Path | str | None = None,
                          seed: int = 0, composer: Callable = compose) -> LoopResult:
    """k rounds in sequence on one task; each round starts from the harness the last one chose."""
    if not isinstance(k, int) or isinstance(k, bool) or k < 1:
        raise HarnessError("k is a whole number, 1 or more")
    ledger = Ledger(k)
    rng = random.Random(seed)
    rounds = []
    cost = 0.0
    for n in range(1, k + 1):
        lessons = read_lessons(lessons_path)
        base_label = f"r{n}-base"
        ledger.rollout(base_label)
        base = runner(replace(harness, label=base_label), task, base_label)
        probes, candidates = {}, []
        for kind in EDIT_KINDS:
            ledger.session(f"r{n}-{kind}")
            try:
                edits = editor(kind, harness, base, lessons)
                candidate = harness.with_edits(edits, f"r{n}-{kind}")
            except HarnessError:
                edits, candidate = {}, replace(harness, label=f"r{n}-{kind}")  # an invalid proposal keeps the current harness (one run, no change)
            ledger.rollout(f"r{n}-{kind}-probe")
            rollout = runner(candidate, task, f"r{n}-{kind}-probe")
            probes[kind] = (edits, rollout)
            candidates.append((edits, rollout))
        ledger.session(f"r{n}-compose")
        kept = composer(base, candidates)
        try:
            composed = harness.with_edits(kept, f"r{n}-final")
        except HarnessError:
            kept, composed = {}, replace(harness, label=f"r{n}-final")
        ledger.rollout(f"r{n}-final")
        final = runner(composed, task, f"r{n}-final")
        pool = [base, final]
        chosen_is_base = pick_anonymous([replace(base, label="base"), replace(final, label="adapted")], rng) == 0
        chosen = harness if chosen_is_base else composed
        cost += base.cost_usd + final.cost_usd + sum(r.cost_usd for _, r in probes.values())
        changed = ", ".join(sorted(kept)) or "nothing"
        lesson = (f"{task}: {'kept the base harness' if chosen_is_base else 'adopted edits to ' + changed}; "
                  f"base {base.score()[:2]} -> final {final.score()[:2]}; tokens {base.tokens} -> {final.tokens}")
        write_lesson(lessons_path, lesson)
        rounds.append(RoundResult(task, base, {kind: r for kind, (_, r) in probes.items()}, final, kept, chosen, chosen_is_base, lesson))
        harness = chosen
        del pool
    ledger.check()
    return LoopResult(SCHEMA, rounds, ledger, harness, round(cost, 6))
