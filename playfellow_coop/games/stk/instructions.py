"""Reading the game's on-screen instructions while racing, and acting on them at the right moment.

The tutorial and story mode teach through a message box at the bottom of the race view ("press <Backspace> to be rescued",
"press the <V> key while turning to skid", "collect nitro bottles, we will use them after the curve"). A player reads it
and does what it says, when it says. Three parts, so the 20-looks-a-second driving never waits for a model:

  watch   (local, ~1 ms)   is a message box up, and is its text new? A coarse picture of the dark text strokes is compared
                           with the last one read; a new message is passed on once it has held still for two looks.
  read    (model, async)   a worker thread sends ONLY that strip to the vision model, which returns the words and one
                           instruction {action, timing}; answers are cached by the strip's picture, so a message shown again
                           costs nothing. A key the message names is checked against the controls card (input.xml): the
                           card, not the model, decides which action that key is.
  act     (local)          the driver applies it with its timing: now (one tap), on the next turn / while turning (skids
                           on sharp turns for a while), on the next straight (nitro when the road ahead is straight).
"""
from __future__ import annotations

import hashlib
import json
import queue
import re
import threading
import time
from dataclasses import dataclass, field
from typing import Callable

import cv2
import numpy as np

from playfellow_coop.games.stk.card import Card

ACTIONS = ("rescue", "nitro", "drift", "fire", "lookBack", "accel", "brake", "steer", "collect", "none")
TIMINGS = ("now", "next_turn", "while_turning", "next_straight", "ongoing", "none")
ACTION_FROM_CARD = {"rescue": "rescue", "nitro": "nitro", "drift": "drift", "fire": "fire", "lookBack": "lookBack", "accel": "accel",
                    "brake": "brake", "steerLeft": "steer", "steerRight": "steer"}


def text_strokes(strip_bgr: np.ndarray) -> np.ndarray:
    """Dark text on the light box, as a boolean picture."""
    grey = cv2.cvtColor(strip_bgr, cv2.COLOR_BGR2GRAY)
    return grey < 90


def find_box(frame: np.ndarray) -> tuple[int, int, int, int] | None:
    """The bottom message box (x0, y0, x1, y1 in the frame), or None. It is a light, almost grey band in the bottom 7% of the
    view, wider than a third of it, with dark letters on it."""
    h, w = frame.shape[:2]
    y0 = int(h * 0.925)
    band = frame[y0:h, :]
    b, g, r = (band[..., i].astype(np.int16) for i in range(3))
    light = (r > 175) & (g > 170) & (b > 150) & (np.abs(r - b) < 70)
    rows = light.mean(axis=1) > 0.30  # the box's rows first (one or two lines of text: 20-50 rows of a ~75-row band)
    if rows.sum() < 6:
        return None
    ys = np.nonzero(rows)[0]
    cols = light[ys[0]:ys[-1] + 1].mean(axis=0) > 0.5
    if cols.sum() < w * 0.33:
        return None
    xs = np.nonzero(cols)[0]
    x0, x1 = int(xs[0]), int(xs[-1]) + 1
    box = (x0, y0 + int(ys[0]), x1, y0 + int(ys[-1]) + 1)
    ink = text_strokes(frame[box[1]:box[3], box[0]:box[2]]).mean()
    return box if 0.01 < ink < 0.35 else None


def signature(strip_bgr: np.ndarray) -> np.ndarray:
    small = cv2.resize(text_strokes(strip_bgr).astype(np.uint8) * 255, (96, 8), interpolation=cv2.INTER_AREA)
    return small > 40


@dataclass
class MessageWatch:
    """Says when a NEW message has appeared and settled (returns its strip), else None."""

    last_read: np.ndarray | None = None
    _pending: np.ndarray | None = None
    _steady: int = 0
    shown: bool = False

    def look(self, frame: np.ndarray) -> np.ndarray | None:
        box = find_box(frame)
        self.shown = box is not None
        if box is None:
            self._pending, self._steady = None, 0
            return None
        x0, y0, x1, y1 = box
        strip = frame[y0:y1, x0:x1]
        sig = signature(strip)
        if self.last_read is not None and np.mean(sig != self.last_read) < 0.06:
            return None  # the message already read
        if self._pending is not None and np.mean(sig != self._pending) < 0.06:
            self._steady += 1
        else:
            self._pending, self._steady = sig, 1
        if self._steady >= 2:
            self.last_read, self._pending, self._steady = sig, None, 0
            return strip.copy()
        return None


