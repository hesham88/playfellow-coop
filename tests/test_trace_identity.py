"""H4-25 trace tagging: every pf-trace/1 line says which agent acted in which session, so a cost or a key press can be attributed. The player is never written, not even
as a hash: a trace belongs to one PC, and the session id leads to the session store that knows the player. A value that does not look right is dropped, never written."""
import json

from playfellow_coop import trace, trace_perfetto
from playfellow_coop.harness.security import Identity


def lines(path) -> list[dict]:
    return [json.loads(line) for line in path.read_text(encoding="utf-8").splitlines() if line.strip()]


def test_every_line_carries_the_agent_and_the_session_but_never_the_player(tmp_path):
    buddy = Identity("buddy", "a1b2c3d4e5f6", "Quentin")
    t = trace.Trace(tmp_path / "t.jsonl", "t1", who=buddy)
    t.request("plan", model="muse-spark", tokens_in=10)
    t.request("marks", model="sam-3.1", images=1)
    t.turn(actions=["UP"])
    t.close()
    head, plan, marks, turn = lines(tmp_path / "t.jsonl")
    for record in (head, plan, marks, turn):
        assert record["who"] == {"agent": "buddy", "session": "a1b2c3d4e5f6"}
    assert "Quentin" not in (tmp_path / "t.jsonl").read_text(encoding="utf-8")


def test_a_line_can_name_another_agent_for_one_call(tmp_path):
    t = trace.Trace(tmp_path / "t.jsonl", "t1", who=Identity("buddy", "s1"))
    t.turn(actions=["LEFT"], who=Identity("skill:chase_food", "s1"))
    t.request("plan", who={"agent": "buddy", "session": "s1", "player": "Quentin"})  # the harness's own tag() form is accepted too
    t.turn(actions=["UP"], who=Identity("Skill Bad Name", "s1"))  # a bad name is dropped, NOT replaced by the default: that would credit the wrong agent
    t.close()
    _, turn, plan, bad = lines(tmp_path / "t.jsonl")
    assert turn["who"] == {"agent": "skill:chase_food", "session": "s1"} and plan["who"] == {"agent": "buddy", "session": "s1"}
    assert "who" not in bad


def test_an_identity_that_does_not_look_right_is_dropped_never_written(tmp_path):
    bad = [Identity("Quentin Smith", "s1"), Identity("buddy", "C:\\Users\\q"), {"agent": "buddy"}, {"agent": 7, "session": "s1"}, "buddy"]
    t = trace.Trace(tmp_path / "t.jsonl", "t1")
    for who in bad:
        t.request("plan", who=who)
    t.close()
    records = lines(tmp_path / "t.jsonl")
    assert all("who" not in r for r in records)
    assert "Quentin" not in (tmp_path / "t.jsonl").read_text(encoding="utf-8") and "Users" not in (tmp_path / "t.jsonl").read_text(encoding="utf-8")


def test_without_an_identity_the_lines_are_as_before(tmp_path):
    t = trace.Trace(tmp_path / "t.jsonl", "t1")
    t.turn(actions=["UP"])
    t.close()
    assert lines(tmp_path / "t.jsonl")[1] == {"type": "turn", "trial": "t1", "n": 1, "actions": ["UP"]}


def test_perfetto_shows_who_acted_on_every_slice_and_turn(tmp_path):
    t = trace.Trace(tmp_path / "t.jsonl", "t1", who=Identity("buddy", "a1b2c3d4e5f6"))
    t.request("plan", model="muse-spark", request_ms=120.0)
    t.turn(actions=["UP"], who=Identity("skill:chase_food", "a1b2c3d4e5f6"))
    t.close()
    document = trace_perfetto.to_events(trace_perfetto.read_trace(tmp_path / "t.jsonl"))
    slice_ = next(e for e in document["traceEvents"] if e.get("ph") == "X" and e.get("name") == "plan #1")
    mark = next(e for e in document["traceEvents"] if e.get("ph") == "i")
    assert slice_["args"]["who"] == "buddy" and mark["args"]["who"] == "skill:chase_food"
    assert document["metadata"]["session"] == "a1b2c3d4e5f6"
    assert "a1b2c3d4e5f6" in next(e for e in document["traceEvents"] if e.get("name") == "process_name")["args"]["name"]


def test_main_tags_the_trace_with_the_harness_identity(tmp_path):
    from playfellow_coop import __main__ as entry
    from playfellow_coop.harness.runtime import Harness
    from tests.test_main import Parts
    path = tmp_path / "t.jsonl"

    def build(argv):
        import settings
        parts = Parts()
        parts.marks_source = "off"
        parts.trace_plan = {"path": path, "trial": "s1"}
        parts.harness = Harness(folder=tmp_path / "harness", game="snake")
        return parts, settings.Settings()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        p.tracer.request("plan", model="muse-spark")
        return "round_done"

    assert entry.main([], build_fn=build, listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=lambda *a: None) == 0
    head, plan = lines(path)
    assert head["who"]["agent"] == "buddy" and plan["who"] == head["who"] and len(plan["who"]["session"]) == 12
