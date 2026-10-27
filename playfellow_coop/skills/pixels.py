"""Reading a game picture: nearest-colour tests on single pixels and small areas. Skills use only these; none looks at a game's inner state."""
from __future__ import annotations

import numpy as np

Colour = tuple[int, int, int]


def near(frame: np.ndarray, x: int, y: int, colour: Colour, tolerance: int = 24) -> bool:
    """True when the pixel at (x, y) is within `tolerance` of `colour` on every channel (off-picture is False)."""
    height, width = frame.shape[:2]
    if not (0 <= x < width and 0 <= y < height):
        return False
    pixel = frame[y, x]
    return all(abs(int(pixel[i]) - colour[i]) <= tolerance for i in range(3))


def nearest(frame: np.ndarray, x: int, y: int, palette: dict, default=None):
    """The key of the palette colour closest to the pixel at (x, y) (sum of channel gaps), or `default` when none is near."""
    pixel = frame[y, x].astype(int)
    best, best_gap = default, 60
    for key, colour in palette.items():
        gap = abs(pixel[0] - colour[0]) + abs(pixel[1] - colour[1]) + abs(pixel[2] - colour[2])
        if gap < best_gap:
            best, best_gap = key, gap
    return best


def mask_of(frame: np.ndarray, colour: Colour, tolerance: int = 24, top: int = 0) -> np.ndarray:
    """A boolean picture: True where a pixel is within `tolerance` of `colour`; rows above `top` (the score bar) are always False."""
    delta = np.abs(frame.astype(np.int16) - np.array(colour, dtype=np.int16))
    mask = (delta <= tolerance).all(axis=2)
    if top:
        mask[:top] = False
    return mask


def centre_of(mask: np.ndarray) -> tuple[float, float] | None:
    """The (x, y) centre of the True pixels, None when there are none."""
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    return float(xs.mean()), float(ys.mean())
