"""INF1: the cached share of a paid run and its dollars at the documented prices, from saved result files only. Synthetic files with numbers checked by hand."""
import importlib.util
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parents[1]
spec = importlib.util.spec_from_file_location("cache_ratio", ROOT / "tools" / "cache_ratio.py")
cache_ratio = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cache_ratio)


def run_file(tmp_path, model="muse-spark-1.3", brain="muse", episodes=None, schema="pf-arena-run/1", name="run.json"):
    episodes = episodes if episodes is not None else [
        {"calls": 3, "tokens_in": 3000, "tokens_cached": 2000, "tokens_out": 300, "cost_usd": 0.005025},
        {"calls": 1, "tokens_in": 1000, "tokens_cached": 0, "tokens_out": 100, "cost_usd": 0.001675}]
    path = tmp_path / name
    path.write_text(json.dumps({"schema": schema, "condition": "c", "brain": brain, "model": model, "episodes": episodes}), encoding="utf-8")
    return path


def test_the_share_the_calls_and_the_dollars_follow_the_documented_prices(tmp_path):
    row = cache_ratio.summarize(run_file(tmp_path))
    assert row["tokens"] == {"in": 4000, "cached": 2000, "out": 400} and row["cached_share"] == 0.5
    assert row["calls"] == 4 and row["calls_after_first"] == 0.5 and row["episodes_with_any_cache_hit"] == 1
    usd = row["usd_at_documented_prices"]
    assert usd["charged"] == pytest.approx(2000 * 1.25e-6 + 2000 * 0.15e-6 + 400 * 4.25e-6)  # 0.0045
    assert usd["without_cache"] == pytest.approx(4000 * 1.25e-6 + 400 * 4.25e-6) and usd["saved_by_cache"] == pytest.approx(2000 * 1.10e-6)
    assert row["recorded_usd"] == pytest.approx(0.0067)  # what our budget wrote: every input token at the full rate
    low, high = row["cached_share_95"]
    assert 0.0 <= low <= 0.5 <= high <= 1.0 and cache_ratio.bootstrap_share([2000, 0], [3000, 1000]) == (low, high)  # seeded: the same every run


def test_runs_without_a_prompt_or_in_another_format_are_left_out_and_unknown_prices_give_no_dollars(tmp_path):
    assert cache_ratio.summarize(run_file(tmp_path, brain="builtin", episodes=[{"calls": 5, "tokens_in": 0, "tokens_cached": 0, "tokens_out": 0}])) is None
    assert cache_ratio.summarize(run_file(tmp_path, schema="something-else/1")) is None
    open_row = cache_ratio.summarize(run_file(tmp_path, model="meta-models/muse-spark-open-1026", brain="open"))
    assert open_row["usd_at_documented_prices"] is None and open_row["cached_share"] == 0.5
    assert cache_ratio.price_table("muse-spark") and cache_ratio.price_table("muse-spark-1.3") and cache_ratio.price_table("muse-sparkle") is None
    assert "no documented price" in cache_ratio.markdown([open_row])


def test_the_command_writes_the_table_and_the_numbers(tmp_path):
    path = run_file(tmp_path)
    md, js = tmp_path / "out.md", tmp_path / "out.json"
    assert cache_ratio.main([str(path), "--md", str(md), "--json", str(js)]) == 0
    assert "50.0%" in md.read_text(encoding="utf-8") and json.loads(js.read_text(encoding="utf-8"))["rows"][0]["cached_share"] == 0.5
    assert cache_ratio.main([str(run_file(tmp_path, schema="x/1", name="other.json"))]) == 1  # nothing to report is an error, not an empty table
