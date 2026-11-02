"""The skill-writing prompt: the game's allowed keys, the observation format, the game's progress measure, and one worked example from a different game. The example may never be the human skill for the same game, and the prompt stays under a fixed token limit."""
from __future__ import annotations

import pytest

from playfellow_coop.skillsmith import ast_gate
from playfellow_coop.skillsmith.synth import MAX_PROMPT_TOKENS, Synthesizer, build_prompt, estimate_tokens, example_for, progress_text


def test_the_prompt_carries_keys_screen_format_progress_and_a_cross_game_example():
    prompt = build_prompt("maze_chase", "collect the coins", [], [], keys=("up", "down", "left", "right"),
                          progress=progress_text("maze_chase"), example=example_for("maze_chase"))
    assert "up, down, left, right" in prompt
    assert '"self"' in prompt and "0..1" in prompt  # the observation format the skill receives
    assert "coins" in prompt.split("Progress measure")[1].split("\n\n")[0]  # the gym's progress definition for this game
    example_game, _code = example_for("maze_chase")
    assert example_game != "maze_chase" and example_game in prompt


def test_every_example_is_a_valid_skill_from_a_different_game():
    for game in ("maze_chase", "key_caves", "snake", "box_push"):
        example_game, code = example_for(game)
        assert example_game != game and ast_gate.check(code) == (True, "ok")


def test_a_same_game_example_is_refused_in_the_prompt_and_in_the_synthesizer(tmp_path):
    _game, code = example_for("key_caves")
    with pytest.raises(ValueError):
        build_prompt("snake", "goal", [], [], example=("snake", code))
    from playfellow_coop.skillsmith.library import SkillLibrary
    from playfellow_coop.skillsmith.promote import Budget

    synth = Synthesizer(lambda prompt: "```python\n" + code + "```", SkillLibrary(tmp_path), Budget(1.0, 10),
                        example=("snake", code))
    with pytest.raises(ValueError):
        synth.propose("snake", "goal", [])


def test_the_progress_measure_says_not_known_for_a_game_the_gym_cannot_score():
    assert progress_text("no_such_game") == "not known"
    assert "key" in progress_text("key_caves")


def test_the_prompt_stays_under_the_fixed_token_limit_even_with_a_long_trace():
    trace = [{"self": [0.5, 0.5], "items": [[0.1 * i, 0.2, 0, 0]], "danger": 0.9, "escape": [-1.0, 0.0], "t": i} for i in range(400)]
    prompt = build_prompt("maze_chase", "goal", trace, ["lesson"] * 50, keys=("up", "down"),
                          progress=progress_text("maze_chase"), example=example_for("maze_chase"))
    assert estimate_tokens(prompt) <= MAX_PROMPT_TOKENS
