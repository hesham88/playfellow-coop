"""Which power the kart is holding, read off the race view: the game draws the power's icon, once per charge, at the top centre.

The look of each power comes from the game's own files at run time (data/gui/icons, named in data/powerup.xml), so nothing of the
game is copied here. Each icon is matched against the top-centre band at the size the game draws it, on its opaque pixels only.
"""
from __future__ import annotations

from pathlib import Path

import cv2
import numpy as np

from playfellow_coop.games.stk.paths import game_data

ICONS = {"bowling": "bowling-icon.png", "bubblegum": "bubblegum-icon.png", "cake": "cake-icon.png", "anchor": "anchor-icon.png",
         "switch": "swap-icon.png", "swatter": "swatter-icon.png", "parachute": "parachute-icon.png", "plunger": "plunger-icon.png",
         "rubber_ball": "rubber_ball-icon.png", "zipper": "zipper_collect.png"}
BAND = (0.03, 0.135, 0.30, 0.70)  # top, bottom, left, right shares of the view
SIZES = (0.036, 0.048)  # icon height at half size, as a share of the view height: icons have different margins (plunger best at 36 px of 1000, bowling at 48)
WORK = 2  # matched at half size
MIN_SHAPE = 0.70  # measured: true icons 0.79 and 0.95 at their best size, teal walls 0.27
MAX_RMS = 35.0  # measured: true icons 19-20 at their best size, an empty sky 47 or more


class HeldPower:
    def __init__(self, data: Path | None = None):
        self.templates: dict[str, tuple[np.ndarray, np.ndarray]] = {}
        folder = (data or game_data()) / "gui" / "icons"
        for name, file in ICONS.items():
            image = cv2.imread(str(folder / file), cv2.IMREAD_UNCHANGED)
            if image is not None and image.ndim == 3 and image.shape[2] == 4:
                self.templates[name] = (image[:, :, :3], image[:, :, 3])
        self._scaled: dict[int, dict] = {}

    def _at(self, size: int) -> dict:
        if size not in self._scaled:
            out = {}
            for name, (bgr, alpha) in self.templates.items():
                t = cv2.resize(bgr, (size, size), interpolation=cv2.INTER_AREA)
                a = (cv2.resize(alpha, (size, size), interpolation=cv2.INTER_AREA) > 200).astype(np.uint8)
                out[name] = (t, cv2.merge([a, a, a]))
            self._scaled[size] = out
        return self._scaled[size]

    @staticmethod
    def _same_shape(band: np.ndarray, template: np.ndarray, mask: np.ndarray, result: np.ndarray) -> bool:
        """The patch must follow the icon's pattern, not only its average colour (Abyss' teal walls are the bowling ball's colour)."""
        _, _, (x, y), _ = cv2.minMaxLoc(result)
        size = template.shape[0]
        patch = cv2.cvtColor(band[y:y + size, x:x + size], cv2.COLOR_BGR2GRAY).astype(np.float32)
        icon = cv2.cvtColor(template, cv2.COLOR_BGR2GRAY).astype(np.float32)
        keep = mask[:, :, 0] > 0
        if patch.shape != icon.shape or keep.sum() < 16:
            return False
        a, b = patch[keep], icon[keep]
        if a.std() < 1.0 or b.std() < 1.0:
            return False
        return float(np.corrcoef(a, b)[0, 1]) >= MIN_SHAPE

    def read(self, frame: np.ndarray) -> tuple[str | None, int]:
        """(power name or None, how many charges are drawn)."""
        h, w = frame.shape[:2]
        band = frame[int(h * BAND[0]):int(h * BAND[1]), int(w * BAND[2]):int(w * BAND[3])]
        band = cv2.resize(band, (band.shape[1] // WORK, band.shape[0] // WORK), interpolation=cv2.INTER_AREA)
        best, best_rms, best_map, best_size = None, MAX_RMS, None, 0
        for share in SIZES:
            size = min(max(int(h * share), 8), min(band.shape[:2]) - 1)
            for name, (template, mask) in self._at(size).items():
                result = cv2.matchTemplate(band, template, cv2.TM_SQDIFF, mask=mask)
                result = np.nan_to_num(np.sqrt(np.maximum(result, 0) / max(int(mask.sum()), 1)), nan=1e9, posinf=1e9)
                rms = float(result.min())
                if rms < best_rms and self._same_shape(band, template, mask, result):
                    best, best_rms, best_map, best_size = name, rms, result, size
        if best is None:
            return None, 0
        spots, work = 0, best_map.copy()
        for _ in range(6):
            _, _, (x, y), _ = cv2.minMaxLoc(work)
            if work[y, x] > MAX_RMS:
                break
            spots += 1
            work[:, max(x - best_size // 3, 0):x + best_size // 3 + 1] = 1e9  # charges overlap by about 40%
        return best, max(spots, 1)


LIST_FIRST, LIST_PITCH = 0.043, 0.06  # the standings list: first row's centre and the row spacing, shares of the view height (measured, 4 karts)


def read_place(frame: np.ndarray) -> int | None:
    """The kart's place, from the red ring around its icon in the standings list at the top left, or None. Only the icon column
    is searched (the time gaps beside it are red too), and only the largest red blob counts (other icons carry red specks)."""
    h, w = frame.shape[:2]
    top = int(h * 0.02)
    strip = frame[top:int(h * 0.32), :int(w * 0.052)]
    b, g, r = (strip[..., i].astype(np.int16) for i in range(3))
    red = ((r > 170) & (g < 70) & (b < 70)).astype(np.uint8)
    count, _, stats, cents = cv2.connectedComponentsWithStats(red)
    if count < 2:
        return None
    best = 1 + int(np.argmax(stats[1:, cv2.CC_STAT_AREA]))
    if stats[best, cv2.CC_STAT_AREA] < 30:
        return None
    centre = (top + (stats[best, cv2.CC_STAT_TOP] + stats[best, cv2.CC_STAT_HEIGHT] / 2.0)) / h
    return max(int(round((centre - LIST_FIRST) / LIST_PITCH)) + 1, 1)
