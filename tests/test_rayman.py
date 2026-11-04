"""Rayman Legends pre-skills: key recipes and goal arithmetic, without the game."""
import pytest

from playfellow_coop.games.rayman import rules


def test_every_move_has_a_recipe_of_known_keys():
    known = set(rules.KEYS.values())
    for move in ("short_jump", "full_jump", "hover", "run", "dash_attack", "jump_cancel_dash", "crush", "roll_jump", "wall_jump", "charged_punch", "murfy"):
        steps = rules.recipe(move)
        assert steps and all(step.keys <= known and step.seconds > 0 for step in steps), move


def test_moves_turn_with_the_facing():
    assert "left" in rules.recipe("run", "left")[0].keys
    assert "left" in rules.recipe("wall_jump", "right")[1].keys  # off the wall, away from it


def test_hover_is_jump_held_and_crush_is_down_and_attack():
    assert rules.recipe("hover")[1].seconds > 1.0 and "space" in rules.recipe("hover")[1].keys
    assert {"down", "s"} <= rules.recipe("crush")[1].keys


def test_unknown_move_is_refused():
    with pytest.raises(KeyError):
        rules.recipe("teleport")


def test_cups_on_a_600_level():
    assert rules.cup_targets(600) == {"bronze": 150, "silver": 300, "ticket": 450, "gold": 600}
    assert rules.cup_for(449, 600) == "silver" and rules.cup_for(600, 600) == "gold" and rules.cup_for(10, 600) == "none"


def test_invaded_levels_save_a_teensy_per_rocket_not_yet_launched():
    assert rules.invaded_saved(39.0) == 3
    assert rules.invaded_saved(45.0) == 2
    assert rules.invaded_saved(61.0) == 0


def test_unlocks_and_next_goal():
    assert rules.unlocked_princesses(60) == 4
    assert rules.next_goal(20) == "free 15 more Teensies for the next princess"
    assert rules.next_goal(300) == "free 100 more Teensies to open Living Dead Party"
    assert rules.teensies_per_level("regular") == 10 and rules.teensies_per_level("invaded") == 3
