"""The pace rule: in a game that runs on its own clock, one move per look leaves the player standing still while the model thinks
(owner run on 2 Nov: 31 of 31 planner turns chose exactly one action, about 2.5 s each). Real-time cards get a rule asking for a short
sequence and for the run skill on open stretches; turn-based cards get nothing extra."""
from __future__ import annotations

import os
from pathlib import Path

import controls
from playfellow_coop.pace import pace_rule

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


def test_a_platformer_is_asked_for_a_short_sequence_and_the_run_skill():
    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    rule = pace_rule(card, max_actions=4, skills=("run_and_jump",))
    assert "3 to 4 actions" in rule and "run_and_jump" in rule and "never just one" in rule


def test_without_a_skill_the_rule_names_no_skill_and_a_turn_based_game_gets_no_rule():
    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    assert "skill" not in pace_rule(card, max_actions=4, skills=())
    chess = next(c for c in (controls.load_card(p) for p in sorted((ENGINE / "controls").glob("*.yaml")))
                 if str(getattr(c, "genre", "")) in ("board", "puzzle", "strategy_turn"))
    assert pace_rule(chess, max_actions=4, skills=()) == ""


def test_a_limit_of_one_action_gets_no_sequence_rule():
    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    assert pace_rule(card, max_actions=1, skills=()) == ""


def test_the_buddy_adds_the_rule_to_the_play_instructions_for_a_real_time_card():
    from types import SimpleNamespace

    from playfellow_coop.__main__ import paced_text

    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    parts = SimpleNamespace(card=card, skills=SimpleNamespace(names=("run_and_jump",)))
    assert "run_and_jump" in paced_text(parts, SimpleNamespace(max_actions_per_step=4))
    assert paced_text(SimpleNamespace(card=card), SimpleNamespace(max_actions_per_step=4)).startswith("\n\nThis game runs in real time")
