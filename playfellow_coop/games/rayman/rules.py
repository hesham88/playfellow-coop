"""Rayman Legends (PC): the moves as key recipes and the goals as numbers, from the 4 Nov research (sources and confidence in SKILLS.md) and the 15 Oct live notes.

Keys follow the PC defaults found (arrows move, Space jumps and holds to hover, S attacks and holds to charge, Left Shift runs, W is Murfy's action, Backspace back, Esc pause).
The Legends layout is only medium confidence (Origins manual + a search summary; the live run of 15 Oct confirmed Space, S and W): `confirm_keys` must read the game's Controls
screen before any move is trusted. Timings are first guesses to tune on the game, never claimed as measured.
"""
from __future__ import annotations

from dataclasses import dataclass

KEYS = {"left": "left", "right": "right", "up": "up", "down": "down", "jump": "space", "attack": "s", "run": "shift", "murfy": "w", "murfy_left": "q", "murfy_right": "e", "back": "backspace", "pause": "esc"}
CONFIRMED_LIVE = {"jump", "attack", "murfy", "back"}  # seen in the game's own prompts on 15 Oct


@dataclass(frozen=True)
class Step:
    """Hold `keys` for `seconds`, then let go of all of them."""

    keys: frozenset[str]
    seconds: float


def _s(*keys: str, t: float) -> Step:
    return Step(frozenset(KEYS[k] for k in keys), t)


def recipe(move: str, facing: str = "right") -> list[Step]:
    """Key steps for a move. Facing is the direction of travel."""
    go = facing
    recipes = {
        "short_jump": [_s(go, "jump", t=0.08)],
        "full_jump": [_s(go, "jump", t=0.35)],
        "hover": [_s(go, "jump", t=0.35), _s(go, "jump", t=1.2)],  # hold jump on the way down
        "run": [_s(go, "run", t=0.8)],
        "dash_attack": [_s(go, "run", t=0.4), _s(go, "run", "attack", t=0.1)],  # attack while running
        "jump_cancel_dash": [_s(go, "run", "attack", t=0.1), _s(go, "run", "jump", t=0.12)],  # jump out of the dash on landing
        "crush": [_s(go, "jump", t=0.35), _s("down", "attack", t=0.1)],  # down + attack in the air
        "roll_jump": [_s(go, "run", "down", t=0.3), _s(go, "run", "jump", t=0.3)],
        "wall_jump": [_s(go, "jump", t=0.3), _s("left" if go == "right" else "right", "jump", t=0.3)],
        "charged_punch": [_s("attack", t=0.9)],
        "murfy": [_s("murfy", t=0.1)],
    }
    if move not in recipes:
        raise KeyError(f"no recipe for {move!r}")
    return recipes[move]


def cup_targets(level_max: int) -> dict[str, int]:
    """Lums needed for each cup on the level-end gauge: bronze 25%, silver 50%, lucky ticket 75%, gold 100% of the level's total (600, 300 or 100)."""
    return {"bronze": level_max // 4, "silver": level_max // 2, "ticket": level_max * 3 // 4, "gold": level_max}


def cup_for(lums: int, level_max: int) -> str:
    best = "none"
    for name, need in cup_targets(level_max).items():
        if lums >= need:
            best = name
    return best


INVADED_ROCKETS = (40.0, 50.0, 60.0)  # seconds: each holds a Teensy; finish before a launch to save it (one hit, no checkpoints)


def invaded_saved(seconds: float) -> int:
    return sum(1 for launch in INVADED_ROCKETS if seconds < launch)


PRINCESS_UNLOCKS = (15, 35, 55, 60, 90, 115, 155, 170, 230, 290)  # Teensies freed
LIVING_DEAD_PARTY = 400
TEENSIES_TOTAL_PC = 700


def unlocked_princesses(teensies: int) -> int:
    return sum(1 for need in PRINCESS_UNLOCKS if teensies >= need)


def teensies_per_level(kind: str) -> int:
    """Regular levels hold 10 (8 + King and Queen behind hidden doors); invaded, music and others 3."""
    return 10 if kind == "regular" else 3


def next_goal(teensies: int) -> str:
    if teensies < PRINCESS_UNLOCKS[-1]:
        need = next(n for n in PRINCESS_UNLOCKS if n > teensies)
        return f"free {need - teensies} more Teensies for the next princess"
    if teensies < LIVING_DEAD_PARTY:
        return f"free {LIVING_DEAD_PARTY - teensies} more Teensies to open Living Dead Party"
    return f"{TEENSIES_TOTAL_PC - teensies} Teensies left to free"
