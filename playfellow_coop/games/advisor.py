"""The models' part for the Endless Sky pack: what is too slow for reflexes but needs judgement. Local code flies and aims; models answer when local code does not know.

  ScreenHelper     Muse with vision: a screen the local reader does not know. It names the screen and one next key from an allow-list, for a stated goal.
  summarise_fight  a fight's numbers, counted locally, for the widget and the log.

The key comes from MODEL_API_KEY, the Windows credential manager or PLAYFELLOW_MODEL_KEY_FILE, in memory only, never printed. Every call passes a
daily budget that stops it before sending; each answer goes in the run's log. A ready helper for the pack's sessions to call when the local
screen reader does not know a screen.
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np

from playfellow_coop.games.stk.paths import HOME, KEY_FILE  # noqa: E402

LEDGER_DIR = HOME.parent / "ledger"  # budgets beside the packs' own folders (~/.playfellow by default)
SCREEN_SYSTEM = ("You look at one screenshot of a single-player game for a program that presses keys. Reply with JSON only: {\"screen\": a short name, \"key\": one key from the "
                 "allowed list that moves toward the goal, or \"none\" if none does, \"why\": ten words at most}. Never choose anything that goes online or quits the game.")


def parse_json(text: str) -> dict:
    """The JSON object in a model's answer, or {} when there is none."""
    match = re.search(r"\{.*\}", text or "", re.S)
    if not match:
        return {}
    try:
        value = json.loads(match.group(0))
    except ValueError:
        return {}
    return value if isinstance(value, dict) else {}


def allowed_key(answer: dict, allowed: frozenset[str]) -> str | None:
    """Only a key on the list ever goes out, whatever the model says."""
    key = str(answer.get("key", "")).strip().lower()
    return key if key in allowed else None


@dataclass
class FightSummary:
    rows: int
    closest: int
    farthest: int
    my_shields: tuple[float, float]
    my_hull: tuple[float, float]
    target_shields: tuple[float, float]
    target_hull: tuple[float, float]
    share_in_range: float


def summarise_fight(rows: list[dict], weapon_range: float) -> FightSummary | None:
    """A fight's log in a few numbers, so a model call costs little."""
    rows = [r for r in rows if r.get("range") is not None]
    if not rows:
        return None
    ranges = [r["range"] for r in rows]
    edge = lambda key: (rows[0][key], rows[-1][key])  # noqa: E731
    return FightSummary(len(rows), min(ranges), max(ranges), edge("shields"), edge("hull"), edge("target_shields"), edge("target_hull"),
                        round(sum(1 for x in ranges if x <= weapon_range) / len(ranges), 2))


class ScreenHelper:  # pragma: no cover - network
    def __init__(self, log: Callable[..., None], cap_usd: float = 1.0):
        from playfellow_coop.budget import DailyBudget
        from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

        from playfellow_coop.games.stk.brains import load_key

        key = load_key(KEY_FILE)
        if not key:
            raise RuntimeError("no model key: run `python -m playfellow_coop keys set`")
        self.brain = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(LEDGER_DIR / "endless-sky-muse-budget.json", cap_usd, 20000), effort="minimal", cache_key=None)
        self.brain.max_tokens = 1000
        self.log = log

    def next_key(self, frame: np.ndarray, goal: str, allowed: frozenset[str], width: int = 800) -> tuple[str | None, dict]:
        import cv2
        from PIL import Image

        h, w = frame.shape[:2]
        small = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
        started = time.monotonic()
        text = self.brain.ask(SCREEN_SYSTEM, f"Goal: {goal}. Allowed keys: {sorted(allowed)}.", [Image.fromarray(np.ascontiguousarray(small[:, :, ::-1]))])
        answer = parse_json(text)
        self.log("muse-screen", goal=goal, answer=answer, seconds=round(time.monotonic() - started, 1))
        return allowed_key(answer, allowed), answer

