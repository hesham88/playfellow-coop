"""Which screen is up. A fast look says whether the flight view is uncovered; for anything else a local text reader reads the screen (menus
pause the game, so a few seconds a read costs nothing)."""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from playfellow_coop.games.endless_sky.hud import is_bright


@dataclass
class Line:
    text: str
    x: int
    y: int


@dataclass
class View:
    name: str  # flight, conversation, dialog, planet, jobs, shipyard, outfitter, map, menu, start, unknown
    lines: list[Line]

    def has(self, *words: str) -> bool:
        joined = " ".join(l.text for l in self.lines).lower()
        return all(w.lower() in joined for w in words)


def selected_model(lines: list[Line]) -> str:
    """The shipyard's detail column names the selected ship on the line 'model:'; the names in the list are always on screen and say nothing."""
    for line in lines:
        low = line.text.lower().strip()
        if low.startswith("model"):
            rest = low.split(":", 1)[1].strip() if ":" in low else ""
            if rest:
                return rest
            same_row = [o for o in lines if o is not line and abs(o.y - line.y) <= 8 and o.x > line.x]
            if same_row:
                return min(same_row, key=lambda o: o.x).text.strip().lower()
    return ""


def bounty_line(lines: list[Line]) -> Line | None:
    """A bounty on the job board: the game names them 'Wanted ...' (data/human/jobs.txt)."""
    return next((l for l in lines if "wanted" in l.text.lower()), None)


def conversation_panel(frame: np.ndarray) -> bool:
    """The conversation sheet: an even grey block down the left side, below the text."""
    h = frame.shape[0]
    strip = frame[h - int(h * 0.25):h - 8, 8:500]
    if strip.size == 0:
        return False
    return bool((np.abs(strip.astype(int) - 32).max(axis=2) <= 6).mean() > 0.7)


def centre_panel(frame: np.ndarray) -> bool:
    h, w = frame.shape[:2]
    patch = frame[h // 2 - 60:h // 2 + 60, w // 2 - 118:w // 2 + 118].astype(int)
    return bool((np.abs(patch - 32).max(axis=2) <= 8).mean() > 0.45)


def classify(frame: np.ndarray, lines: list[Line]) -> View:
    text = " ".join(l.text for l in lines).lower()
    lit = is_bright(frame)
    words = {w.strip("[]().,:") for w in text.split()}
    if conversation_panel(frame):  # a conversation can open over the planet, whose buttons still read through it
        return View("conversation", lines)
    if not lit and centre_panel(frame) and words & {"ok", "cancel", "yes", "no", "accept", "buy", "decline", "random"}:
        return View("dialog", lines)
    if "depart" in words and {"shipyard", "outfitter", "bank", "spaceport", "trading", "job", "jobs", "hire"} & words:
        return View("planet", lines)  # the landed screen keeps the HUD lit behind it
    if lit and ("navigation" in text or "no target" in text):
        return View("flight", lines)
    if "start game" in text:
        return View("start", lines)
    if "new pilot" in text or "enter ship" in text or "load / save" in text or "you have died" in text or "welcome to endless sky" in text:
        return View("menu", lines)
    if "you have" in text and "leave" in words:
        return View("shipyard" if "sell hull" in text or "your ships" in text else "outfitter", lines)
    if "available jobs" in text or "accepted missions" in text or ("accept" in words and "jobs" in words):
        return View("jobs", lines)
    if "done" in words and words & {"find", "government", "systems", "ports", "stars", "shipyards"}:
        return View("map", lines)
    return View("unknown", lines)
