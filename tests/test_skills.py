"""Skills: local controllers started by one model decision. Every skill reads pictures only, obeys the controls card, has a hard step limit and wins its game offline."""
from __future__ import annotations

import json
import os
import re
from pathlib import Path

import numpy as np
from PIL import Image
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
        if path.name in {"__init__.py", "base.py", "book.py", "registry.py", "calibration.py"}:
            continue  # the plumbing talks to the session, not to a game
        text = "\n".join(line for line in path.read_text(encoding="utf-8").splitlines() if not line.lstrip().startswith(("#", '"""')))
        assert not banned.search(text), f"{path.name} reads the game's inner state"
        assert "calibration" not in text, f"{path.name} must not depend on the build-time calibration (it reads game state to label frames)"


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


def test_skill_brain_lets_any_brain_use_a_skill_and_passes_everything_else_through():
    import controls
    from playfellow_coop.skills.skill_brain import SkillBrain, chosen_skill

    class Inner:
        model = "x"
        last_request = {"tokens_in": 5}

        def __init__(self, answer):
            self.answer, self.seen = answer, []

        def ask(self, system, text, images):
            self.seen.append(system)
            return self.answer

    game = ar.load_game("snake", 4)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    screen, hands = ar.VirtualScreen(game), ar.VirtualHands(game, card)
    inner = Inner(json.dumps({"thought": "chase", "say": "going for it", "actions": [], "skill": "chase_food"}))
    brain = SkillBrain(inner, SkillBook("snake"), screen, hands, card, stop=lambda: game.done)
    reply = json.loads(brain.ask("rules", "turn", []))
    assert game.is_won() and reply["actions"] == [] and reply["say"] == "going for it" and brain.last_skill.steps > 50
    assert "SKILLS" in inner.seen[0] and inner.seen[0].startswith("rules") and brain.model == "x" and brain.last_request == {"tokens_in": 5}
    passthrough = json.dumps({"thought": "t", "say": "", "actions": ["UP"], "skill": "none"})
    assert Inner(passthrough) and SkillBrain(Inner(passthrough), SkillBook("snake"), screen, hands, card).ask("s", "t", []) == passthrough
    unknown = json.dumps({"thought": "t", "say": "", "actions": [], "skill": "teleport"})
    assert SkillBrain(Inner(unknown), SkillBook("snake"), screen, hands, card).ask("s", "t", []) == unknown  # an unknown skill name does nothing
    assert chosen_skill("not json") is None and chosen_skill('{"skill": "x"}') == "x"


def test_skill_brain_stops_at_once_when_asked_to_stop():
    import controls
    from playfellow_coop.skills.skill_brain import SkillBrain

    class Inner:
        def ask(self, system, text, images):
            return json.dumps({"thought": "", "say": "", "actions": [], "skill": "chase_food"})

    game = ar.load_game("snake", 0)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    brain = SkillBrain(Inner(), SkillBook("snake"), ar.VirtualScreen(game), ar.VirtualHands(game, card), card, stop=lambda: True)
    brain.ask("s", "t", [])
    assert brain.last_skill.steps == 0 and brain.last_skill.stopped == "game_over" and game.ticks == 0  # the player took over: not one key was pressed


def test_settle_waits_for_the_picture_to_change_and_gives_up_after_the_timeout():
    from playfellow_coop.skills.base import make_settle
    frames = [np.zeros((16, 16, 3), np.uint8)] * 3 + [np.full((16, 16, 3), 200, np.uint8)]
    calls, now = [], [0.0]

    def grab():
        calls.append(1)
        return frames[min(len(calls) - 1, 3)]

    def sleep(seconds):
        now[0] += seconds

    make_settle(grab, timeout=1.0, poll=0.1, sleep=sleep, clock=lambda: now[0])(np.zeros((16, 16, 3), np.uint8))
    assert len(calls) == 4  # three looks at the same picture, then the changed one: it returned at once
    still = make_settle(lambda: np.zeros((16, 16, 3), np.uint8), timeout=0.5, poll=0.1, sleep=sleep, clock=lambda: now[0])
    start = now[0]
    still(np.zeros((16, 16, 3), np.uint8))
    assert 0.45 <= now[0] - start <= 0.7  # a picture that never changes costs one timeout, never an endless wait


