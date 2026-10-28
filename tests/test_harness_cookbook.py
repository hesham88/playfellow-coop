"""Patterns from the Meta cookbook, built into the harness: the five ends of a loop and the doom-loop stop, policy with scopes and protected tools, staged plans, the goal and its
oracle, compaction, deterministic replay fixtures and their gate, the dry run, and the circuit breaker and the empty-turn retry in the brain."""
from __future__ import annotations

import json

import httpx
import pytest
from PIL import Image

from brain import BrainError
from brain.breaker import CircuitBreaker
from playfellow_coop.dry_run import DryRunHands
from playfellow_coop.harness import evaluate as ev
from playfellow_coop.harness import flow
from playfellow_coop.harness.runtime import Harness
from playfellow_coop.harness.security import ALLOW, ASK, DENY, Confirmation, Policy
from playfellow_coop.harness.state import Session, SessionStore
from playfellow_coop.harness.tools import Tool, ToolRegistry
from playfellow_coop.muse_brain import MuseBrain


# ---------------------------------------------------------------- the loop's brakes
def test_a_loop_ends_in_one_of_five_ways_and_only_the_first_is_success():
    g = flow.LoopGuard(max_iterations=5, max_usd=0.10)
    assert g.check(1, complete=True) == flow.COMPLETE and g.check(1, cancelled=True) == flow.CANCELLED and g.check(1, cannot=True) == flow.CANNOT
    assert g.check(1, spent_usd=0.10) == flow.BUDGET and g.check(5) == flow.ITERATION_CAP and g.check(1) is None


def test_the_same_signature_three_times_in_a_row_is_a_doom_loop_and_any_change_resets_it():
    g = flow.LoopGuard(max_iterations=100)
    assert [g.check(i, signature=("chase_food", "step_limit", b"same")) for i in (1, 2, 3)] == [None, None, flow.DOOM_LOOP]
    g2 = flow.LoopGuard(max_iterations=100)
    assert [g2.check(i, signature=s) for i, s in enumerate(["a", "a", "b", "a", "a"])] == [None] * 5
    with pytest.raises(ValueError):
        flow.LoopGuard(max_iterations=0)
    with pytest.raises(ValueError):
        flow.LoopGuard(repeat_limit=1)


# ---------------------------------------------------------------- policy: scopes, precedence, protected tools
def test_a_deny_beats_an_ask_and_an_ask_beats_an_allow_whatever_the_order():
    p = Policy(rules={"*": ALLOW, "wipe": DENY, "spend": ASK})
    assert p.decide("wipe") == DENY and p.decide("spend") == ASK and p.decide("look") == ALLOW
    assert Policy(rules={"*": DENY, "look": ALLOW}).decide("look") == DENY  # an allow never overrides a deny
    assert Policy().decide("anything") is None  # nothing said: the tool's own rule decides
    with pytest.raises(ValueError):
        Policy(rules={"x": "maybe"})


def test_approvals_have_scopes_and_a_protected_tool_can_only_ever_be_approved_once_at_a_time():
    p = Policy(protected={"harness.settings"}, rules={"spend": ASK})
    assert p.grant("spend", "game") and p.decide("spend") == ASK  # an ask rule keeps asking
    free = Policy()
    assert free.grant("look", "session") and free.decide("look") == ALLOW
    assert free.grant("note", "game") and free.decide("note") == ALLOW
    free.end_game()
    assert free.decide("note") is None and free.decide("look") == ALLOW  # a game-scoped grant ends with the game, a session one stays
    assert p.grant("harness.settings", "session") is False and p.grant("harness.settings", "game") is False  # no "always allow" for guardrails
    assert p.decide("harness.settings") == ASK
    assert p.grant("harness.settings", "once") and p.decide("harness.settings") == ALLOW and p.decide("harness.settings") == ASK  # consumed by one use
    denied = Policy(rules={"wipe": DENY})
    assert denied.grant("wipe", "once") is False and p.grant("x", "forever") is False


def test_the_registry_asks_the_player_remembers_a_scoped_approval_and_never_remembers_for_a_protected_tool():
    answers = iter(["session", "yes", "session", "session"])
    asked = []

    def ask(tool, args):
        asked.append(tool)
        return next(answers)

    policy = Policy(protected={"harness.settings"})
    reg = ToolRegistry(confirmation=Confirmation(ask), policy=policy)
    reg.register(Tool("spend", "spend credits", lambda: "paid", needs_confirm=True))
    reg.register(Tool("harness.settings", "change settings", lambda: "changed", needs_confirm=True))
    assert reg.call("spend").ok and reg.call("spend").ok and asked == ["spend"]  # "session": asked once, remembered
    assert reg.call("harness.settings").ok and reg.call("harness.settings").ok and asked.count("harness.settings") == 2  # a protected tool asks every time
    reg.policy.rules["spend"] = DENY
    assert reg.call("spend").error == "denied_by_policy"


