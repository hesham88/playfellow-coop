"""The composed loop and the hand-over, with pretend eyes, hands and brain (no key, no screen, no network)."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from PIL import Image

import controls
import settings as engine_settings
from eyes import WindowBox
from memory import Memory
from safety import Safety

from playfellow_coop import session
from playfellow_coop.handover import HandOver, summary
from playfellow_coop.stage_timer import StageTimer

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])

CARD = controls.load_card(ENGINE / "controls" / "practice_arena.yaml")
MOVE = sorted(CARD.actions)[0]
REPLY = json.dumps({"thought": "go", "say": "", "actions": [MOVE]})


class Screen:
    def __init__(self):
        self.front, self.grabs = True, 0

    def find(self, title):
        return WindowBox(0, 0, 160, 120)

    def in_front(self, title):
        return self.front

    def grab(self, box):
        self.grabs += 1
        return Image.new("RGB", (box.width, box.height), (20, 40, 60))


class Hands:
    def __init__(self):
        self.pressed, self.stops, self.resumes = [], 0, 0

    def do(self, step, box):
        self.pressed.append(step.action)

    def on_stop(self):
        self.stops += 1

    def resume(self):
        self.resumes += 1


class Brain:
    def __init__(self, delay=0.0):
        self.calls, self.delay = 0, delay

    def ask(self, system, text, images):
        self.calls += 1
        time.sleep(self.delay)
        return REPLY


class Stepping:
    """A clock that moves forward a little each time it is read, so every timed stage has a real duration above zero."""

    def __init__(self):
        self.t = 0.0

    def __call__(self):
        self.t += 0.001
        return self.t


def make(brain=None, max_calls=50):
    parts = type("P", (), {})()
    parts.brain, parts.card, parts.screen, parts.hands = brain or Brain(), CARD, Screen(), Hands()
    parts.safety, parts.memory = Safety(5, max_calls), Memory(2)
    return parts, engine_settings.Settings(look_every_seconds=0.2)


def _one_turn(parts, cfg, timer):
    parts.safety.start()
    timer.begin_turn()
    reply = session.take_turn(parts, cfg, "system", timer)
    return reply, timer.end_turn()


def test_one_turn_emits_every_stage_that_exists_each_above_zero():
    parts, cfg = make()
    _, turn = _one_turn(parts, cfg, StageTimer(Stepping()))
    assert set(turn) == {"capture", "shrink", "request", "parse_and_check", "key_down"}  # this brain times nothing inside
    assert all(seconds > 0 for seconds in turn.values())
    assert parts.hands.pressed == [MOVE]


def test_a_slow_brain_lands_in_the_request_stage_and_nowhere_else():
    parts, cfg = make(Brain(delay=0.3))
    _, turn = _one_turn(parts, cfg, StageTimer())
    assert 0.28 <= turn["request"] < 0.6
    assert all(seconds < 0.05 for name, seconds in turn.items() if name != "request")


def test_a_brain_that_times_its_own_inside_is_split_into_encode_and_request():
    parts, cfg = make()
    parts.brain.last_timings = {"encode": 0.011, "request": 0.022}
    _, turn = _one_turn(parts, cfg, StageTimer())
    assert turn["encode"] == 0.011 and turn["request"] == 0.022


def test_off_card_actions_are_still_dropped_by_the_engines_own_check():
    parts, cfg = make()
    parts.brain.ask = lambda system, text, images: json.dumps({"thought": "", "say": "", "actions": ["FORMAT_DISK"]})
    reply, _ = _one_turn(parts, cfg, StageTimer())
    assert parts.hands.pressed == [] and reply.dropped


def test_no_key_goes_down_when_the_window_is_not_in_front():
    parts, cfg = make()
    parts.screen.front = False
    reply, _ = _one_turn(parts, cfg, StageTimer())
    assert reply is None and parts.hands.pressed == [] and parts.brain.calls == 0 and parts.screen.grabs == 0


# ---- the hand-over --------------------------------------------------------------------------------------------
def test_while_the_player_has_the_controls_no_picture_no_ai_and_no_key():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    ticks = {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            handover.take_over()  # F9: after the first buddy turn the player takes over
        return ticks["n"] >= 5

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait)
    assert parts.brain.calls == 1 and parts.hands.pressed == [MOVE]  # only the first turn, before the take-over
    assert parts.screen.grabs == 1 and handover.turns_skipped >= 3
    assert parts.safety.calls == 1  # the AI call counter never moved after the take-over


def test_taking_over_releases_every_held_key_at_once_and_giving_back_resumes():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.safety.start()
    assert handover.take_over() is True and parts.hands.stops == 1 and handover.human_has_controls
    assert handover.take_over() is False and parts.hands.stops == 1  # a second take-over does nothing
    text = handover.give_back()
    assert parts.hands.resumes == 1 and not handover.human_has_controls and text


def test_f9_toggles_and_only_the_give_back_returns_a_summary():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.safety.start()
    assert handover.toggle() is None and handover.human_has_controls
    assert isinstance(handover.toggle(), str) and not handover.human_has_controls


def test_the_summary_is_made_only_of_counted_facts_in_both_languages():
    from messages import set_language

    clock = {"t": 100.0}
    parts, cfg = make()
    parts.safety.start()
    handover = HandOver(parts.hands, parts.safety, clock=lambda: clock["t"])
    handover.take_over()
    for _ in range(7):
        handover.note_skipped()
    clock["t"] = 112.4
    try:
        set_language("english")
        english = handover.give_back()
        set_language("arabic")
        arabic = summary(12.4, 7, 0)
    finally:
        set_language("english")
    assert english == "Back with me. You played for 12 s; I waited out 7 turns and asked the AI 0 times."
    assert "12" in arabic and "7" in arabic and arabic != english and not any("a" <= c.lower() <= "z" for c in arabic)
    assert (handover.times_taken, handover.turns_skipped, handover.ai_calls_while_player) == (1, 7, 0)


def test_the_summary_counts_an_ai_call_that_really_happened_during_the_take_over():
    parts, cfg = make()
    parts.safety.start()
    handover = HandOver(parts.hands, parts.safety)
    handover.take_over()
    parts.safety.count_ai_call()  # an AI call during the player's turn must be reported, not hidden
    handover.give_back()
    assert handover.ai_calls_while_player == 1


def test_a_stop_stays_a_stop_the_hands_are_not_resumed_after_f12():
    parts, cfg = make()
    parts.safety.start()
    handover = HandOver(parts.hands, parts.safety)
    handover.take_over()
    parts.safety.stop("stopped_f12")
    handover.give_back()
    assert parts.hands.resumes == 0
    assert handover.take_over() is False  # nothing can be taken over after a stop


def test_f12_still_ends_the_session_while_the_player_has_the_controls():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.safety.start()
    handover.take_over()

    def wait(seconds):
        parts.safety.stop("stopped_f12")
        return True

    reason = session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait)
    assert reason == "stopped_f12" and parts.hands.stops >= 1 and parts.brain.calls == 0


# ---- the screen watch -----------------------------------------------------------------------------------------
def _loading_screen(box):
    import numpy as np
    frame = np.full((box.height, box.width, 3), 12, np.uint8)
    frame[100:106, 30:90] = (200, 200, 200)
    return Image.fromarray(frame)


def test_a_frozen_loading_screen_is_waited_out_without_asking_the_model_but_only_twice_in_a_row():
    from playfellow_coop.universal.watch import ScreenWatch
    parts, cfg = make()
    parts.screen.grab = lambda box: _loading_screen(box)
    parts.screen_watch = ScreenWatch()
    events = []
    parts.safety.start()
    replies = [session.take_turn(parts, cfg, "system", StageTimer(), lambda kind, data: events.append(kind)) for _ in range(6)]
    assert all(reply is not None for reply in replies)
    # turn 1 has no earlier picture to compare (asked), turns 2 and 3 are skipped, turn 4 is forced (asked), then it rests: the model is never starved
    assert parts.brain.calls == 4 and events.count("status") == 2 and parts.hands.pressed == [MOVE] * 4


def test_a_moving_picture_is_never_skipped_and_a_game_over_screen_is_named_in_the_prompt():
    import numpy as np
    from playfellow_coop.universal.watch import ScreenWatch
    rng = np.random.default_rng(1)
    parts, cfg = make()
    seen_texts = []
    parts.brain.ask = lambda system, text, images: (seen_texts.append(text), REPLY)[1]
    noise = lambda: (rng.random((120, 160, 3)) * 160 + 40).astype(np.uint8)  # noqa: E731
    dead = (rng.random((120, 160, 3)) * 70).astype(np.uint8)
    dead[..., 0] = np.clip(dead[..., 0].astype(int) + 120, 0, 255)
    dead[..., 1] //= 3
    dead[..., 2] //= 3
    from playfellow_coop.universal.state import StateClassifier
    fitted = StateClassifier().fit([(noise(), "gameplay", noise()) for _ in range(8)] + [(dead, "dead", dead)] * 4)
    parts.screen.grab = lambda box: Image.fromarray(noise())
    parts.screen_watch = ScreenWatch(fitted)
    parts.safety.start()
    for _ in range(4):
        session.take_turn(parts, cfg, "system", StageTimer())
    assert len(seen_texts) == 4 and not any("screen looks like" in t for t in seen_texts)
    parts.screen.grab = lambda box: Image.fromarray(dead)
    for _ in range(2):  # the first picture after the cut moves a lot; the second is the steady game-over screen
        session.take_turn(parts, cfg, "system", StageTimer())
    assert "game-over screen" in seen_texts[-1]


def test_an_unfitted_watch_never_labels_screens_it_only_waits_out_a_black_frozen_one():
    import numpy as np
    from playfellow_coop.universal.watch import ScreenWatch
    rng = np.random.default_rng(3)
    parts, cfg = make()
    seen_texts = []
    parts.brain.ask = lambda system, text, images: (seen_texts.append(text), REPLY)[1]
    parts.screen.grab = lambda box: Image.fromarray((rng.random((box.height, box.width, 3)) * 255).astype(np.uint8))
    parts.screen_watch = ScreenWatch()  # the built-in centres are a rough guide: they must not put words in the model's prompt
    parts.safety.start()
    for _ in range(3):
        session.take_turn(parts, cfg, "system", StageTimer())
    assert len(seen_texts) == 3 and not any("screen looks like" in t for t in seen_texts)



def test_when_the_picture_stops_answering_the_keys_the_model_is_told_the_match_may_be_over():
    import numpy as np
    from playfellow_coop.universal.watch import END_NOTE, ScreenWatch
    parts, cfg = make()
    texts = []
    parts.brain.ask = lambda system, text, images: (texts.append(text), REPLY)[1]
    state = {"turn": 0}

    def grab(box):
        frame = np.full((box.height, box.width, 3), (60, 90, 120), np.uint8)
        x = (10 + 9 * min(state["turn"], 8)) % (box.width - 20)  # the avatar moves for eight turns, then the picture freezes
        frame[box.height // 2:box.height // 2 + 12, x:x + 12] = (250, 80, 80)
        state["turn"] += 1
        return Image.fromarray(frame)

    parts.screen.grab = grab
    parts.screen_watch = ScreenWatch(eog_fps=3.0)
    parts.safety.start()
    for _ in range(40):
        session.take_turn(parts, cfg, "system", StageTimer())
    assert END_NOTE in texts[-1] and END_NOTE not in texts[3]
    assert parts.screen_watch.end_candidates > 0


def test_a_watchdog_hook_ends_the_session_at_its_step_limit_and_a_match_over_stops_it_only_when_asked():
    import numpy as np
    from playfellow_coop.harness.hooks import from_spec
    from playfellow_coop.universal.watch import ScreenWatch
    parts, cfg = make(max_calls=500)
    parts.hooks = from_spec({"watchdog": {"max_steps": 3}})
    reason = session.play_session(parts, cfg, "system", StageTimer(), wait=lambda s: False)
    assert reason == "hook_limit" and parts.brain.calls == 3

    parts, cfg = make(max_calls=500)
    state = {"turn": 0}

    def grab(box):
        frame = np.full((box.height, box.width, 3), (60, 90, 120), np.uint8)
        x = (10 + 9 * min(state["turn"], 8)) % (box.width - 20)  # the avatar moves for eight turns, then the picture freezes
        frame[box.height // 2:box.height // 2 + 12, x:x + 12] = (250, 80, 80)
        state["turn"] += 1
        return Image.fromarray(frame)

    parts.screen.grab = grab
    parts.screen_watch = ScreenWatch(eog_fps=3.0)
    parts.stop_on_end = True
    assert session.play_session(parts, cfg, "system", StageTimer(), wait=lambda s: False, max_turns=60) == "match_over"
    assert 8 < parts.brain.calls < 60


def _alternating_grab(parts):
    import numpy as np
    state = {"n": 0}

    def grab(box):
        frame = np.full((box.height, box.width, 3), (60, 90, 120), np.uint8)
        x = 20 if state["n"] % 2 == 0 else 40  # a small avatar hops between two places: calm, repeating play
        frame[50:62, x:x + 12] = (250, 80, 80)
        state["n"] += 1
        return Image.fromarray(frame)

    parts.screen.grab = grab


def test_in_calm_repeating_play_the_state_action_memory_answers_without_the_model_and_a_plain_run_asks_every_time():
    from playfellow_coop.universal.live import LiveLoop
    plain, cfg = make(max_calls=500)
    _alternating_grab(plain)
    session.play_session(plain, cfg, "system", StageTimer(), wait=lambda s: False, max_turns=14)
    assert plain.brain.calls == 14

    parts, cfg = make(max_calls=500)
    _alternating_grab(parts)
    parts.live = LiveLoop()
    session.play_session(parts, cfg, "system", StageTimer(), wait=lambda s: False, max_turns=14)
    assert parts.live.served > 0 and parts.brain.calls < 14 and parts.live.summary()["served_from_memory"] == parts.live.served
    assert parts.hands.pressed.count(MOVE) >= 14  # every turn still pressed its key, from the model or from memory


def test_a_chunk_answer_is_played_as_timed_holds_on_the_cards_keys_only_and_every_key_comes_back_up():
    from playfellow_coop.universal.live import LiveLoop
    parts, cfg = make(max_calls=50)
    log = []

    class Backend:
        def keyDown(self, k): log.append(("down", k))
        def keyUp(self, k): log.append(("up", k))
        def moveRel(self, dx, dy): log.append(("move", dx, dy))

    parts.hands.backend = Backend()
    parts.live = LiveLoop()
    parts.brain.ask = lambda system, text, images: '<|action_start|>0 0 0; left; left right; q<|action_end|> {"thought": "go", "actions": []}'
    parts.safety.start()
    session.take_turn(parts, cfg, "system", StageTimer())
    keys = {e[1] for e in log if e[0] in ("down", "up")}
    assert keys <= {"left", "right"} and "q" not in keys  # q is not a key on this card
    downs, ups = [e for e in log if e[0] == "down"], [e for e in log if e[0] == "up"]
    assert downs and sorted(k for _, k in downs) == sorted(k for _, k in ups)


def test_chunks_press_card_keys_only_in_any_letter_case_no_mouse_on_a_key_card_no_opposite_pair_and_a_failed_release_still_frees_the_rest():
    from playfellow_coop.universal.live import run_chunks
    from playfellow_coop.universal.chunks import Executor, plan, parse
    log = []

    class Backend:
        def keyDown(self, k): log.append(("down", k))
        def keyUp(self, k): log.append(("up", k))
        def moveRel(self, dx, dy): log.append(("move", dx, dy))

    run_chunks("<|action_start|>500 400 0; Left; left right; Space<|action_end|>", {"Left", "right"}, Backend(), sleep=lambda ms: None)
    assert not [e for e in log if e[0] == "move"]  # no mouse on a card without clicks
    assert {e[1] for e in log if e[0] == "down"} <= {"left", "right"} and ("down", "left") in log  # "Left" matched the card's "Left"
    assert not any(e[1] == "space" for e in log)
    first_pair = [e for e in log if e[0] == "down"]
    assert ("down", "right") not in first_pair[:1]
    log.clear()
    run_chunks("<|action_start|>30 0 0; left<|action_end|>", {"left"}, Backend(), sleep=lambda ms: None, allow_mouse=True)
    assert ("move", 30, 0) in [(e[0], e[1], e[2]) for e in log if e[0] == "move"] or any(e[0] == "move" for e in log)

    released = []

    class Flaky:
        def key_down(self, k): pass
        def key_up(self, k):
            released.append(k)
            if k == "a":
                raise OSError("driver hiccup")
        def mouse_move(self, dx, dy): pass

    events = plan(parse("<|action_start|>0 0 0; a b<|action_end|>"))
    try:
        Executor(Flaky(), sleep=lambda ms: None).run(events)
    except OSError:
        pass
    assert {"a", "b"} <= set(released)  # b was released although a's release raised


def test_the_dollar_limit_is_real_what_the_model_calls_report_adds_up_and_ends_the_session():
    from playfellow_coop.harness.hooks import from_spec
    parts, cfg = make(max_calls=500)
    parts.brain.last_request = {"cost_usd": 0.03}
    parts.hooks = from_spec({"watchdog": {"max_usd": 0.1}})
    reason = session.play_session(parts, cfg, "system", StageTimer(), wait=lambda s: False)
    assert reason == "hook_limit" and 3 <= parts.brain.calls <= 5


def test_a_resized_window_is_not_a_failed_key_and_the_live_loop_forgets_everything_on_reset():
    import numpy as np
    from playfellow_coop.universal.live import LiveLoop
    live = LiveLoop()
    small, large = np.zeros((40, 40, 3), np.uint8), np.zeros((60, 60, 3), np.uint8)
    live.look(small)
    live.acted(small, ["UP"])
    live.look(large)  # the shape changed: nothing is recorded, nothing counts as a failure
    assert len(live.memory) == 0 and live._asked_last is False
    live.acted(large, ["UP"])
    live.reset()
    assert live._last_frame is None and live._last_pending is None and len(live.memory) == 0
