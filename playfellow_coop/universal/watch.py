"""The screen watch: the turn loop's one question to the universal interface, "what kind of screen is this, and is it worth asking the model?"

A loading screen has nothing to decide, so asking the model about it costs money and time for nothing. The watch says "wait" for a loading screen, but carefully: the picture must be
nearly frozen, the classifier must be fairly sure, it never skips more than `max_skips` turns in a row, and after a forced question it will not skip again for `cooldown` turns, so a dark
game that merely looks like loading is still played. For menus, death and victory screens it adds one plain sentence to the model's prompt instead.
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np

from playfellow_coop.universal.eog import EoGDetector
from playfellow_coop.universal.frames import normalize
from playfellow_coop.universal.motion import motion_level
from playfellow_coop.universal.state import StateClassifier, looks_loading

WATCH_SIDE = 160  # the watch reads every picture shrunk to this long side; a classifier is fitted on pictures of the same size (state_fit.collect)

END_NOTE = "The picture has stopped answering the keys (the match may be over): look at the screen before pressing more."
NOTES = {"menu": "The screen looks like a menu.", "dead": "The screen looks like a game-over screen.", "victory": "The screen looks like a victory screen."}


@dataclass
class Look:
    state: str
    confidence: float
    motion: float
    skip: bool = False
    note: str = ""
    end_candidate: bool = False  # the end-of-game signals fired on two looks in a row


class ScreenWatch:
    def __init__(self, classifier: StateClassifier | None = None, max_skips: int = 2, cooldown: int = 5, min_confidence: float = 0.4, frozen: float = 0.01, eog_fps: float | None = None):
        """`eog_fps`: how many looks per second the session takes (1 / look interval); when given, the end-of-game signals run on every look (see universal/eog.py)."""
        self.classifier = classifier or StateClassifier()
        self.eog = EoGDetector(fps=max(0.5, eog_fps)) if eog_fps else None
        self._action = 0.0
        self._end_streak = 0
        self.end_candidates = 0
        self.max_skips, self.cooldown, self.min_confidence, self.frozen = max_skips, cooldown, min_confidence, frozen
        self._previous: np.ndarray | None = None
        self._skipped = 0
        self._rest = 0  # turns left before skipping is allowed again
        self.skipped_total = 0

    def note_action(self, magnitude: float) -> None:
        """Tell the watch whether keys were pressed since the last look (0 = none, up to 1): without input there is nothing for the picture to answer."""
        self._action = max(0.0, min(1.0, float(magnitude)))

    def look(self, picture) -> Look:
        frame = normalize(picture, max_side=WATCH_SIDE)  # a small copy is enough to tell screens apart, and fast
        previous, self._previous = self._previous, frame
        state, confidence = self.classifier.classify(frame, previous)
        motion = motion_level(previous, frame) if previous is not None and previous.shape == frame.shape else 1.0
        seen = Look(state, confidence, motion)
        if self.eog is not None and previous is not None and previous.shape == frame.shape:
            verdict = self.eog.update(previous, frame, self._action)
            self._end_streak = self._end_streak + 1 if verdict.candidate else 0
            if self._end_streak >= 2:
                seen.end_candidate = True
                self.end_candidates += 1
            self._action = 0.0
        if self._rest > 0:
            self._rest -= 1
        if looks_loading(frame):  # the strict rule decides loading, whatever the learned centres say
            state, seen.state = "loading", "loading"
        wants_skip = state == "loading" and motion <= self.frozen and previous is not None and (looks_loading(frame) or (self.classifier.fitted and confidence >= self.min_confidence))
        if wants_skip and self._rest == 0 and self._skipped < self.max_skips:
            self._skipped += 1
            self.skipped_total += 1
            seen.skip = True
            return seen
        if self._skipped:  # the loading screen ended, or we have waited enough: the model is asked, and skipping rests for a while
            self._skipped = 0
            self._rest = self.cooldown if wants_skip else 0
        if self.classifier.fitted and state in NOTES and confidence >= 0.2:  # only a hint, only from a classifier fitted to this game: the model also sees the picture
            seen.note = NOTES[state]
        if seen.end_candidate and not seen.note:
            seen.note = END_NOTE
        return seen
