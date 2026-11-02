"""The README ladder section: rungs filled only from committed result files, the frontier rows pending until their files exist, and the public speed figure never overstated."""
from __future__ import annotations

from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")


def _ladder() -> str:
    assert "## The ladder" in README
    return README.split("## The ladder", 1)[1].split("\n## ", 1)[0]


def test_the_ladder_fills_only_from_committed_files_and_keeps_the_frontier_pending():
    ladder = _ladder()
    for name in ("muse-skills-pt1.json", "base" + "ten-skills.json", "muse-raw-20261027.json", "speed-cost-20261102.json"):
        assert name in ladder and (ROOT / "results" / ("k-lane" if "skills" in name else "unseen" if "raw" in name else "speed") / name).is_file(), name
    line = next(row for row in ladder.splitlines() if "fair budget" in row)
    assert "pending: run after the owner's yes" in line  # the F2 row stays pending until its file exists
    import json as _json

    live = sorted((ROOT / "results" / "skillsmith").glob("skillsmith-*.json"))
    live = [p for p in live if p.name.split("-")[1] in ("muse", "open")]
    if not live:
        for marker in ("Model-written skills", "maze_chase", "key_caves"):
            line = next(row for row in ladder.splitlines() if marker in row)
            assert "pending: run after the owner's yes" in line, marker  # F1 rows stay pending until their files exist
    else:
        newest = {}
        for path in live:  # the switch names the newest live file per brain (tools/update_f1_rows.py)
            newest[path.name.split("-")[1]] = path
        for path in newest.values():
            doc = _json.loads(path.read_text(encoding="utf-8"))
            assert path.name in ladder
            for game, row in doc["games"].items():
                held = row.get("held_out") or {}
                if held.get("played"):
                    assert str(held["progress_iqm"]) in ladder, game
    assert "15 of 15" in ladder and "14 of 15" in ladder and "0 of 15" in ladder


def test_every_top_win_count_appears_in_a_table_row_with_its_file():
    import re

    top = README.split("**What each part adds**", 1)[1].split("**The co-op itself", 1)[0]
    tables = "\n".join(row for row in README.splitlines() if row.startswith("| ") and "`results/" in row)
    for count in set(re.findall(r"\d+ of \d+", top)):
        assert count in tables, count  # the top paragraph and the tables must quote the same runs


def test_the_sam_marks_and_wonder_rows_match_their_files():
    ladder = _ladder()
    sam = next(row for row in ladder.splitlines() if "SAM 3.1 marks" in row)
    assert "muse-sam-20261102.json" in sam and "0 of 28" in sam and "model alone" in sam.lower()
    assert "learned the controls" not in README  # first sight drafts a card; it does not learn controls
    assert "drafted the controls" in README and "wonder-live-20261102.json" in README


def test_the_public_speed_figure_is_the_measured_bracket():
    assert "17–24x" in README and "27x" not in README and "27×" not in README
