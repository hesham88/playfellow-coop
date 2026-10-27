"""demo/trace_report.py: a pf-trace/1 file in, the numbers the credit-day trials are judged by out (cost per turn and per win, cache hit
share, p50/p95 latency, parse-valid share). It only reads; it prints no word that was said, no picture and no key (none is in the file)."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

import pytest

from playfellow_coop import trace

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import trace_report as tr  # noqa: E402

SYSTEM = "You are a buddy."


def make(tmp_path, name="run.trace.jsonl", cached=(0, 800, 800, 0), turns=((["UP"], None), (["UP"], None), (["RIGHT"], True), ([], None))):
    log = trace.Trace(tmp_path / name, "s1")
    plans = [(1000, cached[0], 50, 0.0020, 400.0, {"valid": True, "dropped": 0, "actions": 1}),
             (1000, cached[1], 40, 0.0012, 300.0, {"valid": True, "dropped": 0, "actions": 1}),
             (1000, cached[2], 60, 0.0013, 500.0, {"valid": True, "dropped": 1, "actions": 1}),
             (500, cached[3], 10, 0.0007, 200.0, {"valid": False, "dropped": 0, "actions": 0})]
    for tin, cached_in, out, cost, ms, parse in plans:
        log.request("plan", model="muse-spark", prefix=SYSTEM, tokens_in=tin, tokens_cached=cached_in, tokens_out=out, cost_usd=cost,
                    request_ms=ms, encode_ms=5.0, parse_ms=1.0, finish_reason="stop", parse=parse)
    for ms in (100.0, 120.0):
        log.request("marks", model="sam-3.1", images=1, image_bytes=900, cost_usd=0.0025, request_ms=ms, status=200, parse={"valid": True, "boxes": 2})
    log.request("voice", model="muse-voice-transcribe-1.0", audio_ms=1500, cost_usd=0.0001, request_ms=700.0, parse={"valid": True})
    for actions, won in turns:
        log.turn(actions=actions, won=won)
    log.close()
    return tmp_path / name


def test_the_numbers_come_out_right(tmp_path):
    s = tr.summarize(*tr.read(make(tmp_path)))
    assert s["trial"] == "s1" and s["requests"] == {"plan": 4, "marks": 2, "voice": 1} and s["turns"] == 4
    assert s["plan"]["parse_valid_share"] == pytest.approx(3 / 4) and s["plan"]["card_valid_share"] == pytest.approx(2 / 4)
    assert s["plan"]["dropped_actions"] == 1
    assert s["tokens"] == {"in": 3500, "cached": 1600, "out": 160, "cache_hit_share": pytest.approx(1600 / 3500), "per_win": 3660}
    assert s["latency_ms"]["plan"] == {"n": 4, "p50": 300.0, "p95": 500.0}  # nearest rank, the same rule as the stage timer
    assert s["latency_ms"]["marks"] == {"n": 2, "p50": 100.0, "p95": 120.0}
    total = 0.0020 + 0.0012 + 0.0013 + 0.0007 + 2 * 0.0025 + 0.0001
    assert s["cost_usd"]["total"] == pytest.approx(total) and s["cost_usd"]["per_turn"] == pytest.approx(total / 4)
    assert s["wins"] == 1 and s["cost_usd"]["per_win"] == pytest.approx(total) and s["tokens"]["per_win"] == 3660
    assert s["prefix"] == {"distinct": 1, "stable": True}


def test_a_provider_that_never_reports_cached_tokens_gives_no_share_not_zero(tmp_path):
    s = tr.summarize(*tr.read(make(tmp_path, cached=(None, None, None, None))))
    assert s["tokens"]["cached"] is None and s["tokens"]["cache_hit_share"] is None
    assert any("not reported" in line for line in tr.render(s))


def test_with_no_win_there_is_no_cost_per_win_and_the_report_says_so(tmp_path):
    s = tr.summarize(*tr.read(make(tmp_path, turns=((["UP"], None),))))
    assert s["wins"] == 0 and s["cost_usd"]["per_win"] is None and s["tokens"]["per_win"] is None
    assert any("no win" in line for line in tr.render(s))


def test_a_changing_prefix_is_reported_as_not_stable(tmp_path):
    path = tmp_path / "x.jsonl"
    log = trace.Trace(path, "s1")
    log.request("plan", prefix="one")
    log.request("plan", prefix="two")
    log.close()
    s = tr.summarize(*tr.read(path))
    assert s["prefix"] == {"distinct": 2, "stable": False}
    assert any("NOT stable" in line for line in tr.render(s))


def test_errors_are_counted_per_stage(tmp_path):
    path = tmp_path / "x.jsonl"
    log = trace.Trace(path, "s1")
    log.request("plan", error="busy", parse={"valid": False})
    log.request("plan", parse={"valid": True, "dropped": 0, "actions": 1}, request_ms=10.0)
    log.close()
    s = tr.summarize(*tr.read(path))
    assert s["errors"] == {"plan": 1} and s["plan"]["parse_valid_share"] == pytest.approx(0.5)


def test_an_empty_trace_is_fine(tmp_path):
    path = tmp_path / "x.jsonl"
    trace.Trace(path, "s1").close()
    s = tr.summarize(*tr.read(path))
    assert s["requests"] == {} and s["tokens"]["cache_hit_share"] is None and s["cost_usd"]["total"] == 0
    assert any("no requests" in line for line in tr.render(s))


def test_percentiles_use_nearest_rank():
    assert tr.percentile([5.0], 0.95) == 5.0
    assert tr.percentile([1.0, 2.0, 3.0, 4.0], 0.50) == 2.0 and tr.percentile([1.0, 2.0, 3.0, 4.0], 0.95) == 4.0
    assert tr.percentile([], 0.5) is None
    values = list(range(1, 101))
    assert tr.percentile(values, 0.95) == values[math.ceil(0.95 * 100) - 1]


def test_the_report_prints_the_headline_numbers(tmp_path):
    text = "\n".join(tr.render(tr.summarize(*tr.read(make(tmp_path)))))
    for needle in ("trial s1", "plan 4", "marks 2", "voice 1", "cache hit", "45.7%", "p50", "p95", "cost per turn", "cost per win", "parse valid", "75.0%"):
        assert needle in text, needle


def test_a_file_that_is_not_a_trace_is_refused(tmp_path):
    for body in ("", "not json\n", json.dumps({"type": "header", "schema": "pf-session-log/1"}) + "\n", json.dumps({"type": "request"}) + "\n"):
        path = tmp_path / "bad.jsonl"
        path.write_text(body, encoding="utf-8")
        with pytest.raises(tr.NotATrace):
            tr.read(path)
    with pytest.raises(tr.NotATrace):
        tr.read(tmp_path / "missing.jsonl")


def test_the_command_prints_each_file_and_returns_2_for_a_bad_one(tmp_path, capsys):
    good = make(tmp_path)
    assert tr.main([str(good)]) == 0 and "trial s1" in capsys.readouterr().out
    bad = tmp_path / "bad.jsonl"
    bad.write_text("nope\n", encoding="utf-8")
    assert tr.main([str(good), str(bad)]) == 2 and "bad.jsonl" in capsys.readouterr().out


def test_json_mode_prints_the_summary_as_json(tmp_path, capsys):
    assert tr.main([str(make(tmp_path)), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["trial"] == "s1"


def test_the_report_only_reads_the_file(tmp_path):
    path = make(tmp_path)
    before = path.read_bytes()
    tr.main([str(path)])
    assert path.read_bytes() == before and sorted(p.name for p in tmp_path.iterdir()) == ["run.trace.jsonl"]
