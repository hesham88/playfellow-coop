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
    for marker in ("fair budget", "Model-written skills", "maze_chase", "key_caves"):
        line = next(row for row in ladder.splitlines() if marker in row)
        assert "pending: run after the owner's yes" in line, marker  # F1/F2 rows stay pending until their files exist
    assert "15 of 15" in ladder and "14 of 15" in ladder and "0 of 15" in ladder


def test_the_public_speed_figure_is_the_measured_bracket():
    assert "17–24x" in README and "27x" not in README and "27×" not in README
