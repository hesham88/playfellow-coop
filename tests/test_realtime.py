"""The real-time machinery: hold timing physics, opposite-key cleaning, action chunks with held keys, the state-action memory, the three-loop router, and Windows focus/DPI/scan-code logic
(tested through a fake Windows)."""
from __future__ import annotations

import ctypes
import sys

import numpy as np
import pytest

from playfellow_coop.universal import chunks, hold, winio
from playfellow_coop.universal.cache import StateActionMemory, dhash, hamming, hud_key
from playfellow_coop.universal.tiers import REFLEX, STRATEGIC, TACTICAL, ReactiveOverride, Router, Signals

RNG = np.random.default_rng(5)


# ---- hold timing --------------------------------------------------------------------------------------------------------------------
def test_the_registration_probabilities_follow_the_phase_argument_and_a_tap_that_is_too_short_is_dropped():
    assert hold.seen_probability(5, 60) == pytest.approx(5 / 16.6667, rel=1e-3)  # a 5 ms tap is dropped about two times in three
    assert hold.seen_probability(35, 60) == 1.0 and hold.seen_probability(0, 60) == 0.0
    assert hold.latch_probability(16.6667, 60) == pytest.approx(0.0, abs=1e-4) and hold.latch_probability(25, 60) == pytest.approx(0.5, rel=1e-3) and hold.latch_probability(35, 60) == 1.0
    assert hold.latch_probability(50, 60) == 1.0
    assert hold.minimum_hold_ms(60) == pytest.approx(34.33, abs=0.01) and hold.minimum_hold_ms(30) > hold.minimum_hold_ms(120)
    assert hold.hold_for("tap", 60) == 35 and hold.hold_for("tap", 30) == pytest.approx(hold.minimum_hold_ms(30)) and hold.hold_for("full_jump") == 120
    assert hold.hold_for("full_jump", long=True) == 180 and hold.ENVELOPES["move_chunk"].release_gap_ms == 0
    with pytest.raises(ValueError):
        hold.frame_ms(0)


def test_opposite_directions_are_cleaned_in_the_three_community_modes():
    neutral = hold.SocdCleaner("neutral")
    assert neutral.clean({"left", "right", "w"}) == {"w"} and neutral.clean({"up", "down"}) == set() and neutral.clean({"a", "d", "space"}) == {"space"}
    hitbox = hold.SocdCleaner("hitbox")
    assert hitbox.clean({"left", "right"}) == set() and hitbox.clean({"up", "down"}) == {"up"} and hitbox.clean({"w", "s"}) == {"w"}
    last = hold.SocdCleaner("last_input")
    assert last.clean({"left"}) == {"left"}
    assert last.clean({"left", "right"}) == {"right"}  # right went down last
    assert last.clean({"right"}) == {"right"} and last.clean({"left", "right"}) == {"left"}  # left pressed again while right is held: left is the latest
    with pytest.raises(ValueError):
        hold.SocdCleaner("chaos")


# ---- chunks -------------------------------------------------------------------------------------------------------------------------
ANSWER = "thinking...<|action_start|>12 -4 0; w; w d; w d; w; ; none<|action_end|> done"


def test_a_model_answer_parses_into_chunks_and_a_bad_one_into_nothing():
    got = chunks.parse(ANSWER)
    assert len(got) == 6 and got[0].dx == 12 and got[0].dy == -4 and got[1].dx == 0 and got[1].keys == {"w", "d"} and got[4].keys == frozenset() and got[5].keys == frozenset()
    assert chunks.parse("no block") == [] and chunks.parse(chunks.START + "x y z; w" + chunks.END) == [] and chunks.parse(chunks.START + "99999 0 0; w" + chunks.END) == []
    assert len(chunks.parse(chunks.START + "0 0 0; " + "; ".join(["w"] * 40) + chunks.END)) == chunks.MAX_CHUNKS


