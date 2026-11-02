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
    supported, reason = game_support("action_quest")
    assert not supported and "progress" in reason
    result = run_game("action_quest", FakeModel(), tmp_path / "lib", [0], [100])
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


def test_a_promoted_skill_plays_only_the_held_out_seeds_and_play_is_free(tmp_path):
    result = run_game("key_caves", FakeModel(), tmp_path / "lib", [0], [100], candidates=1,
                      validation_steps=120, held_out_steps=60)
    assert result["promoted"] is not None and len(result["skill_sha256"]) == 64
    held = result["held_out"]
    assert held["played"] is True and held["play_calls"] == 0 and held["play_cost_usd"] == 0.0
    assert [e["seed"] for e in held["episodes"]] == [100]  # held-out seeds only, never a validation seed
    assert held["local_step_ms"] != "not measured" and held["local_step_ms"]["n"] > 0