@dataclass
class Instruction:
    text: str
    action: str
    timing: str
    key: str | None = None
    source: str = "model"
    note: str = ""

    def describe(self) -> str:
        when = {"now": "now", "next_turn": "at the next turn", "while_turning": "while turning", "next_straight": "on the next straight",
                "ongoing": "from now on", "none": ""}[self.timing]
        if self.action in ("none", "collect", "steer", "accel"):
            return f'Read: "{self.text}". Noted.'
        key = f" ({self.key.upper()})" if self.key else ""
        return f'Read: "{self.text}" → {self.action}{key} {when}.'.strip()


SYSTEM = ("You read one instruction from the message box of the racing game SuperTuxKart, shown in the picture. Reply with JSON only: "
          '{"text": the exact words, "keys": the key names written between < > (list), "action": one of ' + ", ".join(ACTIONS) +
          ', "timing": one of ' + ", ".join(TIMINGS) + "}. "
          "action: what the message asks the player to press or do (rescue = get put back on the road, drift = skid, lookBack = look "
          "behind, collect = pick things up, none = just information). timing: now = do it right away; while_turning = keep doing it "
          "in turns; next_turn; next_straight = later, once past the curve or on a straight; ongoing = a general habit; none.")


def parse_answer(answer: str, card: Card) -> Instruction:
    """The model's JSON as an Instruction; a key named on screen is mapped through the controls card, which overrules the model."""
    match = re.search(r"\{.*\}", answer, re.S)
    data = json.loads(match.group(0)) if match else {}
    text = str(data.get("text", "")).strip()[:200]
    action = data.get("action") if data.get("action") in ACTIONS else "none"
    timing = data.get("timing") if data.get("timing") in TIMINGS else "none"
    keys = [str(k) for k in (data.get("keys") or []) if isinstance(k, (str, int))]
    key, note = None, ""
    for word in keys + re.findall(r"<([^<>]{1,12})>", text):
        card_action = card.action_for_screen_key(word)
        if card_action is None:
            continue
        mapped = ACTION_FROM_CARD.get(card_action, "none")
        if mapped in ("accel", "steer") and action not in ("accel", "steer", "none"):
            continue  # "accelerate and press <V> while turning": the arrow keys are context, the instruction is the other key
        if mapped != action and action not in ("none",):
            note = f"the card says {word} is {card_action}; the model said {action}"
        action, key = mapped, card.keys.get(card_action)
        break
    return Instruction(text, action, timing, key, "model", note)


@dataclass
class Reader:
    """A worker thread that reads new message strips with `ask(strip) -> answer text` and hands back Instructions."""

    ask: Callable[[np.ndarray], str]
    card: Card
    cache: dict = field(default_factory=dict)
    done: "queue.SimpleQueue[Instruction]" = field(default_factory=queue.SimpleQueue)
    todo: "queue.SimpleQueue[np.ndarray | None]" = field(default_factory=queue.SimpleQueue)
    calls: int = 0
    failures: int = 0
    log: list = field(default_factory=list)
    _said: dict = field(default_factory=dict)

    def start(self) -> "Reader":
        threading.Thread(target=self._run, name="instruction-reader", daemon=True).start()
        return self

    def stop(self) -> None:
        self.todo.put(None)

    def submit(self, strip: np.ndarray) -> None:
        self.todo.put(strip)

    def _run(self) -> None:
        while True:
            strip = self.todo.get()
            if strip is None:
                return
            key = hashlib.sha1(cv2.resize(strip, (192, 16)).tobytes()).hexdigest()
            started = time.monotonic()
            try:
                if key not in self.cache:
                    self.calls += 1
                    self.cache[key] = self.ask(strip)
                inst = parse_answer(self.cache[key], self.card)
            except Exception as error:  # a failed read is said and skipped; the driving goes on
                self.failures += 1
                self.log.append({"error": type(error).__name__, "detail": str(error)[:120]})
                continue
            words = re.sub(r"\W+", " ", inst.text.lower()).strip()
            repeat = words and self._said.get(words, -99.0) > time.monotonic() - 20.0
            self.log.append({"text": inst.text, "action": inst.action, "timing": inst.timing, "key": inst.key, "note": inst.note,
                             "seconds": round(time.monotonic() - started, 2), "repeat": bool(repeat)})
            if repeat:
                continue  # the same words again (the strip re-drawn a little differently): acted on already
            self._said[words] = time.monotonic()
            self.done.put(inst)

    def ready(self) -> list[Instruction]:
        out = []
        while True:
            try:
                out.append(self.done.get_nowait())
            except queue.Empty:
                return out
