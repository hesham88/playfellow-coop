"""The universal game interface: four pillars (input and output, perception, clock and process, evaluation and guardrails), tested with made-up pictures and no game."""
from __future__ import annotations

import numpy as np
import pytest
from PIL import Image, ImageDraw, ImageFont

from playfellow_coop.universal import (ActionBinder, AdaptiveSkip, ClockSync, FrameClock, GlyphReader, GoalChecker, GuardRails, Hud, Interface, ModelReader, Odometry, Region,
                                       StateClassifier, Supervisor, bar_fraction, find_bars, moving_blobs, normalize, shift_between, text_regions)
from playfellow_coop.universal.frames import resize, to_rgb
from playfellow_coop.universal.hud import read_number
from playfellow_coop.universal.motion import components, motion_level
from playfellow_coop.universal.state import features

RNG = np.random.default_rng(7)


def texture(height=96, width=128):
    return (RNG.random((height, width, 3)) * 255).astype(np.uint8)


# ---------- pillar 1: frames ----------
def test_every_kind_of_picture_becomes_the_same_standard_matrix():
    bgra = np.zeros((4, 6, 4), np.uint8)
    bgra[..., 0], bgra[..., 2], bgra[..., 3] = 10, 200, 255  # blue 10, red 200
    rgb = to_rgb(bgra, "bgr")
    assert rgb.shape == (4, 6, 3) and rgb.dtype == np.uint8 and tuple(rgb[0, 0]) == (200, 0, 10)
    assert to_rgb(np.full((3, 3), 90, np.uint8)).shape == (3, 3, 3)
    assert to_rgb(np.full((3, 3, 3), 65535, np.uint16))[0, 0, 0] == 255
    assert to_rgb(np.full((3, 3, 3), 0.5, np.float32))[0, 0, 0] in (127, 128)
    assert to_rgb(Image.new("RGBA", (5, 5), (1, 2, 3, 4))).shape == (5, 5, 3)
    with pytest.raises(ValueError):
        to_rgb(np.zeros((2, 2, 5), np.uint8))


def test_resizing_keeps_colours_and_averages_when_shrinking():
    flat = np.full((40, 60, 3), (10, 200, 90), np.uint8)
    assert resize(flat, 20, 10).shape == (10, 20, 3) and (resize(flat, 20, 10) == flat[:10, :20]).all()
    big = resize(flat, 120, 80)
    assert big.shape == (80, 120, 3) and (big == (10, 200, 90)).all()
    checker = np.zeros((8, 8, 3), np.uint8)
    checker[::2, ::2] = 255
    checker[1::2, 1::2] = 255
    assert abs(int(resize(checker, 1, 1)[0, 0, 0]) - 128) <= 1  # half white, half black: grey, not an arbitrary pixel
    wide = normalize(texture(100, 400), max_side=200)
    assert wide.shape == (50, 200, 3)
    assert normalize(texture(100, 400), size=(80, 20)).shape == (20, 80, 3)


def test_frame_clock_measures_real_rate():
    now = [0.0]
    clock = FrameClock(clock=lambda: now[0])
    for _ in range(11):
        clock.tick()
        now[0] += 0.05
    assert clock.fps == pytest.approx(20.0) and clock.frame_ms == pytest.approx(50.0)
    assert FrameClock().fps == 0.0


# ---------- pillar 1: action tokens and guardrails ----------
def test_tokens_become_native_inputs_and_mouse_positions_map_to_the_window():
    plan = ActionBinder().bind("[MOVE_FORWARD] [HOLD(shift, 300)]&[JUMP] [CLICK(500, 250)] [DRAG_MOUSE(100,100,900,500)]")
    assert plan.notes == []
    assert [[(i.kind, i.key, i.hold_ms) for i in step] for step in plan.steps[:2]] == [[("key", "w", 200)], [("key", "shift", 300), ("key", "space", 0)]]
    click = plan.steps[2][0].to_pixels((100, 50, 1001, 501))
    assert (click.x, click.y) == (100 + 500, 50 + 125)
    drag = plan.steps[3][0].to_pixels((0, 0, 1001, 1001))
    assert (drag.x, drag.y, drag.x2, drag.y2) == (100, 100, 900, 500)


def test_unknown_malformed_and_off_card_tokens_are_dropped_with_a_reason_and_the_rest_runs():
    binder = ActionBinder(card_keys={"w", "space"})
    plan = binder.bind("[MOVE_FORWARD] [FLY_AWAY] [CLICK(5)] [MOVE_LEFT] garbage [JUMP]")
    assert [step[0].key for step in plan.steps] == ["w", "space"]
    text = " | ".join(plan.notes)
    assert "unknown action FLY_AWAY" in text and "CLICK needs" in text and "'a' is not on the controls card" in text and "not an action token" in text


