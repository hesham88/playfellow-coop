"""Lane K (owner go 2026-10-31): pillar-review steps S1-S6.

S1 the goal checker must not cry "done" on the wrong screen (D2-D5), a relative LOOK
must survive the guardrails (D1), and opposite inputs must cancel across devices (D6).
S2 the session's plain actions pass through GuardRails before the hands, with the
keys already held across turns fed in (D7). S3 a real GameClock for our own
step-driven games. S4 the supervisor notices a frozen picture (hang) and a first
picture (ready), not only a dead process. S6 an end screen is read from the learned
region, not the whole picture. Synthetic inputs only; no game window, no network.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.universal.actions import ActionBinder, GuardRails, filter_steps, native_plan
from playfellow_coop.universal.state import GoalChecker, StateClassifier
from playfellow_coop.universal.timing import ClockSync, StepClock, Supervisor


# ---------- S1: false "goal reached" (pillar defects D2-D5) ----------

def test_goal_number_must_sit_with_its_noun_on_the_same_line():
    goal = GoalChecker("reach level 3")
    assert not goal.check(["Score 3", "Level 1"]).done  # D2: the 3 belongs to the score
    assert goal.check(["Level 3", "Score 0"]).done


def test_goal_number_must_touch_its_noun_not_just_share_a_line():
    goal = GoalChecker("reach level 3")
    assert not goal.check(["Score 3 / Level 1"]).done  # D2 strict: the 3 sits with the score, the level is 1
    assert not goal.check(["Level 1 | Total 3"]).done  # same line is not enough: the number must touch its noun
    assert goal.check(["Level 3"]).done
    assert goal.check(["Level: 3"]).done


def test_goal_numbers_read_arabic_digits_on_either_side():
    goal = GoalChecker("reach level 3")
    assert goal.check(["Level ٣"]).done  # Arabic-Indic digit on screen
    assert not goal.check(["Score ٣ / Level 1"]).done
    assert GoalChecker("reach level ٣").check(["Level 3"]).done  # Arabic-Indic digit in the goal itself


def test_goal_count_must_be_the_count_of_the_named_thing():
    goal = GoalChecker("collect 10 coins")
    assert not goal.check(["coins 9", "lives 10"]).done  # D3
    assert goal.check(["coins 10", "lives 1"]).done


def test_a_shop_listing_is_not_owning_the_thing():
    goal = GoalChecker("find a sword")
    assert not goal.check(["Shop: sword 300 gold"]).done  # D4
    assert goal.check(["Inventory", "Iron Sword"]).done


def test_a_negated_goal_is_done_only_when_the_thing_is_absent():
    goal = GoalChecker("do not pick up the sword")
    assert not goal.check(["You picked up the sword"]).done  # D5
    assert goal.check(["A quiet corridor"]).done
    assert "do" not in goal.keywords and "not" not in goal.keywords


# ---------- S1: relative LOOK and cross-device opposites (D1, D6) ----------

def test_a_relative_look_survives_the_guardrails_and_is_never_mapped_to_the_window():
    plan = GuardRails().check(ActionBinder().bind("[LOOK(-200, 50)]"))
    assert len(plan.steps) == 1 and plan.steps[0][0].kind == "mouse_move"
    assert (plan.steps[0][0].x, plan.steps[0][0].y) == (-200, 50)  # D1: left/up was dropped before this fix
    assert plan.steps[0][0].to_pixels((100, 50, 800, 600)) == plan.steps[0][0]  # relative: the window box must not move it
    clamped = GuardRails().check(ActionBinder().bind("[LOOK(-5000, 0)]"))
    assert clamped.steps[0][0].x == -1000 and any("clamped" in n for n in clamped.notes)


def test_opposites_cancel_across_devices_not_only_between_keys():
    plan = GuardRails().check(ActionBinder().bind("[STICK(left, -1000, 0)]&[BUTTON(dpad_right)]"))  # D6
    kept = [(i.kind, i.key) for step in plan.steps for i in step]
    assert kept == [("stick", "left")] and any("cancel out" in n for n in plan.notes)


def test_the_guardrails_see_keys_already_held_across_turns():
    plan = GuardRails().check(ActionBinder().bind("[MOVE_RIGHT]"), held_keys={"a"})  # D7: 'a' is down from a persistent hold
    assert plan.steps == [] and any("already held" in n for n in plan.notes)


# ---------- S2: card steps through the guardrails, one grid mapper ----------

@dataclass
class _Action:
    kind: str = "keys"
    keys: tuple = ()
    hold: float = 0.15
    dx: int = 0
    dy: int = 0
    button: str = "left"
    hold_key: str = ""


@dataclass
class _Step:
    action: str
    x: int | None = None
    y: int | None = None
    x2: int | None = None
    y2: int | None = None


@dataclass
class _Card:
    actions: dict = field(default_factory=dict)


def _card() -> _Card:
    return _Card({"left": _Action(keys=("a",)), "right": _Action(keys=("d",)),
                  "shoot": _Action(kind="click", keys=()), "look": _Action(kind="mouse_move", dx=-200, dy=50)})


def test_card_steps_become_a_guarded_plan_and_bad_steps_fall_out():
    card = _card()
    steps = [_Step("left"), _Step("right"), _Step("shoot", x=500, y=250), _Step("look"), _Step("missing")]
    kept, notes = filter_steps(steps, card, GuardRails(), held_keys={"a"})
    assert [s.action for s in kept] == ["left", "shoot", "look"]  # right would cancel the already-held 'a'; unknown actions fall out with a note
    assert any("already held" in n for n in notes) and any("missing" in n for n in notes)
    plan = native_plan([_Step("shoot", x=500, y=250)], card)
    assert plan.steps[0][0].kind == "mouse_click" and (plan.steps[0][0].x, plan.steps[0][0].y) == (500, 250)


# ---------- S3: a real clock for step-driven games ----------

def test_a_step_clock_only_advances_the_game_when_it_is_not_paused():
    ticks = []
    clock = StepClock(step=lambda key: ticks.append(key))
    assert clock.advance("left") and ticks == ["left"]
    clock.pause()
    assert not clock.advance("right") and ticks == ["left"]  # the model may think as long as it likes: the game does not move
    clock.resume()
    assert clock.advance("right") and clock.ticks == 2
    sync = ClockSync(clock=clock, now=iter([0.0, 0.25]).__next__)
    with sync.thinking():
        assert clock.paused
    assert not clock.paused and sync.thinking_ms == [250.0]


# ---------- S4: hang and ready, not only a dead process ----------

def test_the_supervisor_sees_a_first_picture_and_a_frozen_one():
    clock = [0.0]
    sup = Supervisor(launch=lambda: "game", alive=lambda h: True, stop=lambda h: None,
                     now=lambda: clock[0], frame_probe=lambda h: "frame-a", hang_s=10.0)
    sup.start()
    assert sup.poll() == "ready"  # first picture seen
    clock[0] = 2.0
    assert sup.poll() == "running"
    clock[0] = 12.0  # the same picture for 12 s while the process lives: a hang, met with the crash budget
    assert sup.poll() == "restarted" and any("hang" in text for _, text in sup.events)


# ---------- S6: the end screen is read where the game writes it ----------

def test_the_end_screen_comes_from_the_learned_region():
    rng = np.random.default_rng(3)

    def board(seed):
        frame = (rng.random((240, 320, 3)) * 120 + 40).astype(np.uint8)
        frame[:30] = (18, 20, 34)
        return frame

    def status(frame, colour):
        out = frame.copy()
        for letter in range(8):
            out[17:25, 10 + letter * 7:14 + letter * 7] = colour
        return out

    rows = []
    for seed in range(8):
        rows.append((board(seed), "gameplay", None))
        rows.append((status(board(seed + 40), (90, 225, 120)), "victory", None))
    model = StateClassifier().fit(rows, regions=1)
    assert model.end_screen(status(board(99), (90, 225, 120))) == "victory"
    assert model.end_screen(board(99)) is None  # still playing: no end is claimed
    assert StateClassifier().end_screen(board(99)) is None  # an unfitted classifier never claims an end
