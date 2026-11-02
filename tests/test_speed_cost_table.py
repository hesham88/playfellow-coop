"""The speed and cost table: built only from committed result files, every value sourced, absent values said as not measured, and the public fastpath figure brackets the measured ones."""
from __future__ import annotations

import json
from pathlib import Path

from bench.speed_cost_table import build_table

ROOT = Path(__file__).resolve().parents[1]


def test_the_table_reads_the_committed_files_and_names_them():
    table = build_table(ROOT)
    assert table["schema"] == "pf-speed-cost/1"
    by_source = {row["source"]: row for row in table["per_rung"]}
    assisted = by_source["results/k-lane/muse-skills-pt1.json"]
    assert assisted["rung"] == "human_skills" and assisted["wins"] == 15 and assisted["usd_per_win"] == 0.00272
    alone = by_source["results/unseen/muse-raw-20261027.json"]
    assert alone["wins"] == 0 and alone["usd_per_win"] == "not measured (no wins)"  # never a zero cost per win
    assert "results/k-lane/muse-skills-pt1-billing-failed.json" not in by_source  # the void file is not a rung row
    stages = table["stages_per_turn"]["results/k-lane/muse-skills-pt1.json"]
    assert stages["request"] != "not measured" and stages["request"]["source"].endswith("muse-skills-pt1.json")
    assert stages["mark"] == "not measured"  # a stage no episode timed is said so, never zeroed
    assert table["local_vs_model"]["local_skill_ms_per_step"] != "not measured"
    assert table["local_vs_model"]["model_call_ms"]["ms"] > 1000  # a model call is seconds; a local step is milliseconds


def test_the_fastpath_figure_brackets_the_measured_speedups_and_cache_rows_name_their_file():
    table = build_table(ROOT)
    fast = table["fastpath"]
    assert fast["public_figure"] == "17–24x" and "27" not in fast["public_figure"]
    assert min(fast["measured_speedup_x"]) >= 17 and max(fast["measured_speedup_x"]) <= 24
    shares = {row["file"]: row["cached_share"] for row in table["cache"]}
    assert shares["results/glass/muse-skills-20261029.json"] == 0.5744
    assert all(row["source"] == "results/cache/cache-ratio-20261030.json" for row in table["cache"])


def test_a_missing_stage_in_a_synthetic_file_is_not_measured_never_zero(tmp_path):
    results = tmp_path / "results" / "x"
    results.mkdir(parents=True)
    doc = {"schema": "pf-arena-run/1", "brain": "muse", "model": "m", "overall": {"episodes": 1, "wins": 0, "tokens_in": 10,
           "tokens_cached": 5, "usd_per_win": None, "tokens_per_win": None},
           "episodes": [{"extra": {"stages": {"request": {"n": 1, "p50": 2.0, "p90": 3.0, "p95": 3.0}}}}]}
    (results / "run.json").write_text(json.dumps(doc), encoding="utf-8")
    table = build_table(tmp_path)
    stages = table["stages_per_turn"]["results/x/run.json"]
    assert stages["request"]["p50_s"] == 2.0 and stages["capture"] == "not measured"
    assert table["per_rung"][0]["cache_share"] == 0.5