def test_a_key_that_persists_is_never_released_between_chunks_and_everything_is_released_at_the_end():
    got = chunks.parse(ANSWER)
    events = chunks.plan(got)
    keys = [(e.kind, e.key) for e in events if e.kind != "move"]
    assert keys.count(("down", "w")) == 1 and keys.count(("up", "w")) == 1  # w goes down once, up once: no stutter-stepping
    assert ("down", "d") in keys and ("up", "d") in keys
    assert events[-1].kind == "up" and not any(e.kind == "down" for e in events if e.t_ms >= 5 * chunks.CHUNK_MS)
    moves = [e for e in events if e.kind == "move"]
    assert sum(e.dx for e in moves) == 12 and sum(e.dy for e in moves) == -4 and max(abs(e.dx) for e in moves) <= 3  # a smooth camera move, not a jump
    assert chunks.mouse_substeps(0, 0, 33.3) == [(0, 0)] * 4 or all(s == (0, 0) for s in chunks.mouse_substeps(0, 0, 33.3))


class Recorder:
    def __init__(self):
        self.calls, self.down = [], set()

    def key_down(self, key):
        self.calls.append(("down", key))
        self.down.add(key)

    def key_up(self, key):
        self.calls.append(("up", key))
        self.down.discard(key)

    def mouse_move(self, dx, dy):
        self.calls.append(("move", dx, dy))


def test_the_executor_plays_on_a_clock_and_always_lets_go_even_when_stopped_or_failing():
    now = [0.0]
    sleeps = []
    backend = Recorder()
    ex = chunks.Executor(backend, clock=lambda: now[0], sleep=lambda ms: (sleeps.append(ms), now.__setitem__(0, now[0] + ms)))
    events = chunks.plan(chunks.parse(ANSWER))
    assert ex.run(events) == len(events) and not backend.down and sum(sleeps) == pytest.approx(events[-1].t_ms, abs=0.5)
    backend, stop = Recorder(), {"n": 0}
    ex = chunks.Executor(backend, clock=lambda: now[0], sleep=lambda ms: now.__setitem__(0, now[0] + ms))

    def should_stop():
        stop["n"] += 1
        return stop["n"] > 2

    ex.run(events, should_stop)
    assert not backend.down  # stopped mid-way with a key held: it was released
    class Broken(Recorder):
        def key_down(self, key):
            super().key_down(key)
            raise RuntimeError("driver error")
    broken = Broken()
    with pytest.raises(RuntimeError):
        chunks.Executor(broken, clock=lambda: now[0], sleep=lambda ms: now.__setitem__(0, now[0] + ms)).run(events)
    assert not broken.down


# ---- state-action memory ------------------------------------------------------------------------------------------------------------
def picture(seed):
    return (np.random.default_rng(seed).random((72, 128, 3)) * 255).astype(np.uint8)


def test_a_repeated_situation_is_answered_from_memory_after_it_worked_and_forgotten_when_it_stops_working():
    memory = StateActionMemory(max_distance=4, min_trust=0.7)
    a = picture(1)
    assert memory.lookup(a, {"hp": 0.83}) is None
    for _ in range(3):
        memory.record(a, {"hp": 0.83}, "RIGHT", worked=True)
    assert memory.lookup(a, {"hp": 0.84}) == "RIGHT"  # same screen, health in the same tenth
    assert memory.lookup(a, {"hp": 0.3}) is None and memory.lookup(picture(2), {"hp": 0.83}) is None
    for _ in range(6):
        memory.record(a, {"hp": 0.83}, "RIGHT", worked=False)
    assert memory.lookup(a, {"hp": 0.83}) is None  # trust fell: ask the model again
    assert memory.hit_rate > 0 and len(memory) == 1
    memory.clear()
    assert len(memory) == 0


def test_the_memory_is_bounded_hashes_are_stable_and_nearby_pictures_match():
    memory = StateActionMemory(capacity=3)
    for i in range(6):
        memory.record(picture(i), None, "A", True)
    assert len(memory) == 3
    base = picture(9)
    noisy = np.clip(base.astype(int) + RNG.integers(-2, 3, base.shape), 0, 255).astype(np.uint8)
    assert dhash(base) == dhash(base) and hamming(dhash(base), dhash(noisy)) <= 6 and hamming(dhash(base), dhash(picture(10))) > 12
    assert hud_key({"hp": 0.83, "name": "x"}) == hud_key({"hp": 0.84, "name": "x"}) and hud_key(None) == ()


