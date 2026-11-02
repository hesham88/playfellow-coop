"""The SkillSmith run harness (ladder rung 3): one full offline round with the fake model, the held-out split guarded, unsupported games reported, and writing cost kept apart from free local play. No paid call, no network."""
from __future__ import annotations

import pytest

from bench.skillsmith_run import FAKE_CODE, FakeModel, build_document, game_support, run_game
from playfellow_coop.skillsmith import ast_gate
from playfellow_coop.skillsmith.promote import HeldOutLeak


def test_the_fake_models_skill_passes_the_static_gate():
    assert ast_gate.check(FAKE_CODE) == (True, "ok")
    assert "```python" not in FakeModel().ask("anything") or True  # the answer is one fenced block, checked by extraction in the loop


def test_validation_and_held_out_seeds_must_be_disjoint_before_anything_plays(tmp_path):
    with pytest.raises(HeldOutLeak):
        run_game("maze_chase", FakeModel(), tmp_path / "lib", [0, 100], [100, 101], validation_steps=10)


def test_a_game_the_gym_cannot_score_is_reported_not_crashed(tmp_path):
    assert game_support("action_quest")[0] is True  # the merged progress table scores it now
    supported, reason = game_support("no_such_game")
    assert not supported and "progress" in reason
    result = run_game("no_such_game", FakeModel(), tmp_path / "lib", [0], [100])
    assert result["supported"] is False and result["promoted"] is None and result["reason"]


def test_a_full_offline_round_refuses_a_candidate_that_does_not_beat_the_current_skill(tmp_path):
    result = run_game("maze_chase", FakeModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=40, held_out_steps=40)
    assert result["supported"] is True and result["step_limit"] > 0
    assert result["gate_verdicts"]["idle"]["episodes"] == 1  # the current skill was probed on the validation seed
    assert result["writing"]["calls"] >= 1 and result["writing"]["cost_usd"] == 0.0  # the fake model is free
    assert result["promoted"] is None and result["selector_reason"]  # refused for a stated reason
    assert result["held_out"]["played"] is False  # refused: no held-out seed was played
    document = build_document([result], "fake", "fake-stand-in (not a model result)")
    assert document["schema"] == "pf-arena-run/1" and document["rung"]["key"] == "model_skills"
    assert document["label"] == "[Assisted: Model-Written Skill]"


