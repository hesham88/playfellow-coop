"""pf-trace/1 to a Chrome-trace file that Perfetto opens: the shape Perfetto reads, nothing private, order kept, never overwrites."""
from __future__ import annotations

import json

import pytest

from playfellow_coop import trace_perfetto as tp
from playfellow_coop.trace import Trace

SYSTEM = "You are a game buddy."


def make_trace(tmp_path):
    path = tmp_path / "t.jsonl"
    log = Trace(path, "trial-1", commit="abcdef0")
    log.request("marks", model="sam-3.1", encode_ms=10, request_ms=300, parse_ms=2, cost_usd=0.0025, parse={"valid": True, "boxes": 3})
    log.request("plan", model="muse-spark-1.3", prefix=SYSTEM, images=1, image_bytes=5000, tokens_in=900, tokens_cached=400, tokens_out=120,
                encode_ms=20, request_ms=1400, parse_ms=3, finish_reason="stop", cost_usd=0.002, parse={"valid": True, "actions": 2})
    log.turn(actions=["right", "up"], won=False, progress=0.4, bumps=0)
    log.request("voice", audio_ms=1840, request_ms=700, cost_usd=0.0001)
    log.close()
    return path


def test_the_document_has_the_shape_perfetto_reads(tmp_path):
    doc = tp.to_events(tp.read_trace(make_trace(tmp_path)))
    assert set(doc) >= {"traceEvents", "displayTimeUnit", "metadata"}
    phases = {e["ph"] for e in doc["traceEvents"]}
    assert phases == {"M", "X", "C", "i"}
    for e in doc["traceEvents"]:
        assert e["pid"] == 1 and ("ts" in e or e["ph"] == "M")
        if e["ph"] == "X":
            assert e["dur"] > 0 and isinstance(e["ts"], int)


def test_each_request_is_a_slice_with_its_parts_inside_it_on_its_stage_track(tmp_path):
    doc = tp.to_events(tp.read_trace(make_trace(tmp_path)))
    plan = next(e for e in doc["traceEvents"] if e["ph"] == "X" and e["name"].startswith("plan"))
    assert plan["tid"] == tp.TRACKS["plan"] and plan["dur"] == (20 + 1400 + 3) * 1000
    parts = [e for e in doc["traceEvents"] if e["ph"] == "X" and e.get("cat") == "plan" and not e["name"].startswith("plan")]
    assert [p["name"] for p in parts] == ["encode", "wait for the service", "parse"]
    assert parts[0]["ts"] == plan["ts"] and parts[-1]["ts"] + parts[-1]["dur"] == plan["ts"] + plan["dur"]


def test_requests_keep_their_order_and_never_overlap_on_a_track(tmp_path):
    doc = tp.to_events(tp.read_trace(make_trace(tmp_path)))
    marks = next(e for e in doc["traceEvents"] if e["ph"] == "X" and e["name"].startswith("marks"))
    plan = next(e for e in doc["traceEvents"] if e["ph"] == "X" and e["name"].startswith("plan"))
    assert plan["ts"] >= marks["ts"] + marks["dur"]


def test_counters_add_up_tokens_and_cost(tmp_path):
    doc = tp.to_events(tp.read_trace(make_trace(tmp_path)))
    tokens = [e for e in doc["traceEvents"] if e["ph"] == "C" and e["name"] == "tokens"][-1]["args"]
    assert tokens == {"in": 900, "cached": 400, "out": 120}
    cost = [e for e in doc["traceEvents"] if e["ph"] == "C" and e["name"] == "cost_usd"][-1]["args"]["total"]
    assert cost == pytest.approx(0.0025 + 0.002 + 0.0001)


def test_turns_are_instants_and_the_metadata_says_the_timeline_is_not_wall_clock(tmp_path):
    doc = tp.to_events(tp.read_trace(make_trace(tmp_path)))
    turn = next(e for e in doc["traceEvents"] if e["ph"] == "i")
    assert turn["args"]["actions"] == ["right", "up"] and turn["args"]["progress"] == 0.4
    assert "not the time of day" in doc["metadata"]["timeline"]


def test_nothing_private_can_be_in_the_output(tmp_path):
    text = json.dumps(tp.to_events(tp.read_trace(make_trace(tmp_path))))
    assert SYSTEM not in text and "Bearer" not in text and "data:image" not in text and "C:\\" not in text


def test_a_file_that_is_not_a_trace_is_refused_and_the_output_is_never_overwritten(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text('{"schema": "other"}\n', encoding="utf-8")
    with pytest.raises(tp.TraceFileError):
        tp.read_trace(bad)
    notjson = tmp_path / "nj.jsonl"
    notjson.write_text("hello\n", encoding="utf-8")
    with pytest.raises(tp.TraceFileError):
        tp.read_trace(notjson)
    src = make_trace(tmp_path)
    out = tmp_path / "out.json"
    assert tp.convert(src, out) > 5
    with pytest.raises(FileExistsError):
        tp.convert(src, out)
    assert json.loads(out.read_text(encoding="utf-8"))["traceEvents"]