# ---- router -------------------------------------------------------------------------------------------------------------------------
def test_stable_play_stays_on_the_reflex_loop_and_events_wake_the_tactical_one_with_a_cooldown_and_a_calm_return():
    router = Router(stall_ticks=30, calm_ticks=20, tactical_cooldown=5, strategic_cooldown=40)
    tiers = [router.observe(Signals(progress_delta=1.0)).tier for _ in range(20)]
    assert set(tiers) == {REFLEX}
    d = router.observe(Signals(novelty=0.8, progress_delta=1.0))
    assert d.tier == TACTICAL and "novelty" in d.reasons and d.changed
    for _ in range(19):
        assert router.observe(Signals(progress_delta=1.0)).tier == TACTICAL  # stays awake until play has been calm for a while
    assert router.observe(Signals(progress_delta=1.0)).tier == REFLEX
    stalled = [router.observe(Signals(progress_delta=0.0)).tier for _ in range(35)]
    assert TACTICAL in stalled
    assert "skill_fault" in Router().observe(Signals(skill_fault=True, progress_delta=1.0)).reasons


def test_repeated_tactical_failures_and_the_end_of_a_game_wake_the_strategic_loop_but_not_more_often_than_the_cooldown():
    router = Router(tactical_cooldown=1, strategic_cooldown=10, failures_before_strategic=3, stall_ticks=2)
    seen = []
    for _ in range(40):
        seen.append(router.observe(Signals(progress_delta=0.0, tactical_failed=True)).tier)
    assert STRATEGIC in seen and seen.count(STRATEGIC) <= 5
    ended = Router(strategic_cooldown=0).observe(Signals(ended=True, progress_delta=1.0))
    assert ended.tier == STRATEGIC and "ended" in ended.reasons
    assert abs(sum(router.share().values()) - 1.0) < 1e-9


def test_the_reactive_override_flushes_on_a_close_threat_or_a_motion_spike():
    override = ReactiveOverride(danger_distance=0.12, flow_spike=0.5)
    assert override.should_flush(0.05) and override.should_flush(None, flow_level=0.7) and not override.should_flush(0.4, 0.1) and not override.should_flush(None)


# ---- Windows ------------------------------------------------------------------------------------------------------------------------
class FakeApi:
    def __init__(self, foreground=5, iconic=False, locked=True):
        self.fg, self.iconic, self.locked, self.calls = foreground, iconic, locked, []
        self.threads = {5: 100, 7: 200}
        self.levels = {None: 0x2000, 7: 0x2000}
        self.attached = False
        self.alt = False

    def set_dpi_awareness(self, context):
        self.calls.append(("dpi", context))
        return True

    def client_size(self, hwnd):
        return 1280, 720

    def client_to_screen(self, hwnd, point):
        return 310 + point[0], 76 + point[1]  # a window with a title bar and a border

    def screen_size(self):
        return 1920, 1080

    def foreground(self):
        return self.fg

    def is_iconic(self, hwnd):
        return self.iconic

    def restore(self, hwnd):
        self.iconic = False
        self.calls.append(("restore", hwnd))

    def thread_of(self, hwnd):
        return self.threads.get(hwnd, 0)

    def current_thread(self):
        return 300

    def attach(self, current, other, on):
        self.attached = on
        self.calls.append(("attach", on))
        return True

    def tap_alt(self):
        self.alt = True
        self.calls.append(("alt",))

    def bring_up(self, hwnd):
        # Windows only grants the foreground when the foreground lock is satisfied: attached AND a recent key tap
        if not self.locked or (self.attached and self.alt):
            self.fg = hwnd
        self.calls.append(("bring_up", hwnd))

    def pin_topmost(self, hwnd):
        self.calls.append(("pin", hwnd))

    def integrity_level(self, hwnd):
        return self.levels.get(hwnd, 0x2000)


def test_dpi_awareness_is_set_per_monitor_v2_and_coordinates_land_inside_the_physical_client_area():
    api = FakeApi()
    assert winio.set_dpi_awareness(api) and api.calls[0] == ("dpi", -4)
    rect = winio.client_rect(api, 7)
    assert rect == (310, 76, 1590, 796)
    assert winio.model_to_pixel(0, 0, rect) == (310, 76) and winio.model_to_pixel(1000, 1000, rect) == (1589, 795) and winio.model_to_pixel(2000, -5, rect) == (1589, 76)
    cx, cy = winio.model_to_pixel(500, 500, rect)
    assert 949 <= cx <= 950 and 435 <= cy <= 436
    assert winio.to_absolute(0, 0, 1920, 1080) == (0, 0) and winio.to_absolute(1919, 1079, 1920, 1080) == (65535, 65535) and 32780 <= winio.to_absolute(960, 540, 1920, 1080)[0] <= 32790


