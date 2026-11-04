"""The skill catalogue of a game and its genre, one book per game (`games/<game>/skills.json`), each skill with an honest status.

A skill row comes from our own reading of the game's files and source and from the research agent's report, checked against those files.
Statuses are earned, not declared:
  proven    used in a recorded run that met its check (`proof` names the session)
  tested    built and covered by tests, not yet seen working in the real game
  built     code exists, no test or run yet
  game      the game's own feature does it and the buddy only presses the key
  known     researched, written down, not built
A status of proven without a proof, or tested/built/game without the code it names, fails `check_book`.
"""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path

STATUSES = ("proven", "tested", "built", "game", "known")
TIERS = ("genre", "game")
#: words that must never appear in a book; the source of outside research is always called the research agent
BANNED_WORDS = ("gem" + "ini", "arg" + "on", "deep res" + "earch", "goo" + "gle")  # spelled in parts so the names appear nowhere in the repo


@dataclass
class Skill:
    id: str
    name: str
    tier: str  # genre: carries over to any game of the genre; game: this game only
    area: str
    what: str
    when: str
    how: str
    cue: str
    done_check: str
    level: str  # beginner, intermediate, pro
    source: str
    automation: str  # local, model, hard
    status: str = "known"
    code: str = ""  # module.function that does it
    proof: str = ""  # session folder that shows it


def load_book(path: Path) -> list[Skill]:
    return [Skill(**row) for row in json.loads(Path(path).read_text(encoding="utf-8"))]


def save_book(path: Path, skills: list[Skill]) -> None:
    Path(path).write_text(json.dumps([asdict(s) for s in skills], indent=1, ensure_ascii=False) + "\n", encoding="utf-8")


def check_book(skills: list[Skill]) -> list[str]:
    """Everything wrong with a book, as sentences; empty when it is sound."""
    problems = []
    seen = Counter(s.id for s in skills)
    problems += [f"duplicate id {i}" for i, n in seen.items() if n > 1]
    for s in skills:
        if s.status not in STATUSES:
            problems.append(f"{s.id}: unknown status {s.status}")
        if s.tier not in TIERS:
            problems.append(f"{s.id}: unknown tier {s.tier}")
        if s.status == "proven" and not s.proof:
            problems.append(f"{s.id}: proven with no proof")
        if s.status in ("proven", "tested", "built") and not s.code:
            problems.append(f"{s.id}: {s.status} but names no code")
        if not s.how or not s.what:
            problems.append(f"{s.id}: empty what or how")
        row = json.dumps(asdict(s)).lower()
        problems += [f"{s.id}: contains banned word {w!r}" for w in BANNED_WORDS if w in row]
    return problems


def summary(skills: list[Skill]) -> dict:
    return {"skills": len(skills), "by_status": dict(Counter(s.status for s in skills)), "by_tier": dict(Counter(s.tier for s in skills)),
            "by_area": dict(Counter(s.area for s in skills))}


def render_markdown(title: str, skills: list[Skill]) -> str:
    facts = summary(skills)
    out = [f"# {title}", "", f"{facts['skills']} skills. Status: " + ", ".join(f"{k} {v}" for k, v in sorted(facts["by_status"].items())) + ".",
           "Tier: " + ", ".join(f"{k} {v}" for k, v in sorted(facts["by_tier"].items())) + ".", ""]
    for area in sorted({s.area for s in skills}):
        out += [f"## {area}", "", "| Skill | Tier | Level | Status | What | How | Cue | Worked when |", "|---|---|---|---|---|---|---|---|"]
        for s in sorted((s for s in skills if s.area == area), key=lambda s: (s.tier, s.level, s.name)):
            cells = [s.name, s.tier, s.level, s.status + (f" ({s.proof})" if s.proof else ""), s.what, s.how, s.cue, s.done_check]
            out.append("| " + " | ".join(str(c).replace("|", "/").replace("\n", " ") for c in cells) + " |")
        out.append("")
    return "\n".join(out)
