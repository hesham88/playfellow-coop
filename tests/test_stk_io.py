"""The SuperTuxKart door's three promises, with a fake SendInput and a fake foreground."""
import pytest

from playfellow_coop.games.stk.io import MENU_KEYS, Hands


def make(front=True):
    sent, state = [], {"front": front}
    hands = Hands(allowed=MENU_KEYS | {"space"}, send=lambda packets: sent.append(packets) or 1, in_front=lambda: state["front"], clock=lambda: 0.0)
    return hands, sent, state


def test_nothing_is_sent_when_the_game_is_not_in_front():
    hands, sent, _ = make(front=False)
    assert hands.down("up") is False
    assert sent == [] and hands.refused == 1 and hands.held == set()


def test_a_key_off_the_allow_list_is_refused_before_anything_goes_out():
    hands, sent, _ = make()
    with pytest.raises(PermissionError):
        hands.down("alt")
    assert sent == []


def test_hold_only_presses_new_keys_and_releases_the_rest():
    hands, sent, _ = make()
    hands.hold_only({"up", "left"})
    hands.hold_only({"up", "right"})
    assert hands.held == {"up", "right"}
    assert [(kind, key) for _, kind, key in hands.audit] == [("down", "left"), ("down", "up"), ("up", "left"), ("down", "right")]


def test_losing_the_front_forgets_held_keys_and_sends_no_key_up_elsewhere():
    hands, sent, state = make()
    hands.hold_only({"up", "space"})
    state["front"] = False
    hands.release_all()
    assert len(sent) == 2 and hands.held == set()


def test_release_all_brings_every_key_up():
    hands, sent, _ = make()
    hands.hold_only({"up", "left", "space"})
    hands.release_all()
    downs = [k for _, kind, k in hands.audit if kind == "down"]
    ups = [k for _, kind, k in hands.audit if kind == "up"]
    assert sorted(downs) == sorted(ups) and hands.held == set()


def test_a_key_up_the_game_missed_is_sent_when_it_is_back_in_front():
    hands, sent, state = make()
    hands.down("up")
    state["front"] = False
    hands.up("up")  # refused: nothing may land in another program
    assert len(sent) == 1 and hands.owed == {"up"}
    state["front"] = True
    hands.settle()
    assert len(sent) == 2 and hands.owed == set()


def test_clear_lets_go_of_every_key_the_game_may_think_is_down():
    hands, sent, _ = make()
    hands.clear()
    assert len(sent) == len(hands.allowed) and hands.held == set()
