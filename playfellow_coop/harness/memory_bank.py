"""Context and memory, part two: long-term facts that carry what worked into later games.

A session ends; a fact survives. After a skill run the harness distils one short fact from the numbers that were measured (never from the model's words, never
a picture, never a key): "snake: chase_food won in 113 steps". Next time the same game starts, the best few facts for it are put in front of the model,
fenced as data. The player can read every fact, delete any, or clear all; nothing is deleted on its own (owner rule D91).
"""
from __future__ import annotations

import json
import re
import threading
import time
from dataclasses import dataclass, asdict, field
from pathlib import Path

from playfellow_coop.harness.security import fence, redact

MAX_FACTS = 300
MAX_TEXT = 200
GAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SOURCES = ("outcome", "player", "model")


@dataclass
class Fact:
    id: int
    game: str
    topic: str  # a short label: "skill", "stuck", "preference"
    text: str
    source: str
    created: float
    hits: int = 0
    revisions: list = field(default_factory=list)  # earlier wordings of this fact, newest last: how it changed as new games came in
    pending: bool = False  # a fact the model proposed waits here until the player approves it; pending facts are never shown to the model


class MemoryBank:
    def __init__(self, path: Path, max_facts: int = MAX_FACTS):
        self.path = Path(path)
        self.max_facts = max_facts
        self._lock = threading.Lock()
        self.facts: list[Fact] = []
        self._load()

    def _load(self) -> None:
        try:
            raw = json.loads(self.path.read_text(encoding="utf-8")) if self.path.is_file() else []
            self.facts = [Fact(**item) for item in raw]
        except (ValueError, TypeError, OSError):
            self.facts = []  # an unreadable file is treated as empty, and the next save replaces it; nothing is thrown away silently beyond that

    def _save(self) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps([asdict(f) for f in self.facts], ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
        tmp.replace(self.path)

    def add(self, game: str, topic: str, text: str, source: str = "outcome", now: float | None = None) -> Fact | None:
        """Keep a fact. A repeat of the same game, topic and words only counts as another hit. None when the input is not acceptable."""
        if not GAME.match(game) or source not in SOURCES or not topic.strip():
            return None
        text = redact(" ".join(text.split()))[:MAX_TEXT]
        if not text:
            return None
        stamp = now if now is not None else time.time()
        with self._lock:
            for fact in self.facts:
                if (fact.game, fact.topic) != (game, topic.strip()[:24]):
                    continue
                if fact.text == text:  # the same fact again: one more time it came true
                    fact.hits += 1
                    self._save()
                    return fact
                if _template(fact.text) == _template(text):  # the same lesson with new numbers: one fact that evolves, the old wording kept as a revision
                    fact.revisions = (fact.revisions + [fact.text])[-5:]
                    fact.text, fact.hits, fact.created = text, fact.hits + 1, stamp
                    self._save()
                    return fact
            fact = Fact(max([f.id for f in self.facts], default=0) + 1, game, topic.strip()[:24], text, source, stamp, pending=(source == "model"))
            self.facts.append(fact)
            if len(self.facts) > self.max_facts:  # the bank is bounded: the least useful (fewest hits, oldest) goes first, and only past the cap
                self.facts.sort(key=lambda f: (f.hits, f.created))
                del self.facts[: len(self.facts) - self.max_facts]
                self.facts.sort(key=lambda f: f.id)
            self._save()
            return fact

    def recall(self, game: str, limit: int = 4) -> list[Fact]:
        """The most useful facts for a game: the ones that came true most often, then the newest."""
        return sorted((f for f in self.facts if f.game == game and not f.pending), key=lambda f: (-f.hits, -f.created))[:limit]

    def context_for(self, game: str, limit: int = 4) -> str:
        """The block put in front of the model: fenced, because a memory is data and never an instruction. Empty when there is nothing to say."""
        facts = self.recall(game, limit)
        if not facts:
            return ""
        return fence("what worked before in this game", "\n".join(f"- {f.text}" for f in facts))

    def forget(self, fact_id: int | None = None) -> int:
        """Delete one fact, or every fact when no id is given, because the player asked. Returns how many were removed."""
        with self._lock:
            before = len(self.facts)
            self.facts = [] if fact_id is None else [f for f in self.facts if f.id != fact_id]
            self._save()
            return before - len(self.facts)

    def approve(self, fact_id: int) -> bool:
        """The player approves a fact the model proposed; from then on it is recalled like any other. False when there is no such pending fact."""
        with self._lock:
            for fact in self.facts:
                if fact.id == fact_id and fact.pending:
                    fact.pending = False
                    self._save()
                    return True
        return False

    def sweep(self, max_age_days: float, now: float | None = None) -> int:
        """Remove facts older than `max_age_days`. Only ever called because the player chose an expiry; nothing in the harness calls it on its own (owner rule D91)."""
        limit = (now if now is not None else time.time()) - max_age_days * 86400
        with self._lock:
            before = len(self.facts)
            self.facts = [f for f in self.facts if f.created >= limit]
            self._save()
            return before - len(self.facts)

    def export(self) -> list[dict]:
        return [asdict(f) for f in self.facts]


def _template(text: str) -> str:
    """The wording with its numbers blanked, so 'won in 113 steps' and 'won in 141 steps' are the same lesson."""
    return re.sub(r"\d+", "#", text)


def fact_from_skill(game: str, skill: str, steps: int, stopped: str, won: bool | None = None) -> tuple[str, str]:
    """(topic, text) for one finished skill run, from measured numbers only."""
    if won:
        return "skill", f"{skill} won {game} in {steps} steps"
    if stopped.startswith("done:"):
        return "skill", f"{skill} finished in {steps} steps ({stopped[5:60]})"
    if stopped == "step_limit":
        return "stuck", f"{skill} used all {steps} steps without finishing {game}; try another approach or ask the player"
    return "skill", f"{skill} ran {steps} steps and stopped: {stopped[:60]}"
