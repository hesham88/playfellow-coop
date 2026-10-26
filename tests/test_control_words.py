"""The hand-over control words: matched exactly, in English and Arabic, applied without the AI, and never mistaken for a longer sentence."""
from __future__ import annotations

import json

import pytest

from meta_playfellow import session
from meta_playfellow.control_words import BUDDY_TAKES, PLAYER_TAKES, STOP, control_action, split
from meta_playfellow.handover import HandOver
from meta_playfellow.stage_timer import StageTimer
from meta_playfellow.voice import CommandQueue
from tests.test_session_and_handover import MOVE, make


@pytest.mark.parametrize("text,action", [
    ("stop", STOP), ("Stop!", STOP), ("  STOP now. ", STOP), ("وقّف", STOP), ("وقف", STOP), ("قف!", STOP),
    ("you take it", BUDDY_TAKES), ("You take over.", BUDDY_TAKES), ("خذها", BUDDY_TAKES), ("دورك", BUDDY_TAKES),
    ("I've got it", PLAYER_TAKES), ("I’ve got it!", PLAYER_TAKES), ("my turn", PLAYER_TAKES), ("أنا هكمل", PLAYER_TAKES),
    ("انا هكمل", PLAYER_TAKES), ("دوري", PLAYER_TAKES),
])
def test_the_phrases_are_recognised(text, action):
    assert control_action(text) == action


@pytest.mark.parametrize("text", ["don't stop at the door", "stop at the red door", "take it to the door", "you take the coins on the left",
                                  "grab the coins", "وقّف عند الباب", "", "   ", "stopping"])
def test_a_longer_sentence_that_contains_a_control_word_is_an_ordinary_command(text):
    assert control_action(text) is None


def test_split_keeps_ordinary_commands_and_orders_the_actions():
    ordinary, actions = split(["grab the coins", "stop", "go left", "my turn"])
    assert ordinary == ["grab the coins", "go left"] and actions == [STOP, PLAYER_TAKES]


def test_the_queue_hands_out_control_actions_and_keeps_the_rest():
    q = CommandQueue()
    for line in ("grab the coins", "stop", "you take it"):
        q.put(line)
    assert q.take_controls() == [STOP, BUDDY_TAKES] and q.drain() == ["grab the coins"]
    assert q.take_controls() == []


def test_stop_ends_the_session_at_once_without_asking_the_ai():
    parts, cfg = make()
    q = CommandQueue()
    q.put("stop")
    reason = session.play_session(parts, cfg, "system", StageTimer(), commands=q, wait=lambda s: False)
    assert reason == "stopped_button" and parts.brain.calls == 0 and parts.hands.pressed == [] and parts.hands.stops >= 1


def test_arabic_stop_works_the_same():
    parts, cfg = make()
    q = CommandQueue()
    q.put("وقّف")
    assert session.play_session(parts, cfg, "system", StageTimer(), commands=q, wait=lambda s: False) == "stopped_button"


def test_ive_got_it_takes_the_controls_and_you_take_it_gives_them_back_with_a_counted_summary():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    q = CommandQueue()
    said, ticks = [], {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            q.put("I've got it")
        if ticks["n"] == 3:
            q.put("you take it")
        return ticks["n"] >= 6

    session.play_session(parts, cfg, "system", StageTimer(), handover, on_event=lambda kind, data: said.append((kind, data)),
                         commands=q, wait=wait, max_turns=10)
    lines = [text for kind, text in said if kind == "say"]
    assert lines[0].startswith("It's yours") and lines[1].startswith("Back with me")  # the take-over line, then the counted summary
    assert handover.times_taken == 1 and not handover.human_has_controls
    assert parts.brain.calls >= 1  # after the give-back the buddy plays again


def test_a_control_word_changes_nothing_when_it_does_not_apply():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    q = CommandQueue()
    q.put("you take it")  # the buddy already has the controls
    session.play_session(parts, cfg, "system", StageTimer(), handover, commands=q, max_turns=1, wait=lambda s: True)
    assert handover.times_taken == 0 and parts.hands.pressed == [MOVE] and json is not None
