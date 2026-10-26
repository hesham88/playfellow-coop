"""The summon key: registered with Windows' own RegisterHotKey (no global keyboard hook, so it cannot swallow other keys or lag the
game), and refused if the game's controls card uses that key. The default is Ctrl+Alt+P."""
from __future__ import annotations

import ctypes

MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN, MOD_NOREPEAT = 0x1, 0x2, 0x4, 0x8, 0x4000
MODIFIERS = {"alt": MOD_ALT, "ctrl": MOD_CONTROL, "control": MOD_CONTROL, "shift": MOD_SHIFT, "win": MOD_WIN}
SPECIAL = {**{f"f{n}": 0x6F + n for n in range(1, 25)}, "space": 0x20, "enter": 0x0D, "esc": 0x1B, "tab": 0x09, "up": 0x26, "down": 0x28,
           "left": 0x25, "right": 0x27}
DEFAULT = "ctrl+alt+p"
RESERVED = {"f9": "the hand-over key", "f12": "the stop key"}  # a summon key may never take these


class HotkeyError(ValueError):
    """A key the player cannot use, said in plain words."""


def parse(text: str) -> tuple[int, int, str]:
    """"ctrl+alt+p" -> (modifier bits, virtual-key code, the plain key name). At least one modifier is required for a letter key."""
    parts = [piece.strip().lower() for piece in (text or "").split("+") if piece.strip()]
    if not parts:
        raise HotkeyError("choose a key, for example ctrl+alt+p")
    *mods, key = parts
    bits = 0
    for mod in mods:
        if mod not in MODIFIERS:
            raise HotkeyError(f"unknown modifier {mod!r}: use ctrl, alt, shift or win")
        bits |= MODIFIERS[mod]
    if key in SPECIAL:
        code = SPECIAL[key]
    elif len(key) == 1 and key.isascii() and key.isalnum():
        code = ord(key.upper())
    else:
        raise HotkeyError(f"unknown key {key!r}")
    if len(key) == 1 and not bits:
        raise HotkeyError("a letter or number needs ctrl, alt or shift with it, so typing is never swallowed")
    return bits, code, key


def refuse_if_game_key(key: str, card) -> None:
    """The summon key must not be one the active controls card presses (the card's keys are what the game is played with)."""
    used = {k.lower() for action in getattr(card, "actions", {}).values() for k in action.keys}
    if key in used:
        raise HotkeyError(f"{key.upper()} is a key this game uses, so it can't summon the panel; choose another")
    if key in RESERVED:
        raise HotkeyError(f"{key.upper()} is {RESERVED[key]}; choose another")


class Hotkey:
    """One registered summon key. register() raises if Windows says the combination is already taken."""

    def __init__(self, text: str, card=None, user32=None, hotkey_id: int = 0x5046):
        self.bits, self.code, self.key = parse(text)
        if card is not None:
            refuse_if_game_key(self.key, card)
        self._api = user32 or ctypes.windll.user32
        self._id = hotkey_id
        self.registered = False

    def register(self, hwnd: int | None = None) -> None:
        if not self._api.RegisterHotKey(hwnd, self._id, self.bits | MOD_NOREPEAT, self.code):
            raise HotkeyError("another program already uses that key combination; choose another")
        self.registered = True

    def unregister(self, hwnd: int | None = None) -> None:
        if self.registered:
            self._api.UnregisterHotKey(hwnd, self._id)
            self.registered = False
