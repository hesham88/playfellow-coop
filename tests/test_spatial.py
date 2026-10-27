"""The "your last move did nothing" note: said only when a direction key was pressed and ME did not move, from the marks alone."""
from __future__ import annotations

import json

from grounding import Mark
from messages import set_language

from playfellow_coop.spatial import MOVED, StuckTracker
from playfellow_coop.stage_timer import StageTimer
from tests.test_session_and_handover import Brain, make, session


def me(x, y):
    return Mark("me", x, y, "ME")


def test_pressing_a_direction_and_not_moving_says_so():
    tracker = StuckTracker()
    assert tracker.note([me(100, 100)]) == ""  # the first look: nothing to compare with
    tracker.acted(["right"])
    line = tracker.note([me(100 + MOVED - 1, 100)])  # moved less than the threshold
    assert "did not move you" in line and "right" in line


def test_moving_enough_says_nothing_and_so_does_a_non_direction_key():
    tracker = StuckTracker()
    tracker.note([me(100, 100)])
    tracker.acted(["right"])
    assert tracker.note([me(100 + MOVED + 2, 100)]) == ""  # it moved
    tracker.acted(["jump", "use"])  # not direction keys: never judged
    assert tracker.note([me(100 + MOVED + 2, 100)]) == ""


def test_card_action_names_in_capitals_count_as_direction_keys():
    tracker = StuckTracker()
    tracker.note([me(100, 100)])
    tracker.acted(["RIGHT"])
    assert "RIGHT" in tracker.note([me(100, 100)])


def test_the_note_is_said_once_and_does_not_repeat_without_a_new_press():
    tracker = StuckTracker()
    tracker.note([me(5, 5)])
    tracker.acted(["up"])
    assert tracker.note([me(5, 5)]) != ""
    assert tracker.note([me(5, 5)]) == ""  # nothing was pressed since


def test_no_me_mark_means_no_note_and_forgets_the_old_position():
    tracker = StuckTracker()
    tracker.note([me(5, 5)])
    tracker.acted(["left"])
    assert tracker.note([]) == ""
    tracker.acted(["left"])
    assert tracker.note([me(5, 5)]) == ""  # the old position was forgotten, so there is nothing to compare


def test_the_note_has_an_arabic_version():
    set_language("arabic")
    try:
        tracker = StuckTracker()
        tracker.note([me(1, 1)])
        tracker.acted(["down"])
        assert "ملاحظة" in tracker.note([me(1, 1)])
    finally:
        set_language("english")


def test_in_a_real_turn_the_second_question_carries_the_note():
    parts, cfg = make()
    seen = []

    def ask(system, text, images):
        seen.append(text)
        return json.dumps({"thought": "", "say": "", "actions": ["right"]})

    parts.brain = type("B", (), {"ask": staticmethod(ask)})()
    parts.marker = lambda image: [Mark("me", 200, 500), Mark("reward", 800, 500)]  # ME never moves
    timer = StageTimer()
    parts.safety.start()
    for _ in range(2):
        timer.begin_turn()
        session.take_turn(parts, cfg, "system", timer)
    assert "did not move you" not in seen[0] and "did not move you" in seen[1]
    assert Brain is not None  # the shared fakes are the ones the other session tests use