def test_opposite_keys_together_are_refused_but_one_after_the_other_is_fine():
    binder, guard = ActionBinder(), GuardRails()
    both = guard.check(binder.bind("[MOVE_LEFT]&[MOVE_RIGHT]"))
    assert [i.key for i in both.steps[0]] == ["a"] and any("cancel out" in n for n in both.notes)
    after = guard.check(binder.bind("[MOVE_LEFT] [MOVE_RIGHT]"))
    assert [step[0].key for step in after.steps] == ["a", "d"] and after.notes == []
    assert [i.key for i in guard.check(binder.bind("[LEFT]&[UP]")).steps[0]] == ["left", "up"]  # a diagonal is fine


def test_guardrails_cap_holds_floods_and_total_time():
    guard = GuardRails(max_hold_ms=1000, max_inputs=3, max_turn_ms=1500)
    held = guard.check(ActionBinder().bind("[HOLD(w, 9000)]"))
    assert held.steps[0][0].hold_ms == 1000 and "cut to 1000" in held.notes[0]
    flood = guard.check(ActionBinder().bind("[JUMP] [JUMP] [JUMP] [JUMP] [JUMP]"))
    assert len(flood.steps) == 3 and any("too many inputs" in n for n in flood.notes)
    long = guard.check(ActionBinder().bind("[HOLD(w, 1000)] [HOLD(w, 1000)]"))
    assert len(long.steps) == 1 and any("more than 1500" in n for n in long.notes)
    bad = guard.check(ActionBinder().bind("[CLICK(5000, 10)]"))
    assert bad.steps == [] and any("outside the 0-1000 grid" in n for n in bad.notes)


# ---------- pillar 2: perception ----------
def test_bars_read_their_fill_and_unknown_bars_are_found():
    frame = np.zeros((60, 200, 3), np.uint8)
    frame[10:20, 20:120] = (60, 60, 60)
    frame[10:20, 20:80] = (220, 30, 30)  # 60 of 100 filled
    assert bar_fraction(frame, (20, 10, 100, 10), (220, 30, 30)) == pytest.approx(0.6, abs=0.02)
    assert bar_fraction(frame, (20, 10, 100, 10), (30, 30, 220)) == 0.0
    frame[40:50, 20:120] = (30, 200, 40)
    found = {colour: box for box, colour in find_bars(frame)}
    assert (220, 30, 30) in found and found[(220, 30, 30)] == (20, 10, 60, 10) and (30, 200, 40) in found
    vertical = np.zeros((100, 20, 3), np.uint8)
    vertical[50:, 5:15] = (30, 30, 220)  # fills from the bottom, half full
    assert bar_fraction(vertical, (5, 0, 10, 100), (30, 30, 220), vertical=True) == pytest.approx(0.5, abs=0.02)


def text_picture(text, scale=2):
    """Text drawn one letter per fixed-width cell, the way most game fonts are laid out."""
    image = Image.new("RGB", (10 * len(text) + 8, 20), (20, 20, 40))
    draw = ImageDraw.Draw(image)
    for index, char in enumerate(text):
        draw.text((4 + 10 * index, 4), char, fill=(240, 240, 240), font=ImageFont.load_default())
    return np.asarray(image.resize((image.width * scale, image.height * scale), Image.NEAREST))


def test_glyph_reader_reads_digits_and_words_from_a_drawn_font_and_hud_turns_them_into_values():
    reader = GlyphReader.from_font()
    assert reader.read(text_picture("1250")) == "1250"
    assert reader.read(text_picture("SCORE 42")).replace(" ", "") == "SCORE42"
    canvas = np.zeros((80, 300, 3), np.uint8)
    picture = text_picture("87")
    canvas[10:10 + picture.shape[0], 10:10 + picture.shape[1]] = picture
    hud = Hud({"hp": Region((10, 10, picture.shape[1], picture.shape[0]), "number"), "bar": Region((0, 60, 100, 10), "bar", (200, 0, 0))}, reader)
    canvas[60:70, 0:50] = (200, 0, 0)
    values = hud.read(canvas)
    assert values["hp"] == 87.0 and values["bar"] == pytest.approx(0.5, abs=0.03)
    assert Hud({"t": Region((0, 0, 10, 10))}).read(canvas) == {"t": None}  # no reader: honest None, not an invented text
    assert ModelReader(lambda crop: " 12 ").read(canvas) == "12"


def test_numbers_are_pulled_out_of_noisy_text():
    assert read_number("HP 87/100") == 87 and read_number("1,250 pts") == 1250 and read_number("x3") == 3 and read_number("no digits") is None
    assert read_number("l0O") == 100  # look-alike letters between digits are repaired


