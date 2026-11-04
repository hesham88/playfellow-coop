"""The README keeps the headline; docs/metrics.md keeps every measured table. Rungs are filled only from committed result files,
every count the README quotes stands in a metrics row that names its file, and the public speed figure is never overstated."""
from __future__ import annotations

import json
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
README = (ROOT / "README.md").read_text(encoding="utf-8")
METRICS = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8")


def _ladder() -> str:
    assert "## The ladder" in METRICS
    return METRICS.split("## The ladder", 1)[1].split("\n## ", 1)[0]


def _rows_with_files(text: str) -> list[str]:
    return [row for row in text.splitlines() if row.startswith("| ") and "`results/" in row]


def test_every_result_file_named_in_the_metrics_exists():
    named = set(re.findall(r"`(results/[^`]+\.(?:json|md))`", METRICS))
    assert named, "the metrics page names no result file"
    missing = sorted(name for name in named if not (ROOT / name).is_file())
    assert not missing, missing


def test_the_ladder_fills_only_from_committed_files():
    ladder = _ladder()
    for name in ("muse-skills-pt1.json", "base" + "ten-skills.json", "muse-raw-20261027.json"):
        assert name in ladder, name
    for row in ladder.splitlines():
        if row.startswith("| ") and re.search(r"\d+ of \d+", row) and not row.startswith("| Game"):
            assert "`results/" in row or "results/" in row, row  # no count without its file
    assert "fair budget" not in ladder or "no file yet" in ladder  # a rung that has not run has no row with a number
    newest: dict[str, Path] = {}
    for path in sorted((ROOT / "results" / "skillsmith").glob("skillsmith-*.json")):
        if path.name.split("-")[1] in ("muse", "open"):
            newest[path.name.split("-")[1]] = path
    for path in newest.values():
        doc = json.loads(path.read_text(encoding="utf-8"))
        assert path.name in ladder
        for game, row in doc["games"].items():
            held = row.get("held_out") or {}
            if held.get("played"):
                assert str(held["progress_iqm"]) in ladder, game
    assert "15 of 15" in ladder and "14 of 15" in ladder and "0 of 15" in ladder


def test_every_count_the_readme_quotes_stands_in_a_metrics_row_with_its_file():
    rows = "\n".join(_rows_with_files(METRICS))
    for count in sorted(set(re.findall(r"\b\d+ of \d+\b", README))):
        assert count in rows, count  # the README and the metrics page quote the same runs


def test_the_sam_marks_and_wonder_rows_match_their_files():
    ladder = _ladder()
    sam = next(row for row in ladder.splitlines() if "SAM 3.1 marks" in row)
    assert "muse-sam-20261102.json" in sam and "0 of 28" in sam and "model alone" in sam.lower()
    for text in (README, METRICS):
        assert "learned the controls" not in text  # first sight drafts a card; it does not learn controls
    assert "draft" in README.lower() and "wonder-live-20261102.json" in METRICS


def test_the_readme_points_to_the_evidence_once():
    assert "docs/metrics.md" in README and "Evidence rule" in README


def test_the_public_speed_figure_is_the_measured_bracket():
    for text in (README, METRICS):
        assert "17–24x" in text and "27x" not in text and "27×" not in text
