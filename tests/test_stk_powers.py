"""When each power is used: the rules, and the readers on made-up pictures. No game, no window."""
import numpy as np
import pytest

pytest.importorskip("cv2")

import cv2  # noqa: E402

from playfellow_coop.games.stk.held import HeldPower, read_place  # noqa: E402
from playfellow_coop.games.stk.items import Seen  # noqa: E402
from playfellow_coop.games.stk.powers import HOLD_LIMIT, Moment, decide  # noqa: E402


def kart(x=0.5, y=0.5):
    return Seen("kart", x, y, 0.0)


def fire(**kw):
    kw.setdefault("charges", 1)
    kw.setdefault("karts_ahead", [])
    return decide(Moment(**kw))


def test_nothing_held_nothing_fired():
    assert fire(power=None)[0] is False


def test_a_weapon_is_not_thrown_with_nobody_there():
    for power in ("bowling", "cake", "plunger", "swatter", "bubblegum"):
        assert fire(power=power)[0] is False


def test_bowling_needs_an_opponent_lined_up_close_and_no_bend():
    assert fire(power="bowling", karts_ahead=[kart(0.5, 0.5)])[0] is True
    assert fire(power="bowling", karts_ahead=[kart(0.8, 0.5)])[0] is False  # off to the side
    assert fire(power="bowling", karts_ahead=[kart(0.5, 0.3)])[0] is False  # too far
    assert fire(power="bowling", karts_ahead=[kart(0.5, 0.5)], bend=1.0)[0] is False  # it rolls straight


def test_cake_homes_in_so_any_opponent_ahead_will_do():
    assert fire(power="cake", karts_ahead=[kart(0.8, 0.3)])[0] is True


def test_zipper_only_on_a_straight():
    assert fire(power="zipper", bend=0.1)[0] is True
    assert fire(power="zipper", bend=0.8)[0] is False


def test_swatter_needs_a_kart_within_reach():
    assert fire(power="swatter", karts_ahead=[kart(0.5, 0.6)])[0] is True
    assert fire(power="swatter", karts_ahead=[kart(0.5, 0.45)])[0] is False


def test_powers_that_hit_the_leader_are_kept_while_leading():
    for power in ("parachute", "anchor", "rubber_ball"):
        assert fire(power=power, place=2)[0] is True
        assert fire(power=power, place=1)[0] is False


def test_switch_waits_for_a_banana():
    assert fire(power="switch")[0] is False
    assert fire(power="switch", banana_in_path=True)[0] is True


def test_a_power_held_too_long_is_used_so_the_next_gift_counts():
    assert fire(power="bowling", held_for=HOLD_LIMIT + 1)[0] is True
    shot, backwards, _ = fire(power="bowling", held_for=HOLD_LIMIT + 1, place=1)
    assert shot and backwards  # leading: behind is where the others are


def test_no_two_shots_at_once():
    assert fire(power="cake", karts_ahead=[kart()], since_last=0.5)[0] is False


def draw_list(rows=4, mine=2, h=1000, w=958):
    frame = np.full((h, w, 3), 90, dtype=np.uint8)
    for r in range(rows):
        y = int(h * (0.043 + 0.06 * r))
        cv2.circle(frame, (28, y), 16, (200, 200, 200), -1)
        if r + 1 == mine:
            cv2.circle(frame, (28, y), 20, (0, 0, 255), 3)
    return frame


@pytest.mark.parametrize("place", [1, 2, 3, 4])
def test_the_place_is_read_from_the_ring_in_the_list(place):
    assert read_place(draw_list(mine=place)) == place


def test_no_ring_no_place():
    assert read_place(np.full((1000, 958, 3), 90, dtype=np.uint8)) is None


def test_a_missing_icon_file_means_no_reading_not_a_crash(tmp_path):
    assert HeldPower(tmp_path).read(np.zeros((1000, 958, 3), dtype=np.uint8)) == (None, 0)
