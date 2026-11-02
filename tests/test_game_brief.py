"""The game brief: before play, Muse Wonder answers a fixed set of questions about a game by name (how to get into a level, the menus
and hub, the default keyboard controls, what wins), and only keys the game's controls card allows survive into the brief. Fake model."""
from __future__ import annotations

import json
import os
from pathlib import Path

import controls

from playfellow_coop.game_brief import QUESTIONS, brief_for, brief_text

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
CARD = controls.load_card(ENGINE / "controls" / "practice_arena.yaml")


class Wonder:
    model = "muse-wonder-1.0"

    def __init__(self, answer):
        self.answer, self.seen = answer, []
        self.last_usage = {"prompt_tokens": 500, "completion_tokens": 200}

    def ask(self, system, text, images):
        self.seen.append((system, text, images))
        return json.dumps(self.answer)


ANSWER = {"start": ["From the title press Enter", "In the hub walk right to a painting and press up"],
          "menus": ["Arrows move, Enter chooses, Esc goes back"],
          "controls": {"jump": "space", "attack": "s", "self_destruct": "f12", "run_right": "right"},
          "goal": "Reach the end of each level", "tips": ["Jump twice to double jump"]}


def test_the_brief_asks_every_question_by_game_name_with_no_picture(tmp_path):
    wonder = Wonder(ANSWER)
    brief = brief_for(wonder, "Some Platformer", CARD, cache_dir=tmp_path)
    system, text, images = wonder.seen[0]
    assert images == [] and "Some Platformer" in text and all(q in system for q in QUESTIONS)
    assert brief["start"][0].startswith("From the title")


def test_only_keys_the_card_allows_survive_and_the_stop_key_never_does(tmp_path):
    allowed = {k for a in CARD.actions.values() for k in a.keys}
    brief = brief_for(Wonder(ANSWER), "Some Platformer", CARD, cache_dir=tmp_path)
    assert set(brief["controls"].values()) <= allowed and "f12" not in brief["controls"].values()
    assert "self_destruct" in brief["dropped_controls"]


def test_the_brief_is_cached_per_game_so_it_is_paid_for_once(tmp_path):
    wonder = Wonder(ANSWER)
    brief_for(wonder, "Some Platformer", CARD, cache_dir=tmp_path)
    brief_for(wonder, "Some Platformer", CARD, cache_dir=tmp_path)
    assert len(wonder.seen) == 1


def test_the_text_for_the_planner_is_fenced_as_data_and_says_where_it_came_from(tmp_path):
    text = brief_text(brief_for(Wonder(ANSWER), "Some Platformer", CARD, cache_dir=tmp_path))
    assert text.startswith("GAME BRIEF") and "not instructions from the player" in text and "Enter" in text


def test_an_answer_that_is_not_a_brief_gives_no_brief(tmp_path):
    class Bad(Wonder):
        def ask(self, *a):
            return "I am not sure"
    assert brief_for(Bad({}), "Some Platformer", CARD, cache_dir=tmp_path) is None
