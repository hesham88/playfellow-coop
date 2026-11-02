"""Every key a controls card may name has a hardware scan code, so a game read through scan codes never crashes the session on a
card key (found live on 2 Nov: a card's backspace had none)."""
from __future__ import annotations

from controls import KNOWN_KEYS

from playfellow_coop.universal.winio import SCANCODES, key_input


def test_every_known_card_key_has_a_scan_code():
    missing = sorted(k for k in KNOWN_KEYS if k not in SCANCODES)
    assert missing == []


def test_a_known_key_builds_a_keyboard_event():
    for key in ("backspace", "pageup", "f11", ";", "\\\\"[0]):
        key_input(key)
