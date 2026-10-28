"""A dry run: the buddy looks, thinks and says what it would press, and nothing is ever pressed.

From the voice-chess recipe: start with a dry run, validate the commands and the picture first, then enable execution. `DryRunHands` wraps the real hands: `do` records the step
instead of acting, everything else (stop, resume, release) passes through to the real hands, so F9, F12 and the hand-over behave exactly as in a real run.
"""
from __future__ import annotations


class DryRunHands:
    def __init__(self, real):
        self._real = real
        self.pretended: list[str] = []  # the actions the buddy would have pressed, in order

    def do(self, step, box) -> None:
        self.pretended.append(step.label() if hasattr(step, "label") else str(step))

    def __getattr__(self, name):  # on_stop, resume, release_all, card, ... all go to the real hands
        return getattr(self._real, name)
