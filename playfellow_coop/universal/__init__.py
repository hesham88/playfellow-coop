"""The universal game interface: treat every game as a black box and use only the channels a human uses (pixels in, key and mouse out).

Four pillars, one module each: `frames` + `actions` (input and output), `hud` + `motion` (perception), `timing` (the clock and the process), `state` (evaluation and guardrails).
`Interface` ties them into one object a session can hold: `see` a picture, `watch` it (state, motion, HUD, goal), `act` on the model's action tokens.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.universal.actions import ActionBinder, GuardRails, NativeInput, Plan
from playfellow_coop.universal.frames import normalize
from playfellow_coop.universal.rate import FrameClock
from playfellow_coop.universal.hud import GlyphReader, Hud, ModelReader, Region, bar_fraction, find_bars, text_regions
from playfellow_coop.universal.motion import Odometry, moving_blobs, motion_level, shift_between
from playfellow_coop.universal.state import GoalChecker, StateClassifier, Verdict
from playfellow_coop.universal.timing import AdaptiveSkip, ClockSync, Supervisor, subprocess_supervisor

__all__ = ["ActionBinder", "AdaptiveSkip", "ClockSync", "FrameClock", "GlyphReader", "GoalChecker", "GuardRails", "Hud", "Interface", "ModelReader", "NativeInput", "Observation",
           "Odometry", "Plan", "Region", "StateClassifier", "Supervisor", "Verdict", "bar_fraction", "find_bars", "motion_level", "moving_blobs", "normalize", "shift_between",
           "subprocess_supervisor", "text_regions"]


@dataclass
class Observation:
    frame: np.ndarray
    state: str
    state_confidence: float
    motion: float
    position: tuple[int, int]
    hud: dict
    moving: list = field(default_factory=list)
    goal: Verdict | None = None


class Interface:
    def __init__(self, hud: Hud | None = None, goal: str = "", card_keys: set[str] | None = None, classifier: StateClassifier | None = None, size: tuple[int, int] | None = None,
                 order: str = "rgb"):
        self.hud, self.size, self.order = hud or Hud(), size, order
        self.classifier = classifier or StateClassifier()
        self.odometry = Odometry()
        self.binder, self.guard = ActionBinder(card_keys), GuardRails()
        self.goal = GoalChecker(goal) if goal else None
        self.clock = FrameClock()
        self.skip = AdaptiveSkip()
        self._previous: np.ndarray | None = None

    def see(self, picture) -> np.ndarray:
        self.clock.tick()
        return normalize(picture, self.size, self.order)

    def watch(self, picture, objects: list[str] | None = None) -> Observation:
        frame = self.see(picture)
        state, confidence = self.classifier.classify(frame, self._previous)
        motion = motion_level(self._previous, frame) if self._previous is not None else 0.0
        moving = moving_blobs(self._previous, frame) if self._previous is not None else []
        position = self.odometry.update(frame)
        values = self.hud.read(frame)
        verdict = None
        if self.goal is not None:
            texts = [v for v in values.values() if isinstance(v, str)] + [str(int(v)) for v in values.values() if isinstance(v, float) and not isinstance(v, bool) and v >= 1]
            verdict = self.goal.check(texts, objects)
        self._previous = frame
        return Observation(frame, state, confidence, motion, position, values, moving, verdict)

    def act(self, tokens: str) -> Plan:
        """The model's action tokens, bound to native inputs and passed through the guardrails (notes say what was dropped)."""
        return self.guard.check(self.binder.bind(tokens))