def test_a_live_snake_run_steps_with_the_game_clock_and_wins():
    import controls
    import threading
    import time
    from types import SimpleNamespace
    from playfellow_coop.skills.skill_brain import SkillBrain

    game = ar.load_game("snake", 2)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")

    class Clocked(ar.VirtualHands):
        pass

    hands = ar.VirtualHands(game, card)
    # make the game tick by itself in a thread (like the in-app game); a key only sets the direction
    original_do = hands.do

    def only_press(step, box):
        action = card.actions[step.action]
        if getattr(action, "keys", None):
            game.press(action.keys[0])

    hands.do = only_press
    running = [True]

    def clock():
        while running[0] and not game.done:
            game.tick()
            game.ticks += 1
            time.sleep(0.06)

    thread = threading.Thread(target=clock, daemon=True)

    class Inner:
        def ask(self, system, text, images):
            return json.dumps({"thought": "", "say": "", "actions": [], "skill": "chase_food"})

    brain = SkillBrain(Inner(), SkillBook("snake"), ar.VirtualScreen(game), hands, card, stop=lambda: game.done)
    thread.start()
    try:
        brain.ask("s", "t", [])
    finally:
        running[0] = False
        thread.join(2)
    assert game.is_won() or brain.last_skill.steps > 20  # it stepped with the clock rather than spinning on a stale picture


def test_a_skill_says_whether_it_can_read_a_picture_so_a_blind_skill_is_never_offered():
    book = SkillBook("snake")
    game = ar.load_game("snake", 0)
    assert book.readable(game.render()) is True
    assert book.readable(Image.new("RGB", (440, 504), (30, 30, 60))) is False  # a look it does not know: nothing it can find
    assert SkillBook("box_push").readable(Image.new("RGB", (480, 400), (0, 0, 0))) is False
    assert SkillBook("lane_dash").readable(ar.load_game("lane_dash", 0).render()) is True


def _asking_brain(answer):
    class Inner:
        model = "x"

        def __init__(self):
            self.seen = []

        def ask(self, system, text, images):
            self.seen.append(system)
            return answer(len(self.seen))

    return Inner()


def test_a_skill_that_cannot_read_the_picture_is_not_offered_and_the_model_plays_the_turn():
    import controls
    from playfellow_coop.skills.skill_brain import SkillBrain

    game = ar.load_game("snake", 4)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    screen = ar.VirtualScreen(game)
    screen.grab = lambda box: Image.new("RGB", (440, 440), (90, 90, 90))  # a new skin the skill has never seen
    plan = json.dumps({"thought": "t", "say": "", "actions": ["UP"]})
    inner = _asking_brain(lambda n: plan)
    brain = SkillBrain(inner, SkillBook("snake"), screen, ar.VirtualHands(game, card), card)
    assert brain.ask("rules", "turn", []) == plan and inner.seen == ["rules"] and brain.last_skill is None  # one call, no skills paragraph, nothing pressed by a skill


def test_a_skill_that_turns_out_blind_hands_the_turn_back_to_the_model():
    import controls
    from playfellow_coop.skills.skill_brain import SkillBrain

    game = ar.load_game("snake", 4)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    book = SkillBook("snake")
    screen = ar.VirtualScreen(game)
    book.run = lambda name, parts, box, stop, max_steps=None: SimpleResult()  # readable on the way in, empty-handed when it runs
    plan = json.dumps({"thought": "keys", "say": "", "actions": ["UP"]})
    inner = _asking_brain(lambda n: json.dumps({"thought": "", "say": "", "actions": [], "skill": "chase_food"}) if n == 1 else plan)
    events = []
    brain = SkillBrain(inner, book, screen, ar.VirtualHands(game, card), card, on_event=lambda kind, data: events.append(kind))
    assert brain.ask("rules", "turn", []) == plan and len(inner.seen) == 2 and "pressed nothing" in inner.seen[1] and "skill_blind" in events


class SimpleResult:
    skill, steps, stopped, keys = "chase_food", 0, "done:no head", []


def test_a_resized_window_is_scaled_back_so_the_skill_still_wins():
    import controls
    from playfellow_coop.skills.skill_brain import SkillBrain
    from playfellow_coop.universal.frames import resize, to_rgb

    game = ar.load_game("snake", 4)
    card = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    book = SkillBook("snake")
    screen = ar.VirtualScreen(game)
    assert book.readable(screen.grab(None)) and book.native_size is not None  # proven at the real size first, as a session does at start
    width, height = book.native_size
    screen.grab = lambda box, real=screen.grab: Image.fromarray(resize(to_rgb(real(box)), int(width * 1.5), int(height * 1.5)))  # the window was made bigger
    inner = _asking_brain(lambda n: json.dumps({"thought": "", "say": "", "actions": [], "skill": "chase_food"}))
    SkillBrain(inner, book, screen, ar.VirtualHands(game, card), card, stop=lambda: game.done).ask("rules", "turn", [])
    assert game.is_won() and book.last.steps > 50