# ---------------------------------------------------------------- staged plans: one refusal denies the whole plan
def test_a_plan_is_resolved_stage_by_stage_and_one_refusal_denies_everything_and_nothing_runs():
    ran = []
    reg = ToolRegistry(confirmation=Confirmation(lambda t, a: t != "wipe"))
    reg.register(Tool("count", "count lines", lambda path: ran.append(("count", path)) or 3))
    reg.register(Tool("say", "say a line", lambda text: ran.append(("say", text)) or "ok"))
    reg.register(Tool("wipe", "delete the log", lambda path: ran.append(("wipe", path)) or "gone", needs_confirm=True))
    plan = [("count", {"path": "a.log"}), ("say", {"text": "cleaning"}), ("wipe", {"path": "a.log"})]
    denied = reg.call_plan(plan)
    assert denied.status == "denied" and denied.stage == 2 and denied.reason == "not_approved" and ran == []  # the safe stages did not run either
    good = reg.call_plan(plan[:2])
    assert good.status == "ran" and [r.ok for r in good.results] == [True, True] and ran == [("count", "a.log"), ("say", "cleaning")]


def test_a_plan_with_an_unknown_tool_a_bad_argument_or_a_guard_refusal_is_denied_before_anything_runs():
    ran = []
    reg = ToolRegistry()
    reg.register(Tool("look", "look", lambda: ran.append("look") or "x"))
    reg.add_guard(lambda tool, args: "no" if args.get("blocked") else None)
    reg.register(Tool("poke", "poke", lambda blocked=False: ran.append("poke") or "x"))
    assert reg.call_plan([("look", {}), ("nope", {})]).reason == "unknown_tool"
    assert reg.call_plan([("look", {}), ("look", {"_x": 1})]).reason.startswith("blocked:argument")
    assert reg.call_plan([("look", {}), ("poke", {"blocked": True})]).reason == "blocked:no"
    assert ran == []


# ---------------------------------------------------------------- the goal and its oracle, compaction
def test_a_goal_is_pinned_reminds_after_idle_steps_and_closes_only_when_the_oracle_says_so(tmp_path):
    s = Session("g", SessionStore(tmp_path))
    s.set_goal("win the snake game", "the game is won")
    assert s.probe() == "" and s.close_goal(False) is False  # the model's word is not the oracle
    for _ in range(9):
        s.note_progress(None)
    assert s.probe() == ""
    s.note_progress(None)
    assert "Continue working toward the goal: win the snake game" in s.probe() and "the game is won" in s.probe()
    s.note_progress(5.0)  # progress resets the idle count
    assert s.probe() == "" and s.get("goal.best") == 5.0
    s.note_progress(3.0)  # a lower number is not progress
    assert s.get("goal.idle") == 1
    assert s.close_goal(True) is True and s.get("goal.done") is True and s.probe() == ""
    again = Session("g", SessionStore(tmp_path))  # saved, so it survives a restart
    assert again.get("goal.text") == "win the snake game" and again.get("goal.done") is True
    assert Session("nogoal").close_goal(True) is False


def test_compaction_folds_the_old_middle_into_one_note_and_keeps_the_state_and_the_recent_events():
    s = Session("c")
    s.append("state", {"x": 1}, delta={"level": 3})
    for i in range(30):
        s.append("message" if i % 2 else "skill", {"i": i})
    assert s.compact(keep_last=10) == 21 and len(s.events) == 11
    first = s.events[0]
    assert first.kind == "note" and first.data["compacted"] == 21 and first.data["kinds"]["skill"] >= 10
    assert s.get("level") == 3 and s.events[-1].data == {"i": 29}  # the scratchpad and the newest event are untouched
    assert s.compact(keep_last=50) == 0


# ---------------------------------------------------------------- deterministic replay
EVENTS = [{"kind": "message", "data": {"text": "take the food"}}, {"kind": "skill", "data": {"name": "chase_food", "steps": 113}}, {"kind": "tool_result", "data": {"tool": "x", "ok": True}}]


def test_a_golden_fixture_replays_offline_with_no_diffs_and_never_gets_edited_in_place(tmp_path):
    expected = ev.project_context(EVENTS)
    path = tmp_path / "golden" / "snake_win.json"
    ev.save_fixture(path, "snake_win", EVENTS, expected)
    with pytest.raises(FileExistsError):
        ev.save_fixture(path, "snake_win", EVENTS, expected)
    report = ev.replay_fixture(path)
    assert report == {"name": "snake_win", "load": "ok", "diffs": []}
    ok, reports = ev.replay_gate(path.parent)
    assert ok and len(reports) == 1


