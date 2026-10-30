"""AD4: ADK's spans beside our pf-trace and Perfetto files, names and timings only (never a prompt, an answer, tool arguments or results)."""
import importlib.util
import json

import pytest

from playfellow_coop import trace_perfetto
from playfellow_coop.adk_app.tracing import ALLOWED, PID, merge, to_chrome

SECRET = "sk-" + "planted-secret-value"  # built at run time: it must never reach a written file


def span(name, agent, start_ms, end_ms, **extra):
    attributes = {"gen_ai.operation.name": name.split()[0], "gen_ai.agent.name": agent, "gcp.vertex.agent.llm_request": f'{{"key": "{SECRET}"}}',
                  "gcp.vertex.agent.tool_call_args": '{"text": "player words"}', "gen_ai.tool.call.arguments": SECRET, **extra}
    return {"name": name, "start_ns": start_ms * 1_000_000, "end_ns": end_ms * 1_000_000, "span_id": start_ms, "parent_id": None, "attributes": attributes}


def test_spans_become_one_track_per_agent_with_names_and_timings_only():
    events = to_chrome([span("invoke_agent episode", "episode", 10, 50), span("invoke_agent decider", "decider", 20, 25),
                        span("execute_tool start_skill", "decider", 21, 24, **{"gen_ai.tool.name": "start_skill"})])
    slices = [e for e in events if e["ph"] == "X"]
    threads = {e["args"]["name"]: e["tid"] for e in events if e.get("name") == "thread_name"}
    assert set(threads) == {"episode", "decider"} and all(e["pid"] == PID for e in events)
    assert [s["ts"] for s in slices] == [0, 10_000, 11_000] and slices[0]["dur"] == 40_000  # microseconds from the first span
    assert slices[2]["args"]["gen_ai.tool.name"] == "start_skill" and all(set(s["args"]) <= set(ALLOWED) for s in slices)
    text = json.dumps(events)
    assert SECRET not in text and "player words" not in text and "llm_request" not in text
    assert to_chrome([]) == []


def test_the_adk_events_sit_beside_the_app_side_document(tmp_path):
    from playfellow_coop.trace import Trace
    t = Trace(tmp_path / "t.jsonl", "t1")
    t.request("plan", model="muse-spark", request_ms=50.0)
    t.close()
    app = trace_perfetto.to_events(trace_perfetto.read_trace(tmp_path / "t.jsonl"))
    merged = merge(app, to_chrome([span("invoke_agent episode", "episode", 0, 5)]))
    pids = {e["pid"] for e in merged["traceEvents"]}
    assert pids == {1, PID} and merged["metadata"]["adk_spans"] == 1 and "own clock" in merged["metadata"]["adk_clock"]
    assert merged["metadata"]["trial"] == "t1"  # the app side's own metadata is kept


def _has_adk() -> bool:
    try:
        return importlib.util.find_spec("google.adk") is not None
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _has_adk(), reason="ADK lives in its own environment (AD1): run with the python of `tools/adk_env.py --venv <folder>`")
def test_a_real_episode_through_the_adk_graph_is_traced_on_both_sides(tmp_path):
    from playfellow_coop.adk_app.tracing import trace_episode
    summary = trace_episode("snake", 0, 40, tmp_path / "episode")
    lines = [json.loads(line) for line in (tmp_path / "episode.trace.jsonl").read_text(encoding="utf-8").splitlines()]
    assert lines[0]["who"] == {"agent": "adk:episode", "session": "episode"} and all(line.get("who") for line in lines[1:])
    assert len([line for line in lines if line["type"] == "turn"]) == summary["steps"] > 0
    document = json.loads((tmp_path / "episode.perfetto.json").read_text(encoding="utf-8"))
    adk = [e for e in document["traceEvents"] if e.get("pid") == PID and e["ph"] == "X"]
    assert summary["adk_spans"] > 0 and len(adk) == summary["adk_spans"] and {"decider", "actuator"} <= set(summary["agents"])
    assert "llm_request" not in json.dumps(document) and "tool_response" not in json.dumps(document)
