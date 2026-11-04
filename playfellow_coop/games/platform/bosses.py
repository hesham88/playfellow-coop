"""Learning a boss across attempts, the way a player does: first survive and watch, then punish the openings.

A cue is a coarse signature of what changed on screen just before something happened. Each hit taken is remembered against the cue
before it, with the dodge that was in use; each dodge that worked is remembered too. Next time the cue shows, the dodge with the best
record is chosen, and an untried one is tried while the record is thin. An opening is a cue after which attacking drew no hit.
"""
from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass, field

import cv2
import numpy as np

DODGES = ("jump", "back", "forward", "stay")


def cue_of(before: np.ndarray, after: np.ndarray, side: int = 8) -> tuple:
    """Which parts of a side x side grid changed most: stable for the same wind-up, different for a different one."""
    change = cv2.resize(np.abs(after.astype(np.float32) - before.astype(np.float32)), (side, side), interpolation=cv2.INTER_AREA)
    return tuple(np.flatnonzero(change.ravel() > max(float(change.mean()) * 2.0, 6.0)).tolist()[:12])


@dataclass
class BossBook:
    hits: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    safe: dict = field(default_factory=lambda: defaultdict(lambda: defaultdict(int)))
    openings: dict = field(default_factory=lambda: defaultdict(int))
    attempts: int = 0

    def record(self, cue: tuple, dodge: str, was_hit: bool) -> None:
        (self.hits if was_hit else self.safe)[cue][dodge] += 1

    def record_opening(self, cue: tuple, punished: bool) -> None:
        self.openings[cue] += -2 if punished else 1

    def choose(self, cue: tuple) -> str:
        """The dodge for this cue: an untried one first, then the best record."""
        tried = set(self.hits[cue]) | set(self.safe[cue])
        for dodge in DODGES:
            if dodge not in tried:
                return dodge
        score = lambda d: (self.safe[cue][d] + 1) / (self.safe[cue][d] + self.hits[cue][d] + 2)  # noqa: E731
        return max(DODGES, key=score)

    def attack_now(self, cue: tuple) -> bool:
        return self.openings[cue] > 0
