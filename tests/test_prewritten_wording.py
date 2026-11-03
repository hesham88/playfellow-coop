"""Rung 4 is a PRE-WRITTEN skill: written ahead of time by our team with AI coding agents, reviewed and tested; the runtime model only
picks it. It was never written by a person by hand, so no public text may call it human-written (owner decision, 2 Nov 2026).
The internal origin key `human_skill` / rung key `human_skills` stays, so result files and code keep matching. Result files written
before 3 Nov 2026 keep their old label `[Assisted: Human Local Skill]` (records are never rewritten); the README glossary explains it."""
from __future__ import annotations

import re
from pathlib import Path

from playfellow_coop.evalkit import attribution, ladder

ROOT = Path(__file__).resolve().parent.parent
BANNED = re.compile(r"human[- ]written|human[- ]authored|human local skill|human skill", re.IGNORECASE)
GLOSSARY = ("Result files written before 3 Nov 2026 carry the label `[Assisted: Human Local Skill]`; "
            "it means the pre-written skill above (written ahead of time by our team with AI coding agents).")
ALLOWED = {"README.md": GLOSSARY, "playfellow_coop/evalkit/attribution.py": 'LEGACY_PREWRITTEN_LABEL = "[Assisted: Human Local Skill]"'}


def _public_files():
    for pattern in ("*.md", "docs/**/*.md", "playfellow_coop/**/*.py", "bench/**/*.py", "tools/**/*.py", "demo/**/*.py"):
        yield from ROOT.glob(pattern)


def test_the_rung_and_the_label_say_pre_written():
    rung = ladder.BY_KEY["human_skills"]
    assert rung.title == "System with pre-written skills"
    assert attribution.label(attribution.Shares(human_skill=0.5, model_chunk=0.5)) == "[Assisted: Pre-written Skill]"
    assert "pre-written skill" in attribution.Shares(human_skill=1.0).as_text()


def test_an_old_result_file_label_still_reads_as_the_pre_written_rung():
    assert attribution.is_prewritten_label("[Assisted: Human Local Skill]") and attribution.is_prewritten_label("[Assisted: Pre-written Skill]")
    assert not attribution.is_prewritten_label("[Model Alone]")


def test_no_public_text_calls_a_skill_human_written():
    found = []
    for path in _public_files():
        rel = path.relative_to(ROOT).as_posix()
        if rel.startswith(("results/", "tests/")):
            continue
        for number, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if BANNED.search(line) and ALLOWED.get(rel, "\0") not in line:
                found.append(f"{rel}:{number}: {line.strip()[:120]}")
    assert not found, "\n".join(found)


def test_the_readme_carries_the_glossary_line_for_old_files():
    assert GLOSSARY in (ROOT / "README.md").read_text(encoding="utf-8")