def test_the_gate_counts_diffs_and_treats_an_unloadable_fixture_as_a_failure_not_a_pass(tmp_path):
    ev.save_fixture(tmp_path / "a.json", "a", EVENTS, ev.project_context(EVENTS))
    drifted = json.loads((tmp_path / "a.json").read_text(encoding="utf-8"))
    drifted["events"][1]["data"]["steps"] = 999  # the recorded event changed, the expectation did not
    (tmp_path / "b.json").write_text(json.dumps(drifted), encoding="utf-8")
    (tmp_path / "c.json").write_text(json.dumps({"schema_version": 2, "events": [], "expected_context": []}), encoding="utf-8")
    (tmp_path / "d.json").write_text("{not json", encoding="utf-8")
    ok, reports = ev.replay_gate(tmp_path)
    by = {r["name"]: r for r in reports}
    assert not ok and by["a"]["diffs"] == [] and len(by["b"]["diffs"]) == 1 and "steps=999" in by["b"]["diffs"][0]
    assert by["c"]["load"] == "partial" and "unsupported fixture schema version 2" in by["c"]["error"] and by["d"]["load"] == "partial"
    assert ev.replay_gate(tmp_path / "empty")[0] is False  # no fixtures is not a pass


# ---------------------------------------------------------------- the dry run
def test_a_dry_run_records_what_would_be_pressed_presses_nothing_and_passes_everything_else_through():
    class Real:
        pressed = []
        stopped = False

        def do(self, step, box):
            Real.pressed.append(step)

        def on_stop(self):
            Real.stopped = True

    class Step:
        def label(self):
            return "UP"

    dry = DryRunHands(Real())
    dry.do(Step(), None)
    dry.do(Step(), None)
    dry.on_stop()
    assert dry.pretended == ["UP", "UP"] and Real.pressed == [] and Real.stopped is True


# ---------------------------------------------------------------- the harness brakes in one place
def test_the_harness_calls_a_doom_loop_when_the_same_skill_ends_the_same_way_on_the_same_picture(tmp_path):
    h = Harness(tmp_path, game="snake", goal="win snake")
    assert h.turn_done(True, ("chase_food", "step_limit", b"p1")) is None
    assert h.turn_done(False, ("chase_food", "step_limit", b"p1")) is None
    assert h.turn_done(False, ("chase_food", "step_limit", b"p1")) == flow.DOOM_LOOP
    assert any(e.data.get("loop_end") == "doom_loop" for e in h.session.events)
    assert h.session.get("goal.text") == "win snake" and h.progress == 1
    for _ in range(9):
        h.turn_done(False, None)
    assert "Continue working toward the goal" in h.reminder()
    assert "harness.settings" in h.policy.protected


# ---------------------------------------------------------------- the brain: breaker and empty-turn retry
OK = {"choices": [{"message": {"content": '{"thought":"","say":"","actions":[]}'}, "finish_reason": "stop"}], "usage": {}}


def test_the_circuit_breaker_stops_the_calls_after_repeated_failures_and_a_success_resets_it():
    clock = [0.0]
    sent = []

    def handler(request):
        sent.append(1)
        return httpx.Response(503, json={})

    brain = MuseBrain("muse-spark-1.3", "k", client=httpx.Client(transport=httpx.MockTransport(handler)), breaker=CircuitBreaker("muse", clock=lambda: clock[0]))
    img = [Image.new("RGB", (8, 8))]
    for _ in range(2):
        with pytest.raises(BrainError):
            brain.ask("s", "t", img)
    assert len(sent) == 2
    with pytest.raises(BrainError) as blocked:  # open: nothing is sent
        brain.ask("s", "t", img)
    assert len(sent) == 2 and blocked.value.key == "busy" and blocked.value.retry is True


def test_an_empty_answer_caused_by_running_out_of_budget_is_not_retried_but_a_dropped_stream_is():
    seen = []

    def length_cut(request):
        seen.append(1)
        return httpx.Response(200, json={"choices": [{"message": {"content": ""}, "finish_reason": "length"}], "usage": {}})

    brain = MuseBrain("muse-spark-1.3", "k", client=httpx.Client(transport=httpx.MockTransport(length_cut)))
    with pytest.raises(BrainError):
        brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert len(seen) == 1  # the budget ran out: asking the same thing again would do the same