def test_text_regions_find_lines_of_text_but_not_plain_areas():
    canvas = np.zeros((120, 300, 3), np.uint8)
    picture = text_picture("GAME OVER")
    canvas[40:40 + picture.shape[0], 30:30 + picture.shape[1]] = picture
    boxes = text_regions(canvas)
    assert boxes and any(abs(left - 30) < 30 and abs(top - 40) < 20 for left, top, _, _ in boxes)
    assert text_regions(np.full((120, 300, 3), 90, np.uint8)) == []


def test_odometry_follows_a_slide_and_remembers_the_map_and_scenery_is_not_a_moving_thing():
    world = texture(200, 400)
    view = lambda x, y: world[y:y + 96, x:x + 128]  # noqa: E731
    dx, dy, confidence = shift_between(view(40, 30), view(34, 30))  # camera moved left 6: content slid right 6
    assert (dx, dy) == (6, 0) and confidence > 0.3
    odo = Odometry()
    for x in range(40, 40 + 5 * 8, 8):
        odo.update(view(x, 30))
    assert odo.x == 32 and odo.y == 0 and odo.seen(32, 0) and not odo.seen(500, 500)
    assert shift_between(np.zeros((40, 40, 3), np.uint8), np.zeros((40, 40, 3), np.uint8)) == (0, 0, 0.0)
    a = view(40, 30).copy()
    b = view(46, 30).copy()
    b[40:46, 60:66] = (255, 0, 0)  # one thing moved on its own while the scenery scrolled
    blobs = moving_blobs(a, b)
    assert len(blobs) >= 1 and any(abs(blob.centre[0] - 63) < 8 and abs(blob.centre[1] - 43) < 8 for blob in blobs)
    assert len(moving_blobs(a, b, compensate=False)) > len(blobs) or len(moving_blobs(a, b, compensate=False)) >= 1


def test_components_and_motion_level():
    mask = np.zeros((20, 20), bool)
    mask[2:5, 2:6] = True
    mask[10:12, 10:12] = True
    blobs = components(mask)
    assert [b.area for b in blobs] == [12, 4] and blobs[0].box == (2, 2, 4, 3) and components(mask, min_area=5)[0].area == 12
    still = texture()
    assert motion_level(still, still) == 0.0 and motion_level(still, texture()) > 0.9


# ---------- pillar 3: clock and process ----------
def test_adaptive_skip_waits_in_calm_moments_and_never_in_frantic_ones():
    skip = AdaptiveSkip(max_skip=10)
    assert skip.frames_to_skip(latency_ms=400, frame_ms=16, motion=0.1) == 10  # 25 frames went by: capped
    assert skip.frames_to_skip(latency_ms=100, frame_ms=50, motion=0.1) == 2
    assert skip.frames_to_skip(latency_ms=100, frame_ms=50, motion=0.5) == 0
    assert skip.frames_to_skip(latency_ms=100, frame_ms=50, motion=0.1, urgent=True) == 0
    assert skip.frames_to_skip(latency_ms=0, frame_ms=50, motion=0.0) == 2  # nothing is happening: wait longer, save calls
    assert skip.frames_to_skip(latency_ms=100, frame_ms=0) == 0
    assert skip.sample(list(range(100)), 4) == [0, 33, 66, 99] and skip.sample([1, 2], 5) == [1, 2] and skip.sample([1, 2, 3], 1) == [3] and skip.sample([], 3) == []


def test_clock_sync_pauses_while_thinking_and_always_resumes():
    log = []

    class Hook:
        def pause(self):
            log.append("pause")

        def resume(self):
            log.append("resume")

    now = [0.0]
    sync = ClockSync(Hook(), now=lambda: now[0])
    with sync.thinking():
        now[0] += 1.5
    with pytest.raises(RuntimeError):
        with sync.thinking():
            now[0] += 0.5
            raise RuntimeError("the model call failed")
    assert log == ["pause", "resume", "pause", "resume"] and sync.average_ms == pytest.approx(1000.0) and sync.can_pause
    with ClockSync().thinking():  # no hook: only measures
        pass


def test_supervisor_restarts_a_crashed_game_gives_up_on_a_crash_loop_and_resets_cleanly():
    now = [0.0]
    started, stopped = [], []

    class Handle:
        def __init__(self):
            self.up = True

    def launch():
        handle = Handle()
        started.append(handle)
        return handle

    sup = Supervisor(launch, lambda h: h.up, lambda h: (stopped.append(h), setattr(h, "up", False)), max_restarts=2, window_s=10, now=lambda: now[0])
    assert sup.check() == "stopped"
    sup.start()
    assert sup.check() == "running" and sup.uptime == 0.0
    now[0] = 3.0
    started[-1].up = False
    assert sup.check() == "restarted" and len(started) == 2 and sup.uptime == 0.0
    sup.reset()
    assert len(started) == 3 and stopped == [started[1]] and sup.check() == "running"  # a reset is not a crash
    for _ in range(3):  # crashes in quick succession
        now[0] += 1
        started[-1].up = False
        result = sup.check()
    assert result == "failed" and sup.state == "failed" and sup.check() == "failed" and any("gave up" in text for _, text in sup.events)
    sup.shutdown()
    assert sup.state == "stopped"


