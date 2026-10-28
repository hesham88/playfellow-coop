"""The engine's own hands pressing scan codes: same cards, same safety rules, different packets."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

import controls
from hands import CornerStop, Hands, Step

from playfellow_coop.universal import winio
from playfellow_coop.universal.scan_backend import DirectInputCompat, FailSafeException

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
CARD = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")


class Box:
    left, top, width, height = 0, 0, 440, 504


def make(cursor=lambda: (500, 500)):
    sent = []
    backend = DirectInputCompat(send=lambda packets: sent.append(list(packets)) or len(packets), cursor=cursor, screen=(1920, 1080))
    hands = Hands(CARD, backend=backend, sleep=lambda s: None, in_front=lambda: True, get_box=lambda: Box())
    return hands, backend, [p for group in sent for p in group], sent


def flat(sent):
    return [p for group in sent for p in group]


def test_a_card_key_becomes_a_scan_code_down_and_up_through_the_engines_own_hands():
    hands, backend, _, sent = make()
    name = next(n for n, a in CARD.actions.items() if getattr(a, "keys", None) and a.keys[0] == "up")
    hands.do(Step(name), Box())
    packets = flat(sent)
    assert packets and all(p.type == winio.INPUT_KEYBOARD for p in packets)
    downs = [p for p in packets if not p.ki.dwFlags & winio.KEYEVENTF_KEYUP]
    ups = [p for p in packets if p.ki.dwFlags & winio.KEYEVENTF_KEYUP]
    assert downs and ups and downs[0].ki.wScan == 0x48 and downs[0].ki.dwFlags & winio.KEYEVENTF_EXTENDEDKEY and downs[0].ki.wVk == 0  # the up arrow, a hardware scan code


def test_every_held_key_can_always_let_go_even_with_the_mouse_in_the_corner():
    hands, backend, _, sent = make(cursor=lambda: (0, 0))
    with pytest.raises(FailSafeException):
        backend.keyDown("left")  # the corner fail-safe refuses new input
    backend.keyUp("left")  # but a release always goes through
    assert flat(sent)[-1].ki.dwFlags & winio.KEYEVENTF_KEYUP
    name = next(n for n, a in CARD.actions.items() if getattr(a, "keys", None))
    with pytest.raises(CornerStop):
        hands.do(Step(name), Box())  # the engine turns the exception into its normal stop


def test_the_mouse_surface_the_engine_uses_maps_to_absolute_relative_and_button_packets():
    _, backend, _, sent = make()
    backend.moveTo(960, 540)
    backend.moveRel(5, -3)
    backend.click(100, 200, button="right")
    backend.mouseDown("left")
    backend.mouseUp("left")
    packets = flat(sent)
    assert packets[0].mi.dwFlags == winio.MOUSEEVENTF_MOVE | winio.MOUSEEVENTF_ABSOLUTE and 32780 <= packets[0].mi.dx <= 32790
    assert packets[1].mi.dwFlags == winio.MOUSEEVENTF_MOVE and (packets[1].mi.dx, packets[1].mi.dy) == (5, -3)
    assert packets[3].mi.dwFlags == winio.MOUSEEVENTF_RIGHTDOWN and packets[4].mi.dwFlags == winio.MOUSEEVENTF_RIGHTUP
    assert packets[5].mi.dwFlags == winio.MOUSEEVENTF_LEFTDOWN and packets[6].mi.dwFlags == winio.MOUSEEVENTF_LEFTUP and backend.position() == (500, 500)
