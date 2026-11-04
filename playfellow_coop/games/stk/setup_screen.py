"""The Race Setup screen, read locally: which difficulty is selected (its portrait sits in a gold glow), so the difficulty is
set by sight - press, look, press - and never by a blind key count (3 Nov: a fixed count left the race on Novice)."""
from __future__ import annotations

import numpy as np

DIFFICULTIES = ("novice", "intermediate", "expert", "supertux")
SLOT_X = (0.16, 0.38, 0.61, 0.83)  # the four portraits' centres across the window


def selected_difficulty(frame: np.ndarray) -> str | None:
    """The difficulty in the gold glow, or None when the Race Setup's difficulty row is not on screen."""
    h, w = frame.shape[:2]
    band = frame[int(h * 0.15):int(h * 0.45)]
    b, g, r = (band[..., i].astype(np.int16) for i in range(3))
    gold = (r > 220) & (g > 140) & (g < 225) & (b < 90)
    if gold.sum() < 0.01 * band.shape[0] * band.shape[1]:
        return None
    # gold per portrait slot: the glowing one has far more than any other (every penguin has yellow feet and a beak)
    counts = [int(gold[:, max(int((s - 0.10) * w), 0):int((s + 0.10) * w)].sum()) for s in SLOT_X]
    order = sorted(range(4), key=lambda i: counts[i], reverse=True)
    if counts[order[0]] < 2.5 * max(counts[order[1]], 1):
        return None  # no single glowing slot (the main menu's logo spreads across the middle slots)
    return DIFFICULTIES[order[0]]