# ---------- pillar 4: states and goals ----------
def screen(kind, previous=None):
    h, w = 120, 160
    if kind == "loading":
        frame = np.full((h, w, 3), 12, np.uint8)
        frame[100:106, 30:90] = (200, 200, 200)
        return frame
    if kind == "menu":
        frame = np.full((h, w, 3), (50, 60, 110), np.uint8)
        for row in range(4):
            frame[20 + row * 24:36 + row * 24, 40:120] = (200, 200, 220)
            frame[24 + row * 24:32 + row * 24:2, 50:110:3] = (30, 30, 60)
        return frame
    if kind == "gameplay":
        return (RNG.random((h, w, 3)) * 160 + 40).astype(np.uint8)
    if kind == "dead":
        base = (RNG.random((h, w, 3)) * 70).astype(np.uint8)
        base[..., 0] = np.clip(base[..., 0].astype(int) + 120, 0, 255)
        base[..., 1] //= 3
        base[..., 2] //= 3
        return base
    if kind == "victory":
        base = np.full((h, w, 3), (230, 190, 40), np.uint8)
        base[40:80:2, 30:130] = (250, 235, 120)
        return base
    raise AssertionError(kind)


@pytest.mark.parametrize("kind", ["loading", "menu", "gameplay", "dead", "victory"])
def test_state_classifier_knows_the_five_screens_out_of_the_box(kind):
    previous = screen("gameplay") if kind == "gameplay" else None
    state, confidence = StateClassifier().classify(screen(kind), previous)
    assert state == kind and 0.0 <= confidence <= 1.0


def test_state_classifier_adapts_to_a_games_own_look_and_says_when_unsure():
    # this game shows death as a BLUE tint: the built-in centres cannot know; labelled examples teach it
    def blue_death():
        frame = (RNG.random((120, 160, 3)) * 60).astype(np.uint8)
        frame[..., 2] = np.clip(frame[..., 2].astype(int) + 140, 0, 255)
        return frame

    examples = [(screen("gameplay"), "gameplay", screen("gameplay")) for _ in range(6)] + [(blue_death(), "dead", None) for _ in range(6)]
    model = StateClassifier().fit(examples)
    assert model.classify(blue_death())[0] == "dead" and model.classify(screen("gameplay"), screen("gameplay"))[0] == "gameplay"
    with pytest.raises(ValueError):
        StateClassifier().fit([(screen("menu"), "sleeping", None)])
    assert features(screen("menu")).shape == (10,)
    middle = (screen("menu").astype(int) + screen("loading").astype(int)) // 2
    assert StateClassifier().classify(middle.astype(np.uint8))[1] < 0.6  # between two screens: low confidence


def test_goal_checker_matches_words_and_numbers_against_screen_texts_and_objects():
    goal = GoalChecker("Find a sword")
    assert goal.check(["INVENTORY", "Iron Sword x1"]).done
    assert not goal.check(["INVENTORY", "Wooden Shield"]).done
    assert goal.check(["INVENTORY"], objects=["sword"]).done
    assert goal.check(["Iron Swrd"]).done  # one letter lost in the font reading
    level = GoalChecker("reach level 3")
    assert not level.check(["LEVEL 2"]).done and level.check(["LEVEL 3"]).done
    assert level.check(["LEVEL 2"]).missing == ["3"]
    assert not GoalChecker("").check(["anything"]).done


# ---------- the interface ties them together ----------
def test_interface_watches_a_game_and_acts_through_the_guardrails():
    hud = Hud({"hp": Region((0, 0, 100, 8), "bar", (200, 0, 0))})
    interface = Interface(hud=hud, goal="find a sword", card_keys={"w", "a", "d", "space"}, size=(160, 120))
    frame = screen("gameplay")
    frame[0:8, 0:50] = (200, 0, 0)
    first = interface.watch(Image.fromarray(frame))
    second = interface.watch(Image.fromarray(screen("gameplay")))
    assert first.frame.shape == (120, 160, 3) and first.motion == 0.0 and second.motion > 0.5
    assert second.state in ("gameplay", "dead", "menu", "loading", "victory") and second.goal is not None and not second.goal.done
    plan = interface.act("[MOVE_LEFT]&[MOVE_RIGHT] [MOVE_FORWARD] [HOLD(q, 100)]")
    assert [[i.key for i in step] for step in plan.steps] == [["a"], ["w"]] and len(plan.notes) == 2
