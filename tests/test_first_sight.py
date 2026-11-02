"""First sight: Muse Wonder looks at a game it has never seen and drafts how to play it; the engine's own card rules check the draft; a probe
presses each drafted key once and keeps only the keys that change the picture; the result is scored against the game's real card.
Fake model; the probe runs on a real arena game, in memory (no window, no key)."""
from __future__ import annotations

import json
import os
from pathlib import Path

import numpy as np
import pytest

import controls
from bench import arena_run as ar
from playfellow_coop.first_sight import FirstSightError, draft_card, key_recall, probe

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


class Wonder:
    model = "muse-wonder-1.0"

    def __init__(self, answer):
        self.answer, self.seen = answer, []
        self.last_usage = {"prompt_tokens": 2000, "completion_tokens": 300}

    def ask(self, system, text, images):
        self.seen.append((system, text, len(images)))
        return self.answer if isinstance(self.answer, str) else json.dumps(self.answer)


DRAFT = {"genre": "maze", "goal": "collect the coins, take the key, reach the door",
         "actions": [{"name": "UP", "keys": "up", "says": "walk up"}, {"name": "DOWN", "keys": "down", "says": "walk down"},
                     {"name": "LEFT", "keys": "left", "says": "walk left"}, {"name": "RIGHT", "keys": "right", "says": "walk right"},
                     {"name": "JUMP", "keys": "space", "says": "jump"}]}


def _frames(n=3):
    game = ar.load_game("maze_chase", 0)
    return [game.render() for _ in range(n)]


def test_the_draft_becomes_a_card_the_engine_itself_accepts_and_the_model_saw_only_pictures_and_the_title():
    wonder = Wonder(DRAFT)
    card, info = draft_card(wonder, _frames(), "Maze Chase")
    assert isinstance(card, controls.ControlsCard) and set(card.actions) == {"UP", "DOWN", "LEFT", "RIGHT", "JUMP"}
    assert card.genre == "maze" and info["cost_usd"] > 0
    assert wonder.seen[0][2] == 3 and "Maze Chase" in wonder.seen[0][1]


@pytest.mark.parametrize("bad", ["f12", "f9", "not-a-key"])
def test_a_draft_that_uses_the_stop_key_the_take_over_key_or_an_unknown_key_is_refused_by_the_engines_own_rules(bad):
    answer = dict(DRAFT, actions=DRAFT["actions"] + [{"name": "BAD", "keys": bad, "says": "x"}])
    with pytest.raises(FirstSightError):
        draft_card(Wonder(answer), _frames(), "Maze Chase")


def test_an_answer_that_is_not_a_plan_is_refused_plainly():
    with pytest.raises(FirstSightError):
        draft_card(Wonder("I think you press arrows"), _frames(), "Maze Chase")


def test_the_probe_keeps_only_the_keys_that_change_the_picture_on_a_real_game():
    card, _ = draft_card(Wonder(DRAFT), _frames(), "Maze Chase")
    game = ar.load_game("maze_chase", 0)
    pressed = []

    def press(key):
        pressed.append(key)
        game.step(key)

    learned, report = probe(card, press, lambda: np.asarray(game.render().convert("RGB")), idle=lambda: game.step(None))
    assert "JUMP" not in learned.actions  # maze chase has no space key: pressing it changes nothing
    assert {"LEFT", "RIGHT", "UP", "DOWN"} & set(learned.actions)
    assert set(pressed) <= {"up", "down", "left", "right", "space"}  # only drafted keys, each tried
    assert report["JUMP"]["changed"] is False


def test_recall_against_the_real_card():
    real = controls.load_card(ENGINE / "controls" / "arena_maze_chase.yaml")
    card, _ = draft_card(Wonder(DRAFT), _frames(), "Maze Chase")
    assert key_recall(card, real) == 1.0
    half = dict(DRAFT, actions=DRAFT["actions"][:2])
    assert key_recall(draft_card(Wonder(half), _frames(), "Maze Chase")[0], real) == 0.5
