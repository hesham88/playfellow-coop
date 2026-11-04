"""The start: "Ready!" ... "Set!" ... "Go!" in orange letters at the centre of the race view, about a second each, after a
short camera fly-in. The game's own help: press accelerate at "Set!" for a start boost (pressing during "Ready!" is
punished). "Ready!" is a wider word than "Set!" and "Go!", so the width of the orange text tells the phases apart, locally,
in about a millisecond. Measured on the 3 Nov tutorial recording: Ready 145-155, Set 156-168, Go 170 (frames at 12 fps).
"""
from __future__ import annotations

from dataclasses import dataclass

import numpy as np


def text_width(frame: np.ndarray) -> float:
    """Width of the orange countdown letters, as a share of the view's width (0 when there are none)."""
    h, w = frame.shape[:2]
    crop = frame[int(h * 0.33):int(h * 0.47), int(w * 0.3):int(w * 0.7)]
    import cv2

    b, g, r = (crop[..., i].astype(np.int16) for i in range(3))
    orange = (r > 200) & (g > 120) & (g < 215) & (b < 90) & (r - b > 140)
    # the letters have a dark outline; orange sand or a sunset does not: keep orange pixels within 2 px of near-black ones
    dark = (cv2.cvtColor(crop, cv2.COLOR_BGR2GRAY) < 50).astype(np.uint8)
    near_dark = cv2.dilate(dark, np.ones((5, 5), np.uint8)) > 0
    orange &= near_dark
    cols = np.nonzero(orange.sum(axis=0) >= 2)[0]
    if len(cols) < 6 or orange.sum() < 40:
        return 0.0
    return float(cols[-1] - cols[0]) / w


@dataclass
class Countdown:
    """Feed it frames; `go_now` turns true at "Set!" (accelerate from here) and stays true."""

    ready_width: float = 0.0
    phase: str = "waiting"  # waiting -> ready -> set
    looks: int = 0

    def look(self, frame: np.ndarray) -> str:
        self.looks += 1
        width = text_width(frame)
        if self.phase == "waiting" and width > 0.07:
            self.phase, self.ready_width = "ready", width
        elif self.phase == "ready":
            if width > self.ready_width:
                self.ready_width = width
            elif 0.0 < width < 0.8 * self.ready_width:
                self.phase = "set"  # the word got shorter: "Set!" (or "Go!" if a look was missed): accelerate
        return self.phase

    @property
    def go_now(self) -> bool:
        return self.phase == "set"
