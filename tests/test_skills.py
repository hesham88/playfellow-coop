"""Skills: local controllers started by one model decision. Every skill reads pictures only, obeys the controls card, has a hard step limit and wins its game offline."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
import pytest

from bench import arena_run as ar
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.skills import SKILLS, run_skill, skill_for_game
from playfellow_coop.skills import paddle_track
from playfellow_coop.skills.base import Done
from playfellow_coop.skills.book import NONE, SkillBook

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
SKILL_DIR = Path(__file__).resolve().parents[1] / "playfellow_coop" / "skills"


def play(game_key, seed, limit=None):
    game = ar.load_game(game_key, seed)
    skill = skill_for_game(game_key)
    result = run_skill(skill, game.render, lambda key: game.step(key), lambda: game.done, set(game.keys), max_steps=limit)
    return game, result


def test_every_listed_game_has_exactly_one_skill_and_it_is_described_for_the_model():
    assert set(SKILLS) == {"snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"}
    for key in SKILLS:
        skill = skill_for_game(key)
        assert re.fullmatch(r"[a-z_]+", skill.name) and len(skill.about) > 30 and skill.max_steps >= 30


def test_no_skill_looks_inside_the_game_it_reads_pixels_only():
    banned = re.compile(r"arena_pack|\.progress\(|\.is_won\(|\.is_lost\(|\bgame\.[a-z_]|self\.game\b")
    for path in SKILL_DIR.glob("*.py"):
        if path.name in {"__init__.py", "base.py", "book.py", "registry.py"}:
            continue  # the plumbing talks to the session, not to a game
        text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("#", '"""')))
        assert not banned.search(text), f"{path.name} reads the game's inner state"


@pytest.mark.parametrize("game_key, seeds", [("snake", 8), ("slide_2048", 3), ("box_push", 3)])
def test_a_skill_wins_its_game_from_the_picture_alone(game_key, seeds):
    for seed in range(seeds):
        game, result = play(game_key, seed)
        assert game.is_won(), (game_key, seed, result.stopped, game.progress())
        assert result.steps <= skill_for_game(game_key).max_steps


def test_the_lane_runner_survives_sixty_seconds_and_collects_enough_coins():
    game, result = play("lane_dash", 0)
    assert game.is_won() and game.progress()["coins"] >= 30 and result.steps == 600


def test_the_paddle_follows_the_ball_launches_and_breaks_bricks():
    game, result = play("brick_breaker", 0, limit=900)
    progress = game.progress()
    assert progress["launched"] and progress["lives"] == 3 and progress["bricks_left"] < 32 and result.stopped == "step_limit"


def test_the_ball_landing_spot_folds_back_off_the_side_walls():
    assert paddle_track.landing_x(100.0, 100.0, 0.0, 6.0, 372.0) == pytest.approx(100.0)
    assert paddle_track.landing_x(470.0, 100.0, 6.0, 6.0, 372.0) < 470.0  # it goes out to the wall and comes back
    assert paddle_track.landing_x(240.0, 300.0, 3.0, -6.0, 372.0) == 240.0  # going up: it is not landing yet


def test_the_loop_stops_at_a_key_the_card_does_not_allow_and_never_presses_it():
    class Wild:
        name, about, max_steps = "wild", "x" * 40, 50

        def reset(self):
            pass

        def next_key(self, frame):
            return "delete"

    pressed = []
    result = run_skill(Wild(), lambda: np.zeros((4, 4, 3), np.uint8), pressed.append, lambda: False, {"left", "right"})
    assert result.stopped == "key_not_allowed:delete" and pressed == [] and result.steps == 0


def test_the_step_limit_is_hard_and_a_finished_skill_says_why():
    class Forever:
        name, about, max_steps = "forever", "y" * 40, 7

        def reset(self):
            pass

        def next_key(self, frame):
            return "left"

    pressed = []
    result = run_skill(Forever(), lambda: np.zeros((4, 4, 3), np.uint8), pressed.append, lambda: False, {"left"}, max_steps=1000)
    assert result.steps == 7 == len(pressed) and result.stopped == "step_limit"

    class Short(Forever):
        def next_key(self, frame):
            raise Done("all done")

    assert run_skill(Short(), lambda: np.zeros((4, 4, 3), np.uint8), pressed.append, lambda: False, {"left"}).stopped == "done:all done"


def test_a_game_that_is_over_stops_the_skill_before_any_key():
    game = ar.load_game("snake", 0)
    pressed = []
    result = run_skill(skill_for_game("snake"), game.render, pressed.append, lambda: True, set(game.keys))
    assert result.stopped == "game_over" and pressed == []