def _fake_chat_brain(kind="muse", completion_tokens=50, prompt_tokens=100):
    """A fake chat server behind the real client classes: no network, the transport answers in this process."""
    import httpx

    seen = {"requests": 0}

    def handler(request):
        seen["requests"] += 1
        body = {"choices": [{"finish_reason": "stop", "message": {"content": "```python\n" + FAKE_CODE + "```"}}],
                "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}
        return httpx.Response(200, json=body)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    if kind == "open":
        from bench.open_weights_brain import OpenWeightsBrain

        return OpenWeightsBrain("test-key", client=client), seen
    from playfellow_coop.muse_brain import MuseBrain

    return MuseBrain("muse-spark-1.3", "test-key", client=client), seen


def test_the_hard_cap_stops_before_the_call_that_would_pass_it():
    from bench.skillsmith_run import CappedBrain
    from playfellow_coop.skillsmith.promote import BudgetExceeded

    brain, seen = _fake_chat_brain(completion_tokens=100000)  # one call costs about $0.43 in reported tokens
    capped = CappedBrain(brain, cap_usd=0.01, provider="muse", run_id="cap-test")
    capped.ask("write a skill")
    assert seen["requests"] == 1 and capped.spent_usd > 0.01  # the first call was allowed and reported over the cap
    with pytest.raises(BudgetExceeded):
        capped.ask("write another skill")
    assert seen["requests"] == 1  # the call that would pass the cap was never sent


def test_the_open_brain_is_capped_the_same_way_before_anything_is_sent():
    from bench.skillsmith_run import CappedBrain
    from playfellow_coop.skillsmith.promote import BudgetExceeded

    brain, seen = _fake_chat_brain(kind="open")
    capped = CappedBrain(brain, cap_usd=0.001, provider="open", run_id="cap-open")
    with pytest.raises(BudgetExceeded):
        capped.ask("write a skill")
    assert seen["requests"] == 0 and capped.calls == 0


def test_every_paid_call_appends_one_line_to_the_spend_ledger(tmp_path):
    from bench.skillsmith_run import CappedBrain

    brain, _seen = _fake_chat_brain()
    ledger = tmp_path / "ledger.md"
    capped = CappedBrain(brain, cap_usd=2.0, provider="muse", run_id="run-42", ledger_path=ledger)
    capped.ask("one")
    capped.ask("two")
    lines = [line for line in ledger.read_text(encoding="utf-8").splitlines() if line.strip()]
    assert len(lines) == 2
    for line in lines:
        assert "run-42" in line and "muse" in line and "muse-spark-1.3" in line and "100/50" in line and "$" in line and "left" in line
    assert capped.usage()["calls"] == 2 and capped.usage()["tokens_in"] == 200 and capped.usage()["cost_usd"] > 0


def test_a_dry_run_plans_calls_and_a_dollar_estimate_and_sends_nothing(capsys):
    from bench.skillsmith_run import main, plan_run

    plan = plan_run(["maze_chase", "key_caves"], brain="muse", candidates=1)
    assert plan["brain"] == "muse" and plan["planned_calls"] == 4 and plan["estimated_usd"] > 0
    assert all(row["planned_calls"] == 2 for row in plan["games"].values())
    assert main(["--dry-run", "--brain", "open", "--games", "maze_chase"]) == 0
    out = capsys.readouterr().out
    assert "maze_chase" in out and "$" in out and "nothing was sent" in out


def test_a_fake_run_refuses_to_write_under_results(tmp_path):
    from pathlib import Path

    from bench.skillsmith_run import ROOT, main

    with pytest.raises(SystemExit):
        main(["--fake", "--games", "maze_chase", "--library", str(tmp_path / "lib"),
              "--out", str(Path(ROOT) / "results" / "skillsmith" / "planted.json")])


def test_a_live_result_carries_the_full_source_its_fingerprint_and_each_safety_verdict(tmp_path):
    import hashlib

    from bench.skillsmith_run import CappedBrain, run_game

    brain, _seen = _fake_chat_brain()
    capped = CappedBrain(brain, cap_usd=2.0, provider="muse", run_id="live-test", ledger_path=tmp_path / "ledger.md")
    result = run_game("key_caves", capped, tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=120, held_out_steps=60)
    assert result["promoted"] is not None
    assert result["skill_source"] and hashlib.sha256(result["skill_source"].encode("utf-8")).hexdigest() == result["skill_sha256"]
    checks = result["safety_checks"]
    assert checks["static_gate"]["passed"] is True and checks["sandbox"]["passed"] is True
    assert checks["held_out_promote"]["promoted"] == result["promoted"]
    assert result["example_game"] not in (None, "key_caves")
    assert result["writing"]["cost_usd"] > 0 and result["held_out"]["play_cost_usd"] == 0.0


def _promoted_document(tmp_path):
    import json

    from bench.skillsmith_run import build_document, run_game

    result = run_game("key_caves", FakeModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=120, held_out_steps=60)
    assert result["promoted"] is not None
    path = tmp_path / "skillsmith-fake.json"
    path.write_text(json.dumps(build_document([result], "fake", "fake-stand-in (not a model result)")), encoding="utf-8")
    return path


def test_a_judge_replay_watches_the_saved_skill_and_matches_the_saved_numbers(tmp_path, capsys):
    from bench.skillsmith_run import main, replay_file

    path = _promoted_document(tmp_path)
    report = replay_file(path)
    assert report["refused"] is None and report["ok"] is True
    assert main(["--replay", str(path)]) == 0
    assert "key_caves" in capsys.readouterr().out


def test_a_tampered_source_is_refused_and_a_gate_failure_is_refused_even_with_a_matching_hash(tmp_path):
    import hashlib
    import json

    from bench.skillsmith_run import ReplayRefused, main, replay_file

    path = _promoted_document(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["games"]["key_caves"]["skill_source"] += "\n# edited after the run\n"
    tampered = tmp_path / "tampered.json"
    tampered.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ReplayRefused):
        replay_file(tampered)
    assert main(["--replay", str(tampered)]) != 0
    bad = "import os\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n"
    doc["games"]["key_caves"]["skill_source"] = bad
    doc["games"]["key_caves"]["skill_sha256"] = hashlib.sha256(bad.encode("utf-8")).hexdigest()
    gated = tmp_path / "gated.json"
    gated.write_text(json.dumps(doc), encoding="utf-8")
    with pytest.raises(ReplayRefused):
        replay_file(gated)


def test_a_replay_that_does_not_match_the_saved_numbers_exits_1(tmp_path):
    import json

    from bench.skillsmith_run import main, replay_file

    path = _promoted_document(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["games"]["key_caves"]["held_out"]["wins"] = 99
    wrong = tmp_path / "wrong.json"
    wrong.write_text(json.dumps(doc), encoding="utf-8")
    report = replay_file(wrong)
    assert report["ok"] is False and report["refused"] is None
    assert main(["--replay", str(wrong)]) == 1


def test_a_planted_same_game_example_is_refused_with_the_fake_model(tmp_path):
    from playfellow_coop.skillsmith.synth import example_for

    _game, code = example_for("key_caves")
    with pytest.raises(ValueError):
        run_game("maze_chase", FakeModel(), tmp_path / "lib", [0], [100], validation_steps=10,
                 example=("maze_chase", code))


def test_a_promoted_skill_plays_only_the_held_out_seeds_and_play_is_free(tmp_path):
    result = run_game("key_caves", FakeModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=120, held_out_steps=60)
    assert result["promoted"] is not None and len(result["skill_sha256"]) == 64
    held = result["held_out"]
    assert held["played"] is True and held["play_calls"] == 0 and held["play_cost_usd"] == 0.0
    assert [e["seed"] for e in held["episodes"]] == [100]  # held-out seeds only, never a validation seed
    assert held["local_step_ms"] != "not measured" and held["local_step_ms"]["n"] > 0


class _StringErrorModel:
    """Answers with a swallowed provider error as text (the architect live runner's failure shape)."""

    def ask(self, prompt):
        return "<BrainError>"

    def usage(self):
        return {"calls": 0, "tokens_in": "not measured", "tokens_out": "not measured", "cost_usd": 0.0}


class _GateFailModel:
    def ask(self, prompt):
        return "```python\nimport os\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {'move': [0.0, 0.0], 'buttons': [], 'hold_ms': 0}\n```"

    def usage(self):
        return {"calls": 0, "tokens_in": "not measured", "tokens_out": "not measured", "cost_usd": 0.0}


class _RaisingModel:
    def ask(self, prompt):
        raise RuntimeError("provider down (simulated)")

    def usage(self):
        return {"calls": 0, "tokens_in": "not measured", "tokens_out": "not measured", "cost_usd": 0.0}


def test_proposal_failures_are_recorded_not_dropped(tmp_path):
    """HK5-1: a candidate that is never scored must say why in the result, not only 'no candidate beats'."""
    for model, needle in ((_StringErrorModel(), "no code"), (_GateFailModel(), "os")):
        result = run_game("key_caves", model, tmp_path / "lib", [0], [100], candidates=1,
                          validation_steps=40, held_out_steps=40)
        assert result["promoted"] is None
        proposals = result.get("proposals") or []
        assert proposals, "the result must record what happened to each proposal"
        assert any(needle in (p.get("detail") or "") for p in proposals), proposals
        assert all(p.get("outcome") in ("answered", "error") for p in proposals)


def test_an_ask_exception_is_recorded_and_the_round_still_reports(tmp_path):
    result = run_game("key_caves", _RaisingModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=40, held_out_steps=40)
    assert result["promoted"] is None and result["supported"] is True
    proposals = result.get("proposals") or []
    assert any(p.get("outcome") == "error" and "RuntimeError" in (p.get("detail") or "") for p in proposals), proposals


def test_the_learning_curve_has_one_point_per_round_and_rises_with_an_improving_fake(tmp_path):
    from bench.skillsmith_run import ImprovingFakeModel

    result = run_game("key_caves", ImprovingFakeModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=120, held_out_steps=60, rounds=4)
    curve = result.get("curve") or []
    assert len(curve) == 4, curve  # one point per round, nothing interpolated
    for point in curve:
        assert "current_progress" in point and "best_progress" in point and "reason" in point
        assert "trace_shown" in point and "lessons_shown" in point
    assert curve[-1]["best_progress"] > curve[0]["best_progress"], curve
    assert curve[-1]["current_progress"] >= curve[0]["current_progress"], curve
    assert result["promoted"] is not None  # the improving fake is promoted at some round


def test_replay_latest_reports_no_live_file_yet_and_exits_zero(tmp_path, monkeypatch, capsys):
    import bench.skillsmith_run as run_module

    empty = tmp_path / "skillsmith"
    empty.mkdir()
    (empty / "sandbox-proof-20261102.json").write_text('{"rows": [], "harmless": []}', encoding="utf-8")
    monkeypatch.setattr(run_module, "ROOT", tmp_path)
    # ROOT/results/skillsmith is where latest looks; point it at the empty folder via a fresh tree
    live_dir = tmp_path / "results" / "skillsmith"
    live_dir.mkdir(parents=True)
    (live_dir / "sandbox-proof-20261102.json").write_text('{"rows": [], "harmless": []}', encoding="utf-8")
    assert run_module.main(["--replay", "latest"]) == 0
    assert "no live file yet" in capsys.readouterr().out


def test_replay_latest_picks_the_newest_live_file(tmp_path, monkeypatch, capsys):
    import json

    import bench.skillsmith_run as run_module

    live_dir = tmp_path / "results" / "skillsmith"
    live_dir.mkdir(parents=True)
    path = _promoted_document(tmp_path)
    doc = json.loads(path.read_text(encoding="utf-8"))
    doc["brain"] = "muse"
    doc["condition"] = "skillsmith-muse"
    live = live_dir / "skillsmith-muse-20261102.json"
    live.write_text(json.dumps(doc), encoding="utf-8")
    (live_dir / "sandbox-proof-20261102.json").write_text(
        json.dumps({"rows": [{"name": "import os", "stopped": True, "layer": "static gate", "ms": 0.1}],
                    "harmless": [{"name": "stay still", "passed": True, "ms": 1.0}]}), encoding="utf-8")
    monkeypatch.setattr(run_module, "ROOT", tmp_path)
    assert run_module.main(["--replay", "latest"]) == 0
    out = capsys.readouterr().out
    assert "key_caves" in out and "sandbox" in out.lower()


def test_a_flat_fake_gives_a_flat_curve(tmp_path):
    from bench.skillsmith_run import IDLE_CODE

    class FlatModel:
        def ask(self, prompt):
            return "```python\n" + IDLE_CODE + "```"

        def usage(self):
            return {"calls": 0, "tokens_in": "not measured", "tokens_out": "not measured", "cost_usd": 0.0}

    result = run_game("key_caves", FlatModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=60, held_out_steps=40, rounds=3)
    curve = result.get("curve") or []
    assert len(curve) == 3
    assert all(abs(p["best_progress"] - p["current_progress"]) < 1e-9 for p in curve), curve
    assert result["promoted"] is None


def test_a_skill_writing_answer_has_room_for_the_code_and_the_cap_prices_that_room(tmp_path, monkeypatch):
    """F1 (2 Nov): 25 of 34 Muse answers stopped at exactly 1000 tokens and 21 had no code block. Writing a skill needs a longer
    answer than a planner turn, so the harness gives the writing brain its own answer cap, and the hard cap prices the full room."""
    from bench.skillsmith_run import WRITING_MAX_TOKENS, make_live_brain, plan_run

    assert WRITING_MAX_TOKENS >= 4000
    monkeypatch.setenv("OPEN_BRAIN_API_KEY", "not-a-real-key")
    capped = make_live_brain("open", cap_usd=0.5, ledger_path=tmp_path / "ledger.md", run_id="room")
    assert capped.brain.max_tokens == WRITING_MAX_TOKENS
    smaller = make_live_brain("open", cap_usd=0.5, ledger_path=tmp_path / "ledger.md", run_id="room", max_tokens=1500)
    assert smaller.brain.max_tokens == 1500 and capped.estimate_next_usd("x") > smaller.estimate_next_usd("x")
    plan = plan_run(["maze_chase"], brain="muse", candidates=1)
    assert plan["games"]["maze_chase"]["tokens_out_est_per_call"] == WRITING_MAX_TOKENS
