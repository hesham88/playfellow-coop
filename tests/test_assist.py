"""The accessibility co-op as the application describes it: the player plays; when a part is too hard they say what they want, the buddy
does that part with the keys the card allows, only in the chosen window, and gives the controls back by itself. Split controls: the
player picks the keys they keep, and the buddy can never press or release them. Pretend eyes, hands and brain: no key, no screen, no network."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

import controls
from safety import Safety

from playfellow_coop import session
from playfellow_coop.assist import Assist, AssistError, OwnedKeys, buddy_card
from playfellow_coop.handover import HandOver
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue

from tests.test_session_and_handover import CARD, MOVE, make

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
ARENA_CARDS = sorted((ENGINE / "controls").glob("arena_*.yaml"))


# ---- split controls: the card the buddy plans with ----------------------------------------------------------------
def _keys(card):
    return {k for a in card.actions.values() for k in (*a.keys, *((a.hold_key,) if a.hold_key else ()))}


def test_the_buddy_card_drops_every_action_that_uses_a_key_the_player_keeps():
    owned = {next(iter(CARD.actions[MOVE].keys))}
    mine = buddy_card(CARD, owned)
    assert MOVE not in mine.actions and mine.actions
    assert not _keys(mine) & owned
    assert set(mine.actions) <= set(CARD.actions)  # nothing new is invented, only taken away


def test_owning_a_key_the_card_never_heard_of_or_every_key_is_refused_in_both_languages():
    with pytest.raises(AssistError):
        buddy_card(CARD, {"not-a-key"})
    with pytest.raises(AssistError):
        buddy_card(CARD, _keys(CARD))  # the buddy would have nothing left to press


@pytest.mark.parametrize("path", ARENA_CARDS, ids=lambda p: p.stem)
def test_on_every_arena_game_the_buddy_card_never_holds_a_key_the_player_keeps(path):
    card = controls.load_card(path)
    keys = sorted(_keys(card))
    if len(keys) < 2:
        pytest.skip("a one-key game cannot be split")
    owned = {keys[0]}
    mine = buddy_card(card, owned)
    assert not _keys(mine) & owned


def test_there_are_at_least_fifteen_arena_games_to_split():
    assert len(ARENA_CARDS) >= 15


# ---- split controls: the keys themselves --------------------------------------------------------------------------
class Backend:
    def __init__(self):
        self.log = []

    def keyDown(self, k): self.log.append(("down", k))  # noqa: E704,N802
    def keyUp(self, k): self.log.append(("up", k))  # noqa: E704,N802
    def key_down(self, k): self.log.append(("down", k))  # noqa: E704
    def key_up(self, k): self.log.append(("up", k))  # noqa: E704
    def press(self, k): self.log.append(("press", k))  # noqa: E704
    def moveTo(self, x, y): self.log.append(("move", x, y))  # noqa: E704,N802


def test_the_guard_never_presses_or_releases_a_kept_key_in_any_letter_case_and_counts_each_refusal():
    inner = Backend()
    guard = OwnedKeys(inner, {"j", "Space"})
    for call in ("keyDown", "keyUp", "key_down", "key_up", "press"):
        getattr(guard, call)("J")
        getattr(guard, call)("space")
        getattr(guard, call)("left")
    assert all(entry[1] == "left" for entry in inner.log) and len(inner.log) == 5
    assert guard.refused == 10
    guard.moveTo(3, 4)  # everything else passes through untouched
    assert inner.log[-1] == ("move", 3, 4)


# ---- the assist: you ask, it does that part, it gives the controls back --------------------------------------------
def _assisted(done_after=None, max_turns=6, said=("grab the coins on the left",), stop_at=None):
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    resumes_at_stop = {}

    def done(request, the_parts):
        return done_after is not None and the_parts.brain.calls >= done_after  # the game's own truth stands in here: "done after N turns"

    parts.assist = Assist(max_turns=max_turns, done=done)
    queue, events, ticks = CommandQueue(), [], {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 2:
            for line in said:
                queue.put(line)
        if stop_at is not None and ticks["n"] == stop_at:
            parts.safety.stop("stopped_f12")
            resumes_at_stop["n"] = parts.hands.resumes
        return ticks["n"] >= 20

    reason = session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue,
                                  on_event=lambda kind, data: events.append((kind, data)))
    parts.resumes_at_stop = resumes_at_stop.get("n")
    return parts, handover, events, reason


def test_the_player_starts_with_the_controls_and_nothing_is_asked_until_they_ask():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=4)
    ticks = {"n": 0}
    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=lambda s: ticks.__setitem__("n", ticks["n"] + 1) or ticks["n"] >= 5,
                         commands=CommandQueue())
    assert parts.brain.calls == 0 and parts.hands.pressed == [] and parts.screen.grabs == 0
    assert handover.human_has_controls


def test_a_spoken_request_hands_over_that_part_and_the_controls_come_back_by_themselves_when_it_is_done():
    parts, handover, events, _ = _assisted(done_after=3)
    said = [data for kind, data in events if kind == "say"]
    assert any("grab the coins on the left" in line for line in said)
    record = parts.assist.log[-1]
    assert record["request"] == "grab the coins on the left" and record["done"] is True and record["turns"] == 3
    assert record["ai_calls"] == parts.brain.calls == 3 and record["actions"] == 3
    assert handover.human_has_controls  # back with the player, without a key or a word from them
    assert any(line.startswith("Done") or line.startswith("تم") for line in said)


def test_the_planner_hears_the_request_as_the_players_words():
    seen = []
    parts, cfg = make()
    parts.brain.ask = lambda system, text, images: seen.append(text) or json.dumps({"thought": "", "say": "", "actions": [MOVE]})
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=1)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("take me to the door")
        return ticks["n"] >= 6

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    assert len(seen) == 1 and "take me to the door" in seen[0]


def test_a_part_that_is_not_done_in_time_comes_back_honestly_after_the_turn_limit():
    parts, handover, events, _ = _assisted(done_after=None, max_turns=4)
    record = parts.assist.log[-1]
    assert record["done"] is False and record["turns"] == 4 and parts.brain.calls == 4
    assert handover.human_has_controls
    assert any("couldn't finish" in data or "لم أستطع" in data for kind, data in events if kind == "say")


def test_f12_during_an_assisted_part_ends_everything_and_is_recorded_as_a_stop_not_a_success():
    parts, handover, events, reason = _assisted(done_after=None, max_turns=10, stop_at=4)
    assert reason == "stopped_f12"
    record = parts.assist.log[-1]
    assert record["done"] is False and record["ended"] == "stopped_f12"
    assert parts.hands.resumes == parts.resumes_at_stop  # after F12 nothing is resumed, not even by the hand-back


def test_assist_and_split_controls_together_never_press_a_kept_key():
    owned = {next(iter(CARD.actions[MOVE].keys))}
    parts, cfg = make()
    parts.card = buddy_card(CARD, owned)
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=3)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("you block, I heal")
        return ticks["n"] >= 8

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    assert parts.brain.calls == 3 and parts.hands.pressed == []  # the brain asked for the kept key; the card dropped it every time


def test_a_done_check_that_crashes_never_claims_the_part_was_done():
    from tests.test_session_and_handover import make as make_parts
    parts, _ = make_parts()
    assist = Assist(max_turns=2, done=lambda request, p: 1 / 0)
    assist.begin("get me past this jump", 0)
    assert assist.after_turn(parts, 1, 1) is None
    line = assist.after_turn(parts, 1, 2)
    assert assist.log[-1]["done"] is False and assist.log[-1]["ended"] == "turn_limit" and "couldn't finish" in line


def test_the_command_line_turns_on_the_assist_and_splits_the_controls_around_the_backend_that_really_presses():
    from playfellow_coop import __main__ as entry
    from tests.test_main import Parts

    class RealBackend(Backend):
        pass

    def builder(cfg):
        parts = Parts()
        parts.hands.backend = RealBackend()
        return parts

    key = sorted(next(iter(a.keys)) for a in CARD.actions.values() if a.keys)[0]
    parts, _ = entry.build(["--assist", "5", "--keep", key], build_parts=builder, key_loader=lambda: None)
    assert parts.assist.max_turns == 5
    assert isinstance(parts.hands.backend, OwnedKeys) and key in parts.hands.backend.owned
    assert not any(key in a.keys for a in parts.card.actions.values())
    plain, _ = entry.build([], build_parts=builder, key_loader=lambda: None)
    assert not hasattr(plain, "assist") and isinstance(plain.hands.backend, RealBackend)  # off unless asked


# ---- the live "is this part done" check: the planner says so, and the record says who decided ---------------------------
def test_the_planner_saying_done_ends_the_part_and_the_record_says_the_model_decided():
    from playfellow_coop.assist import DoneSpotter, model_said_done
    parts, cfg = make()
    answers = iter([{"actions": [MOVE]}, {"actions": [MOVE]}, {"actions": [], "done": True}] + [{"actions": [MOVE]}] * 20)
    parts.brain.ask = lambda system, text, images: json.dumps({"thought": "", "say": "", **next(answers)})
    parts.brain = DoneSpotter(parts.brain)
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=10, done=model_said_done)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("take me to the door")
        return ticks["n"] >= 12

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    record = parts.assist.log[-1]
    assert record["done"] is True and record["turns"] == 3 and record["done_by"] == "model_said"
    assert handover.human_has_controls and parts.safety.calls == 3


def test_done_must_be_the_json_value_true_a_string_or_a_missing_flag_never_ends_the_part():
    from playfellow_coop.assist import DoneSpotter
    for raw in ('{"actions": [], "done": "true"}', '{"actions": [], "done": 1}', '{"actions": []}', "no json at all", '{"done": false}'):
        spotter = DoneSpotter(type("B", (), {"ask": lambda self, s, t, i, raw=raw: raw})())
        spotter.ask("s", "t", [])
        assert spotter.said_done is False, raw
    spotter = DoneSpotter(type("B", (), {"ask": lambda self, s, t, i: '{"actions": [], "done": true}', "last_request": {"cost_usd": 0.01}})())
    spotter.ask("s", "t", [])
    assert spotter.said_done is True and spotter.last_request == {"cost_usd": 0.01}  # everything else passes through


def test_a_done_flag_from_before_the_request_does_not_end_the_next_part():
    from playfellow_coop.assist import DoneSpotter, model_said_done
    spotter = DoneSpotter(type("B", (), {"ask": lambda self, s, t, i: '{"done": true}'})())
    spotter.ask("s", "t", [])
    parts = type("P", (), {"brain": spotter})()
    assist = Assist(max_turns=3, done=model_said_done)
    assist.begin("grab the coins", 0, parts=parts)  # a new part forgets the last answer
    assert spotter.said_done is False and model_said_done("grab the coins", parts) is False


def test_the_command_line_assist_tells_the_planner_the_done_rule_and_wraps_the_brain():
    from playfellow_coop import __main__ as entry
    from playfellow_coop.assist import DONE_RULE, DoneSpotter, VerifiedDone
    from tests.test_main import Parts

    def builder(cfg):
        p = Parts()
        p.screen = type("S", (), {"find": lambda self, t: None, "grab": lambda self, b: None})()
        return p

    parts, _ = entry.build(["--assist"], build_parts=builder, key_loader=lambda: None)
    assert isinstance(parts.brain, DoneSpotter) and isinstance(parts.assist._done, VerifiedDone)
    assert entry.assist_system("base") == "base\n\n" + DONE_RULE and "done" in DONE_RULE


# ---- live "done": the model must be able to say it, and must still know what was asked -----------------------------------------------
def test_with_the_assist_on_the_strict_answer_schema_carries_a_done_flag():
    from playfellow_coop.muse_brain import MuseBrain
    brain = MuseBrain("muse-spark-1.3", "k")
    brain.set_actions(["UP", "DOWN"])
    assert "done" not in brain._schema()["json_schema"]["schema"]["properties"]  # off unless the assist asks for it
    brain.set_done_flag(True)
    schema = brain._schema()["json_schema"]["schema"]
    assert schema["properties"]["done"] == {"type": "boolean"} and "done" in schema["required"]


def test_the_planner_hears_the_request_on_every_turn_of_the_part_not_only_the_first():
    seen = []
    parts, cfg = make()
    parts.brain.ask = lambda system, text, images: seen.append(text) or json.dumps({"thought": "", "say": "", "actions": [MOVE]})
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=3)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("take me to the door")
        return ticks["n"] >= 8

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    assert len(seen) == 3 and all("take me to the door" in text for text in seen)


def test_the_command_line_assist_asks_the_brain_for_the_done_flag():
    from playfellow_coop import __main__ as entry
    from tests.test_main import Parts

    class Brain:
        flag = None

        def set_done_flag(self, on):
            self.flag = on

    def builder(cfg):
        p = Parts()
        p.brain = Brain()
        return p

    parts, _ = entry.build(["--assist"], build_parts=builder, key_loader=lambda: None)
    assert parts.brain.flag is True


# ---- a second look before "done" counts: two pictures, when the player asked and now ------------------------------------------------------
def test_a_done_claim_counts_only_when_a_second_look_at_before_and_now_agrees():
    from playfellow_coop.assist import DoneSpotter, VerifiedDone
    parts, cfg = make()
    asked = []

    def ask(system, text, images):
        asked.append((system, text, len(images)))
        if "finished" in system:  # the second look: says no the first time, yes the second
            return json.dumps({"thought": "", "say": "", "actions": [], "done": sum("finished" in s for s, _, _ in asked) >= 2})
        return json.dumps({"thought": "", "say": "", "actions": [MOVE], "done": True})  # the planner claims done every turn

    parts.brain.ask = ask
    parts.brain = DoneSpotter(parts.brain)
    check = VerifiedDone(grab=lambda: parts.screen.grab(parts.screen.find("")))
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=8, done=check)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("take me to the door")
        return ticks["n"] >= 12

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    record = parts.assist.log[-1]
    assert record["done"] is True and record["done_by"] == "model_verified" and record["turns"] == 2
    looks = [a for a in asked if "finished" in a[0]]
    assert len(looks) == 2 and all(n == 2 for _, _, n in looks)  # two pictures each time: when asked, and now
    assert all("take me to the door" in text for _, text, _ in looks)
    assert check.refused == 1  # the first claim was not confirmed and the part went on


def test_without_a_claim_no_second_look_is_spent():
    from playfellow_coop.assist import VerifiedDone
    calls = []
    parts = type("P", (), {"brain": type("B", (), {"said_done": False, "ask": lambda self, *a: calls.append(a)})()})()
    check = VerifiedDone(grab=lambda: None)
    assert check("x", parts) is False and calls == []


def test_a_one_word_fragment_does_not_start_a_part_but_a_real_request_does():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=2, min_words=2)
    queue, ticks, said = CommandQueue(), {"n": 0}, []

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("click")
        if ticks["n"] == 4:
            queue.put("run right and jump")
        return ticks["n"] >= 12

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue, on_event=lambda k, d: said.append((k, d)))
    assert [r["request"] for r in parts.assist.log] == ["run right and jump"]
    assert any("click" in str(d) for k, d in said if k == "status")  # the player is told it was too short to act on


def test_new_words_during_a_part_replace_it_at_once_and_wait_hands_back():
    parts, cfg = make()
    handover = HandOver(parts.hands, parts.safety)
    parts.assist = Assist(max_turns=6)
    queue, ticks = CommandQueue(), {"n": 0}

    def wait(seconds):
        ticks["n"] += 1
        if ticks["n"] == 1:
            queue.put("run to the level painting")
        if ticks["n"] == 3:
            queue.put("jump up to enter the level")  # said while the first part runs
        if ticks["n"] == 5:
            queue.put("wait")
        return ticks["n"] >= 9

    session.play_session(parts, cfg, "system", StageTimer(), handover, wait=wait, commands=queue)
    log = parts.assist.log
    assert [r["request"] for r in log] == ["run to the level painting", "jump up to enter the level"]
    assert log[0]["ended"] == "replaced" and log[0]["turns"] < 6
    assert log[1]["ended"] == "player_took"  # "wait" gave the controls straight back
    assert handover.human_has_controls