def test_the_book_tells_the_model_the_skill_and_the_answer_format_and_refuses_unknown_names():
    book = SkillBook("snake")
    text = book.system_text()
    assert "chase_food" in text and '"skill"' in text and NONE in text
    assert book.names == ("chase_food", NONE)
    assert book.run("teleport", parts=None, box=None, stop=lambda: False) is None
    with pytest.raises(KeyError):
        SkillBook("maze_chase")


def test_the_brain_schema_allows_exactly_the_skills_it_was_told_and_nothing_else():
    brain = MuseBrain("muse-spark-1.3", "k")
    brain.set_actions(("UP", "DOWN"))
    assert "skill" not in brain._schema()["json_schema"]["schema"]["properties"]
    brain.set_skills(("chase_food", NONE))
    schema = brain._schema()["json_schema"]["schema"]
    assert schema["properties"]["skill"]["enum"] == ["chase_food", NONE] and "skill" in schema["required"]


def test_one_scripted_decision_through_the_real_turn_loop_wins_with_no_invalid_plan():
    episode = ar.run_episode("snake", 0, ar.ScriptedChooser("chase_food"), max_turns=3, max_calls=3, engine_dir=ENGINE, skills=True)
    assert episode.won and episode.turns == 1 and episode.invalid_plans == 0 and episode.ended == "won"


def test_a_skill_lets_go_the_moment_the_player_takes_the_controls():
    from playfellow_coop import session

    class Parts:
        class safety:
            stopped = False

        class screen:
            @staticmethod
            def in_front(title):
                return True

        class handover:
            human_has_controls = True

    class Settings:
        game_window = "x"

    assert session._skill_must_stop(Parts, Settings) is True
    Parts.handover.human_has_controls = False
    assert session._skill_must_stop(Parts, Settings) is False
    Parts.safety.stopped = True
    assert session._skill_must_stop(Parts, Settings) is True


def test_the_harness_remembers_a_won_skill_run_tags_who_acted_and_shows_the_fact_next_time(tmp_path):
    first = ar.run_episode("snake", 0, ar.ScriptedChooser("chase_food"), max_turns=2, max_calls=2, engine_dir=ENGINE, skills=True, harness_dir=tmp_path)
    assert first.won and first.invalid_plans == 0
    from playfellow_coop.harness.runtime import Harness
    h = Harness(tmp_path, game="snake")
    facts = [f.text for f in h.bank.recall("snake")]
    assert any("chase_food won snake" in t for t in facts)
    skill_events = [e for e in h.session.events if e.kind == "skill"] or [e for s in h.session.store.sessions() for e in h.session.store.events(s) if e.kind == "skill"]
    assert skill_events and skill_events[0].who["agent"] == "skill:chase_food" and skill_events[0].who["player"] == "local"
    assert h.memory_block().startswith("<<<DATA") and "chase_food won snake" in h.memory_block()


def test_a_skill_that_does_nothing_ends_in_the_players_turn_with_a_spoken_line():
    from playfellow_coop import session
    from playfellow_coop.harness.runtime import Harness, HELP_LINE
    import tempfile

    class Idle:
        name, about, max_steps = "idle", "does nothing at all " * 3, 5

        def reset(self):
            pass

        def next_key(self, frame):
            return None

    game = ar.load_game("box_push", 0)
    taken, said = [], []

    class Hand:
        def take_over(self):
            taken.append(True)
            return True

    book = SkillBook("box_push")
    book.skill = Idle()

    class Parts:
        pass

    parts = Parts()
    from controls import load_card
    parts.card = load_card(ENGINE / "controls" / "arena_box_push.yaml")
    parts.screen, parts.hands = ar.VirtualScreen(game), ar.VirtualHands(game, parts.card)

    class Safety:
        stopped = False

    parts.safety = Safety()
    parts.skill_idle = lambda: None  # an idle skill presses nothing, and a puzzle does not move by itself, so the picture never changes
    book.name = "idle"
    with tempfile.TemporaryDirectory() as folder:
        harness = Harness(folder, game="box_push")
        run = lambda: book.run("idle", parts, None, lambda: False)  # noqa: E731
        outcome = harness.skill_flow(run, game.render, lambda: False).run()
    assert outcome.status == "help" and outcome.attempts == 2 and "did not change" in outcome.reason
    assert "your turn" in HELP_LINE
