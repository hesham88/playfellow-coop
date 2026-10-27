"""propose, probe, compose (method adopted from Harness², our own code): the budget identity, the safety rules and the decision rules, all offline."""
from __future__ import annotations

import random

import pytest

from playfellow_coop import harness_loop as hl
from playfellow_coop.harness_loop import Harness, Rollout

BASE = Harness(system="Play the game.", marks_phrases={"me": "blue circle", "reward": "yellow circle"}, horizon=1)


def make_runner(table):
    """A fake game: the outcome depends only on the harness parts, so contrasts are deterministic. Calls are counted."""
    calls = []

    def run(harness, task, label):
        calls.append(label)
        parts = harness.parts()
        won = parts["horizon"] == 3 and "walls" in parts["tool_guidance"]
        progress = 0.2 + (0.3 if parts["horizon"] == 3 else 0) + (0.2 if "walls" in parts["tool_guidance"] else 0)
        tokens = 1000 // parts["horizon"] + 100
        return Rollout(label, harness.digest, won=won, progress=progress, steps=20, tokens=tokens, cost_usd=0.001, facts="blocked 4")

    run.calls = calls
    return run


def editor_for(inv, dom):
    def edit(kind, harness, base, lessons):
        return inv if kind == "invariant" else dom
    return edit


def test_one_round_costs_exactly_4_rollouts_and_3_sessions_and_k_rounds_cost_4k_and_3k():
    for k in (1, 2, 3):
        runner = make_runner(None)
        result = hl.propose_probe_compose("garden", BASE, runner, editor_for({"horizon": 3}, {"tool_guidance": "Dark squares are walls."}), k=k)
        assert len(runner.calls) == 4 * k and len(result.ledger.sessions) == 3 * k
        result.ledger.check()


def test_the_ledger_raises_when_a_run_does_not_land_on_the_identity():
    ledger = hl.Ledger(1)
    ledger.rollout("a")
    with pytest.raises(hl.BudgetError):
        ledger.check()


def test_edits_that_won_are_composed_and_adopted_and_the_gain_is_real():
    runner = make_runner(None)
    result = hl.propose_probe_compose("garden", BASE, runner, editor_for({"horizon": 3}, {"tool_guidance": "Dark squares are walls."}))
    rnd = result.rounds[0]
    assert set(rnd.kept_edits) == {"horizon", "tool_guidance"} and not rnd.chosen_is_base
    assert rnd.final.won and not rnd.base.won
    assert result.harness.horizon == 3


def test_an_edit_that_does_not_beat_the_base_contributes_nothing():
    runner = make_runner(None)
    result = hl.propose_probe_compose("garden", BASE, runner, editor_for({"memory_notes": "Be careful."}, {"stuck_note": "Try another way."}))
    rnd = result.rounds[0]
    assert rnd.kept_edits == {} and rnd.chosen_is_base and result.harness is BASE or result.harness == BASE


def test_where_two_winning_edits_touch_the_same_part_the_better_run_keeps_it():
    base = Rollout("b", "x", progress=0.2)
    weak = ({"horizon": 2}, Rollout("w", "x", progress=0.4))
    strong = ({"horizon": 3, "memory_notes": "m"}, Rollout("s", "x", progress=0.9))
    assert hl.compose(base, [weak, strong]) == {"horizon": 3, "memory_notes": "m"}
    assert hl.compose(base, [strong, weak]) == {"horizon": 3, "memory_notes": "m"}


def test_the_controls_card_is_not_an_editable_part_and_unknown_parts_are_refused():
    for bad in ({"controls_card": "x"}, {"keys": "w"}, {"allowed_keys": ["w"]}):
        with pytest.raises(hl.HarnessError, match="allow-list"):
            BASE.with_edits(bad, "x")
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"script": "import os"}, "x")


def test_edit_values_are_checked_for_size_type_and_marker_syntax():
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"system": "x" * (hl.MAX_TEXT + 1)}, "x")
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"horizon": 99}, "x")
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"horizon": True}, "x")
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"marks_phrases": {"me": "<|box;x1=0|>"}}, "x")
    with pytest.raises(hl.HarnessError):
        BASE.with_edits({"marks_phrases": {"Me!": "blue circle"}}, "x")


def test_an_invalid_proposal_keeps_the_current_harness_and_the_budget_still_lands():
    runner = make_runner(None)
    result = hl.propose_probe_compose("garden", BASE, runner, editor_for({"horizon": 99}, {"controls_card": "z"}))
    assert result.rounds[0].kept_edits == {} and len(runner.calls) == 4
    result.ledger.check()


def test_the_digest_follows_the_content_only():
    assert BASE.digest == BASE.with_edits({}, "other label").digest
    assert BASE.digest != BASE.with_edits({"horizon": 2}, "x").digest


def test_selection_is_by_score_not_by_label_or_position_and_the_base_wins_a_tie():
    better = Rollout("a", "h", won=True, progress=1.0)
    worse = Rollout("b", "h", won=False, progress=0.1)
    for seed in range(10):
        assert hl.pick_anonymous([worse, better], random.Random(seed)) == 1
        assert hl.pick_anonymous([better, worse], random.Random(seed)) == 0
    tie_base, tie_other = Rollout("base", "h", progress=0.5), Rollout("adapted", "h", progress=0.5)
    assert all(hl.pick_anonymous([tie_base, tie_other], random.Random(s)) == 0 for s in range(10))


def test_a_missing_measure_counts_as_the_worst_not_as_zero():
    assert Rollout("a", "h", progress=None).score() < Rollout("b", "h", progress=0.0).score()


def test_lessons_are_bounded_and_carry_to_the_next_task(tmp_path):
    path = tmp_path / "lessons.md"
    for i in range(30):
        hl.write_lesson(path, f"lesson {i} " + "x" * 500)
    text = hl.read_lessons(path)
    assert len(text.splitlines()) == hl.LESSON_LINES and all(len(line) <= hl.LESSON_CHARS for line in text.splitlines())
    assert "lesson 29" in text and "lesson 0 " not in text
    seen = []

    def editor(kind, harness, base, lessons):
        seen.append(lessons)
        return {}

    hl.propose_probe_compose("garden", BASE, make_runner(None), editor, lessons_path=path)
    assert "lesson 29" in seen[0]


def test_a_lesson_is_written_for_every_round_in_counted_facts(tmp_path):
    path = tmp_path / "l.md"
    hl.propose_probe_compose("level7", BASE, make_runner(None), editor_for({"horizon": 3}, {}), k=2, lessons_path=path)
    lines = path.read_text(encoding="utf-8").splitlines()
    assert len(lines) == 2 and all(line.startswith("level7:") and "tokens" in line for line in lines)


def test_k_must_be_a_whole_number_of_one_or_more():
    for bad in (0, -1, True, 1.5):
        with pytest.raises(hl.HarnessError):
            hl.propose_probe_compose("g", BASE, make_runner(None), editor_for({}, {}), k=bad)


def test_the_module_has_no_network_no_file_reads_beyond_the_lessons_and_no_dynamic_code():
    import inspect
    text = inspect.getsource(hl)
    for banned in ("import httpx", "import socket", "subprocess", "eval(", "exec(", "requests"):
        assert banned not in text
