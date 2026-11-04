"""The controls card, from the game's own keys.txt (SDL key codes): the keys the player really has bound."""
from __future__ import annotations

import re
from pathlib import Path

KEYS_FILE = Path(r"F:\Program Files\Endless Sky\keys.txt")
SDL = {1073741906: "up", 1073741904: "left", 1073741903: "right", 1073741905: "down", 27: "esc", 9: "tab", 32: "space", 13: "enter",
       1073741882: "f1", 1073741884: "f3", 1073741892: "f11", 1073742050: "alt", 1073741881: "capslock", 47: "/"}
#: the actions the skills use, by the names keys.txt gives them
ACTIONS = {"thrust": "Forward thrust", "left": "Turn left", "right": "Turn right", "reverse": "Reverse", "autosteer": "Auto steer",
           "fire": "Fire primary weapon", "fire2": "Fire secondary weapon", "select2": "Select secondary weapon", "land": "Land on planet / station",
           "board": "Board selected ship", "talk": "Talk to selected ship", "scan": "Scan selected ship", "jump": "Initiate hyperspace jump",
           "next": "Select next ship", "hostile": "Select nearest hostile ship", "asteroid": "Select nearest asteroid", "afterburner": "Fire afterburner",
           "map": "View star map", "info": "View player info", "pause": "Pause", "menu": "Show main menu", "fight": "Fleet: Fight my target", "gather": "Fleet: Gather around me"}


def key_name(code: int) -> str:
    if code in SDL:
        return SDL[code]
    if 32 < code < 127:
        return chr(code)
    raise KeyError(f"no key name for SDL code {code}")


def read_card(text: str) -> dict[str, str]:
    bound = {m.group(1): int(m.group(2)) for m in re.finditer(r'"([^"]+)"\s+(\d+)', text)}
    return {action: key_name(bound[label]) for action, label in ACTIONS.items() if label in bound}


def load_card(path: Path = KEYS_FILE) -> dict[str, str]:
    return read_card(Path(path).read_text(encoding="utf-8"))
