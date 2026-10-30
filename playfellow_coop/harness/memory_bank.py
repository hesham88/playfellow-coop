"""Context and memory, part two: long-term facts that carry what worked into later games.

A session ends; a fact survives. After a skill run the harness distils one short fact from the numbers that were measured (never from the model's words, never
a picture, never a key): "snake: chase_food won in 113 steps". Next time the same game starts, the best few facts for it are put in front of the model,
fenced as data. The player can read every fact, delete any, or clear all; nothing is deleted on its own (owner rule D91).
When the agent wants to remember something specific it asks in its own words, English or Arabic (`search`, the `memory.search` tool): the facts closest in meaning come back,
found offline by words, word pieces and a small game vocabulary (no model, no network).
"""
from __future__ import annotations

import json
import math
import re
import threading
import time
from collections import Counter
from dataclasses import dataclass, asdict, field
from pathlib import Path

from playfellow_coop.harness.security import fence, redact

MAX_FACTS = 300
MAX_TEXT = 200
GAME = re.compile(r"^[a-z][a-z0-9_]{0,31}$")
SOURCES = ("outcome", "player", "model")

# ---- similarity search (H4-09): offline, by words, word pieces and a small game vocabulary; not a neural embedding ----------------------------------------------------------
WORD = re.compile(r"[^\W_]+")
AR_MARKS = re.compile("[ً-ْٰـ]")  # short vowels, shadda, sukun, dagger alef, tatweel
AR_FOLD = str.maketrans({"أ": "ا", "إ": "ا", "آ": "ا", "ٱ": "ا", "ة": "ه", "ى": "ي", "ؤ": "و", "ئ": "ي"})
AR_ARTICLE = ("وال", "بال", "فال", "كال", "لل", "ال")
STOP = frozenset("a an the to of and or in on at for with is are was were be it this that we you i do did does how what which who why when where before again "
                 "my our your their its by from as not no yes can could should would will just about there here "
                 "في من على الى عن مع هذا هذه ذلك تلك ثم او و ما ماذا كيف لماذا متى اين هل التي الذي قد لا نعم".split())
CONCEPTS = {  # words that name the same idea in a fact and in a question, in both languages ("finish" is NOT a win: a skill can finish without winning)
    "win": "win won wins winning beat beats victory cleared فاز فوز يفوز فزنا فزت ربح ربحنا انتصر نجح",
    "lose": "lose lost loses losing die died dies dead death fail failed خسر خساره يخسر خسرنا مات موت فشل",
    "stuck": "stuck blocked trapped loop looping repeat repeating عالق علق محاصر توقف",
    "step": "step move turn steps moves turns خطوه خطوات حركه حركات",
    "slow": "slow slowly careful calm بطيء بطيئه هادي بهدوء",
    "fast": "fast quick quickly speed hurry سريع سريعه بسرعه سرعه",
    "like": "like likes prefer prefers preferred favourite favorite يفضل تفضل يحب تحب مفضل مفضله",
}
MIN_SCORE = 0.12  # below this a fact is not "close" and is not returned


def _fold(text: str) -> str:
    return AR_MARKS.sub("", text.lower()).translate(AR_FOLD)


CONCEPT_OF = {_fold(word): f"~{idea}" for idea, words in CONCEPTS.items() for word in words.split()}


def _stem(word: str) -> str:
    if word.isascii():
        for suffix in ("ing", "ed", "es", "s"):
            if word.endswith(suffix) and len(word) - len(suffix) >= 3:
                return word[: -len(suffix)]
        return word
    for article in AR_ARTICLE:
        if word.startswith(article) and len(word) - len(article) >= 2:
            return word[len(article):]
    return word


def normalise_words(text: str) -> list[str]:
    """The words of a text as the search compares them: lower case, Arabic marks removed and letter forms folded, the article and plural endings off, numbers as '#',
    and short common words dropped."""
    text = _fold(text)
    words = []
    for raw in WORD.findall(text):
        if raw.isdigit():
            words.append("#")
            continue
        if raw in STOP:
            continue
        words.append(CONCEPT_OF.get(raw) or CONCEPT_OF.get(_stem(raw)) or _stem(raw))
    return words


def _pieces(words: list[str]) -> Counter:
    """Three-letter pieces of every word: 'won'/'wins' or 'تفضل'/'المفضله' still share pieces when the whole words differ."""
    out: Counter = Counter()
    for word in words:
        if word.startswith("~") or word == "#":
            continue
        padded = f" {word} "
        out.update(padded[i:i + 3] for i in range(len(padded) - 2))
    return out


def _cosine(a: dict, b: dict) -> float:
    dot = sum(value * b.get(key, 0.0) for key, value in a.items())
    norm = math.sqrt(sum(v * v for v in a.values())) * math.sqrt(sum(v * v for v in b.values()))
    return dot / norm if norm else 0.0


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

    def search(self, game: str, query: str, limit: int = 4) -> list[Fact]:
        """The facts for a game closest in meaning to a question, best first ('load memory' when the agent asks).

        A fact's score: how much of the question it holds (each word weighted by how rare it is among this game's facts, so a word every fact has says little), plus how
        focused it is on the question (a cosine, so a short fact about exactly this beats a long one that mentions it), plus three-letter word pieces (other forms of a word).
        A small vocabulary joins words that name the same idea in English and Arabic. Question words that no fact has are left out: they say nothing about which fact is
        closer. Pending facts and other games' facts are never returned; nothing is returned when nothing is close."""
        facts = [f for f in self.facts if f.game == game and not f.pending]
        texts = {f.id: normalise_words(f"{f.topic} {f.text}") for f in facts}
        seen_in = Counter(word for words in texts.values() for word in set(words))
        asked = normalise_words(query or "")
        known = [word for word in asked if word in seen_in]
        if not known:
            return []
        weight = {word: math.log(1 + (len(facts) + 1) / (1 + seen_in[word])) for word in seen_in}

        def vector(words: list[str]) -> dict:
            return {word: count * weight[word] for word, count in Counter(words).items()}

        question, question_pieces = vector(known), _pieces(asked)
        total = sum(question.values())
        scored = []
        for fact in facts:
            words = vector(texts[fact.id])
            covered = sum(value for word, value in question.items() if word in words) / total
            score = 0.6 * covered + 0.25 * _cosine(question, words) + 0.15 * _cosine(question_pieces, _pieces(texts[fact.id]))
            if score >= MIN_SCORE:
                scored.append((score, fact))
        scored.sort(key=lambda item: (-item[0], -item[1].hits, -item[1].created))
        return [fact for _, fact in scored[:max(1, limit)]]

    def context_for(self, game: str, limit: int = 4, query: str = "") -> str:
        """The block put in front of the model: fenced, because a memory is data and never an instruction. Empty when there is nothing to say.
        With a `query`, the facts closest to it (`search`); without one, the most useful facts (`recall`)."""
        facts = self.search(game, query, limit) if query else self.recall(game, limit)
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
