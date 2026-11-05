"""The menu pre-skill: reach a goal in the game's menus with the keyboard, checking the screen at every step.

Blind key counts break as soon as the focus starts somewhere else (on 3 November "Down, Left x5" opened High Scores instead
of the tutorial). Here each step is: look at the screen (a small screenshot to the vision model, which says which screen
this is, what is focused, and which ONE menu key moves toward the goal), check the answer locally, press that one key.

Local rules the model cannot overrule: only menu keys (arrows, Enter, Esc); Enter is refused while Online, Addons or anything
networked is focused or on screen (offline play only); at most `max_steps` presses; the goal check is the model's "done"
confirmed by the caller's own test where there is one (the race view is confirmed by the minimap, not by the model).
"""
from __future__ import annotations

import json
import re
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

KEYS = ("up", "down", "left", "right", "enter", "esc")
FORBIDDEN = re.compile(r"online|addon|network|server|login|log in|sign in|register|account", re.I)

SYSTEM = ("You help a player move through the menus of the racing game SuperTuxKart with the keyboard only. You see one screenshot. "
          "Reply with JSON only: {\"screen\": short name of this screen, \"focused\": the exact label of the focused (highlighted) "
          "button or item, or its tooltip for icon buttons, \"press\": ONE of up, down, left, right, enter, esc, or none, "
          "\"done\": true if the goal is already reached, \"why\": a few words}. The arrow keys move the focus, enter activates the "
          "focused item, esc goes back. Never choose enter on anything about Online, Addons, servers or accounts.")


@dataclass
class Step:
    screen: str
    focused: str
    press: str
    done: bool
    why: str
    refused: str = ""


def parse_step(answer: str) -> Step:
    match = re.search(r"\{.*\}", answer, re.S)
    data = json.loads(match.group(0)) if match else {}
    press = str(data.get("press", "none")).strip().lower()
    return Step(str(data.get("screen", ""))[:60], str(data.get("focused", ""))[:60], press if press in KEYS else "none",
                bool(data.get("done", False)), str(data.get("why", ""))[:80])


def check(step: Step) -> Step:
    """The local rules: an Enter that would open anything networked is refused."""
    if step.press == "enter" and (FORBIDDEN.search(step.focused) or FORBIDDEN.search(step.screen)):
        step.refused = f"refused Enter on '{step.focused}' ({step.screen}): offline play only"
        step.press = "esc" if FORBIDDEN.search(step.screen) else "none"
    return step


BAR = ("options", "help", "tutorial", "high scores", "achievements", "grand prix editor", "about", "quit")
LABEL_SYSTEM = ("You see a small crop of a SuperTuxKart menu screen (a tooltip above the main menu's icon bar, or the caption "
                "under a grid of choices). Reply with JSON only: {\"label\": the words written in it, or \"\" if there are none}.")


def bar_index(label: str) -> int | None:
    label = label.strip().lower()
    for i, name in enumerate(BAR):
        if name in label or (label and label in name and len(label) > 3):
            return i
    return None


def walk_bar(target: str, look: Callable[[], np.ndarray], read_label: Callable[[np.ndarray], str], press: Callable[[str], bool],
             say: Callable[[str], None] = print, max_steps: int = 12, settle: float = 1.1) -> bool:
    """Focus the bottom-bar icon `target` (one of BAR) on the main menu and activate it. The focus is read from the tooltip the
    game draws above the focused icon (the model reads only that small crop); the bar's fixed order decides Left or Right."""
    want = BAR.index(target)
    for _ in range(max_steps):
        frame = look()
        h, w = frame.shape[:2]
        label = read_label(frame[int(h * 0.80):int(h * 0.925), int(w * 0.40):w])
        at = bar_index(label)
        if at == want:
            say(f"The tooltip says {label!r}: that is the one. Enter.")
            return press("enter")
        key = "down" if at is None else ("left" if at > want else "right")
        if not press(key):
            return False
        time.sleep(settle)  # the tooltip appears about a second after the focus moves
    return False


@dataclass
class Navigator:
    look: Callable[[], np.ndarray]  # a screenshot of the game window (BGR)
    ask: Callable[[np.ndarray, str], str]  # (screenshot, user text) -> model answer
    press: Callable[[str], bool]  # one guarded key tap
    say: Callable[[str], None] = print
    history: list = field(default_factory=list)
    alive: Callable[[], bool] | None = None  # is the game window still there (no endless looks at a closed game)

    def reach(self, goal: str, confirm: Callable[[], bool] | None = None, max_steps: int = 18, settle: float = 0.6) -> bool:
        """Press keys until the goal is reached. `confirm` is the caller's own local test of the goal, when there is one."""
        for _ in range(max_steps):
            if self.alive is not None and not self.alive():  # 5 Nov 02:06: the game closed and every look failed for minutes
                self.say("The game window is gone (closed or crashed), so I stop here; nothing is pressed.")
                return False
            if confirm is not None and confirm():
                return True
            recent = "; ".join(f"{h.focused}->{h.press}" for h in self.history[-4:])
            answer = None
            for _attempt in range(2):  # one empty or failed answer is a transport hiccup, not the end of the mission
                try:
                    answer = self.ask(self.look(), f"Goal: {goal}. Recent steps (focused->pressed): {recent or 'none'}.")
                    self._failed_looks = 0
                    break
                except Exception as error:  # noqa: BLE001 - said and retried; nothing is pressed on a failed look
                    self._failed_looks = getattr(self, "_failed_looks", 0) + 1
                    if self._failed_looks == 1:  # said once, not every second (5 Nov: a minute of the same line)
                        self.say(f"I can't see the game window right now ({type(error).__name__}); waiting for it, nothing is pressed.")
                    time.sleep(1.0)
            if answer is None:
                if getattr(self, "_failed_looks", 0) >= 20:
                    self.say("I still can't see the game after 20 tries; I stop here. Nothing was pressed.")
                    return False
                continue
            step = check(parse_step(answer))
            if "quit" in f"{step.screen} {step.focused}".lower() and step.press not in ("esc", "none"):
                # 5 Nov: Esc on the main menu opens "Are you sure you want to quit?"; one Enter on "Yes" closes the game.
                # On a quit question the only key ever pressed is Esc (= No).
                step.press = "esc"
            self.history.append(step)
            self.say(f"Menu: on '{step.screen}', '{step.focused}' is focused: {'pressing ' + step.press if step.press != 'none' else 'nothing to press'}.")
            if step.refused:
                self.say(step.refused)
            if step.done and step.press in ("none",):
                return confirm() if confirm is not None else True
            if step.press == "none":
                time.sleep(settle)
                continue
            if not self.press(step.press):
                self.say("The game is not in front, so I stopped pressing.")
                return False
            time.sleep(settle)
            if step.press == "enter" and confirm is not None:  # a race may be loading: wait for it locally, asking nothing
                deadline = time.monotonic() + 15.0
                while time.monotonic() < deadline:
                    if confirm():
                        return True
                    time.sleep(0.5)
        return confirm() if confirm is not None else False