def test_the_focus_lock_attaches_taps_alt_brings_the_window_up_and_always_detaches():
    api = FakeApi()
    lock = winio.FocusLock(api, pin=True)
    assert lock.ensure(7) and api.fg == 7 and lock.log == ["attach", "detach"] and ("pin", 7) in api.calls and api.attached is False
    assert winio.FocusLock(FakeApi(foreground=7)).ensure(7)  # already in front: nothing to do
    api = FakeApi(iconic=True)
    lock = winio.FocusLock(api)
    assert lock.ensure(7) and lock.log[0] == "restore"
    api = FakeApi()
    api.bring_up = lambda hwnd: (_ for _ in ()).throw(RuntimeError("window vanished"))
    with pytest.raises(RuntimeError):
        winio.FocusLock(api).ensure(7)
    assert api.attached is False  # detached even though the call failed


def test_input_to_a_more_privileged_window_is_reported_before_it_is_silently_dropped():
    api = FakeApi()
    assert winio.integrity_ok(api, 7)
    api.levels[7] = 0x3000
    assert not winio.integrity_ok(api, 7)


def test_scan_code_packets_have_the_right_size_flags_and_extended_keys():
    assert ctypes.sizeof(winio.INPUT) == (40 if sys.maxsize > 2 ** 32 else 28)
    down, up = winio.key_input("w"), winio.key_input("w", up=True)
    assert down.type == winio.INPUT_KEYBOARD and down.ki.wScan == 0x11 and down.ki.wVk == 0 and down.ki.dwFlags == winio.KEYEVENTF_SCANCODE
    assert up.ki.dwFlags == winio.KEYEVENTF_SCANCODE | winio.KEYEVENTF_KEYUP
    arrow = winio.key_input("up")
    assert arrow.ki.wScan == 0x48 and arrow.ki.dwFlags & winio.KEYEVENTF_EXTENDEDKEY
    with pytest.raises(KeyError):
        winio.key_input("banana")
    sent = []
    backend = winio.ScanBackend(lambda packets: sent.append(packets) or len(packets))
    backend.key_down("shift")
    backend.key_up("shift")
    backend.mouse_move(3, -2)
    backend.mouse_absolute(960, 540, 1920, 1080)
    backend.click()
    backend.click(right=True)
    backend.wheel(-2)
    flat = [p for group in sent for p in group]
    assert flat[2].mi.dx == 3 and flat[2].mi.dy == -2 and flat[2].mi.dwFlags == winio.MOUSEEVENTF_MOVE
    assert flat[3].mi.dwFlags == winio.MOUSEEVENTF_MOVE | winio.MOUSEEVENTF_ABSOLUTE and flat[4].mi.dwFlags == winio.MOUSEEVENTF_LEFTDOWN and flat[5].mi.dwFlags == winio.MOUSEEVENTF_LEFTUP
    assert flat[6].mi.dwFlags == winio.MOUSEEVENTF_RIGHTDOWN and flat[-1].mi.dwFlags == winio.MOUSEEVENTF_WHEEL and ctypes.c_long(flat[-1].mi.mouseData).value in (-240, 4294967056)


def test_a_drag_follows_a_curve_to_exactly_the_end_point_and_the_precise_sleep_spins_for_the_tail():
    path = winio.bezier_path((100, 100), (500, 300), steps=10)
    assert len(path) == 10 and path[-1] == (500, 300) and path != [(round(100 + 40 * i), round(100 + 20 * i)) for i in range(1, 11)]
    assert all(path[i][0] <= path[i + 1][0] for i in range(9))
    now = [0.0]
    slept = []

    def clock():
        now[0] += 0.05  # every read of the clock costs 0.05 ms
        return now[0]

    winio.precise_sleep(10.0, clock=clock, sleep=lambda s: (slept.append(s), now.__setitem__(0, now[0] + s * 1000.0)), spin_ms=1.5)
    assert slept == [pytest.approx(0.0085)] and now[0] >= 10.0 and now[0] < 11.0  # a coarse sleep for all but the last 1.5 ms, then a spin to the target
