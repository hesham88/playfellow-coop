"""The controls card, read from the game's own input.xml (the bindings the player really has), not assumed.

input.xml stores each action as an Irrlicht key code (the Windows virtual-key numbers). The card maps every game action to
the key name the guarded door can press, and back: when an on-screen instruction names a key ("press <Backspace>"), the
buddy looks it up here to learn which action it means, and refuses a key the card does not have.
"""
from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

try:
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET

DEFAULT_INPUT = Path.home() / "AppData" / "Roaming" / "supertuxkart" / "config-0.10" / "input.xml"

VK_NAMES = {8: "backspace", 9: "tab", 13: "enter", 27: "esc", 32: "space", 37: "left", 38: "up", 39: "right", 40: "down",
            16: "shift", 17: "ctrl", 160: "shift", 162: "ctrl", 46: "delete", 45: "insert", 36: "home", 35: "end", 33: "pageup", 34: "pagedown"}
VK_NAMES.update({c: chr(c).lower() for c in range(ord("A"), ord("Z") + 1)})
VK_NAMES.update({c: chr(c) for c in range(ord("0"), ord("9") + 1)})
# the words the game itself writes between < > in its messages
SCREEN_WORDS = {"up": "up", "down": "down", "left": "left", "right": "right", "space": "space", "backspace": "backspace",
                "enter": "enter", "return": "enter", "escape": "esc", "esc": "esc", "tab": "tab"}
RACE_ACTIONS = ("steerLeft", "steerRight", "accel", "brake", "nitro", "drift", "rescue", "fire", "lookBack")


@dataclass
class Card:
    keys: dict[str, str]  # game action -> key name

    @classmethod
    def from_xml(cls, text: str, config: str = "keyboard", index: int = 0) -> "Card":
        root = ET.fromstring(text)
        boards = [node for node in root if node.tag == config]
        if len(boards) <= index:
            raise LookupError(f"input.xml has no {config} configuration number {index + 1}")
        keys = {}
        for action in boards[index].iter("action"):
            if action.get("event") == "1":
                name = VK_NAMES.get(int(action.get("id")))
                if name:
                    keys[action.get("name")] = name
        return cls(keys)

    @classmethod
    def load(cls, path: Path = DEFAULT_INPUT, index: int = 0) -> "Card":
        return cls.from_xml(path.read_text(encoding="utf-8"), index=index)

    def action_for_screen_key(self, word: str) -> str | None:
        """The race action a key named on screen ("<Backspace>", "<V>") is bound to, or None if the card has no such key."""
        word = word.strip().strip("<>").strip().lower()
        key = SCREEN_WORDS.get(word, word if len(word) == 1 else None)
        if key is None:
            return None
        for action in RACE_ACTIONS:
            if self.keys.get(action) == key:
                return action
        return None

    def race_keys(self) -> frozenset[str]:
        return frozenset(self.keys[a] for a in RACE_ACTIONS if a in self.keys)
