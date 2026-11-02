"""Stale-status guard: public text must not claim live calls have not happened once result files prove they have.

Live Muse, SAM 3.1 and voice calls were made and recorded on 2026-11-02 (`results/sam/sam-live-20261102.json`,
`results/wonder/wonder-live-20261102.json`, `results/access/assist-live-muse-strict-20261102.json`,
`tests/fixtures/real/`). Any public doc that again says no live call has been made is stale and fails here.
"""
from __future__ import annotations

import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

STALE = (
    "no live Muse or sam call has been made yet",
    "no real voice call yet",
    "no live run on a real window yet",
)

PUBLIC_DOCS = ("README.md", "JUDGES.md")


def _public_docs(root: Path) -> list[Path]:
    docs = [root / name for name in PUBLIC_DOCS]
    docs += sorted((root / "docs").rglob("*.md"))
    return [p for p in docs if p.is_file()]


def _stale_hits(root: Path) -> list[str]:
    hits = []
    for path in _public_docs(root):
        text = path.read_text(encoding="utf-8", errors="replace").lower()
        hits += [f"{path.relative_to(root)}: {phrase}" for phrase in STALE if phrase in text]
    return hits


def test_no_public_doc_claims_live_calls_have_not_happened():
    assert _stale_hits(ROOT) == []


def test_the_story_names_the_live_result_files():
    story = (ROOT / "docs" / "project-story.md").read_text(encoding="utf-8")
    for name in ("sam-live-20261102.json", "assist-live-muse-strict-20261102.json", "wonder-live-20261102.json"):
        assert name in story, name


def test_the_scan_catches_a_planted_stale_line(tmp_path, monkeypatch):
    monkeypatch.setattr(sys.modules[__name__], "ROOT", tmp_path)
    (tmp_path / "docs").mkdir()
    (tmp_path / "README.md").write_text("Status: no real voice call yet.\n", encoding="utf-8")
    (tmp_path / "JUDGES.md").write_text("Try it.\n", encoding="utf-8")
    (tmp_path / "docs" / "ok.md").write_text("Live calls are recorded in the result files.\n", encoding="utf-8")
    assert _stale_hits(tmp_path) == ["README.md: no real voice call yet"]
