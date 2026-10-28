"""Pillar 4, knowing how it is going: what kind of screen this is, and whether the player's goal has been reached.

* `StateClassifier` tells loading screens, menus, gameplay, death and victory apart from the picture alone. It is a small nearest-centroid model over a few plain picture measurements
  (brightness, colour, how much red or gold, how much text-like detail, how much moves). It starts with sensible built-in centres and `fit` re-learns them from labelled pictures of
  the game at hand, so it adapts to a game's own look. Unsure answers say so (`confidence`) instead of guessing.
* `GoalChecker` reads the player's request ("find a sword", "reach level 3") and checks it against the text the screen shows (from the HUD reader) and the objects the model reports.
Numpy only.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.universal.motion import grey, motion_level

STATES = ("loading", "menu", "gameplay", "dead", "victory")
FEATURES = ("brightness", "contrast", "saturation", "red", "gold", "dark", "detail", "palette", "motion", "edge_band")


def features(frame: np.ndarray, previous: np.ndarray | None = None) -> np.ndarray:
    """Ten plain measurements of a picture, each roughly 0..1."""
    small = frame[::3, ::3].astype(np.float32)
    r, g, b = small[..., 0], small[..., 1], small[..., 2]
    brightness = float(grey(small).mean()) / 255.0
    contrast = float(grey(small).std()) / 128.0
    top, bottom = small.max(axis=2), small.min(axis=2)
    saturation = float(((top - bottom) / np.maximum(top, 1.0)).mean())
    red = float(((r > 120) & (r > g * 1.7) & (r > b * 1.7)).mean())
    gold = float(((r > 170) & (g > 130) & (b < g * 0.6) & (r >= g)).mean())
    dark = float((top < 45).mean())
    g2 = grey(small)
    detail = float(((np.abs(np.diff(g2, axis=1)) > 50).mean() + (np.abs(np.diff(g2, axis=0)) > 50).mean()) / 2 * 4)
    quant = (small // 32).astype(np.int32)
    palette = len(np.unique(quant[..., 0] * 64 + quant[..., 1] * 8 + quant[..., 2])) / 128.0
    motion = motion_level(previous, frame) if previous is not None and previous.shape == frame.shape else 0.0
    h, w = g2.shape
    band = max(h // 8, 1)
    edge_band = float(min(1.0, abs(g2[:band].mean() - g2[h // 2 - band:h // 2 + band].mean()) / 128.0))  # vignette / panel: edges differ from the middle
    return np.array([brightness, contrast, saturation, red, gold, dark, min(detail, 1.0), min(palette, 1.0), motion, edge_band], dtype=np.float32)


# built-in centres, from what these screens generally look like; fit() replaces them with a game's own. Measured on the five arena games they are NOT reliable (play frames of
# two games read as a menu or a loading screen), so nothing acts on an unfitted classifier except the strict `looks_loading` rule below.
DEFAULT_CENTRES = {
    "loading": np.array([0.10, 0.10, 0.20, 0.00, 0.00, 0.80, 0.03, 0.05, 0.00, 0.05], dtype=np.float32),
    "menu": np.array([0.35, 0.40, 0.40, 0.00, 0.01, 0.30, 0.30, 0.20, 0.02, 0.25], dtype=np.float32),
    "gameplay": np.array([0.40, 0.35, 0.45, 0.01, 0.01, 0.15, 0.20, 0.35, 0.20, 0.10], dtype=np.float32),
    "dead": np.array([0.18, 0.30, 0.55, 0.30, 0.00, 0.40, 0.12, 0.15, 0.03, 0.30], dtype=np.float32),
    "victory": np.array([0.55, 0.35, 0.55, 0.00, 0.30, 0.10, 0.15, 0.20, 0.05, 0.25], dtype=np.float32),
}


def looks_loading(frame: np.ndarray) -> bool:
    """The one rule that needs no learning: a nearly black picture with at most a thin bright strip (a progress bar). Games rarely look like this while they are being played."""
    small = frame[::3, ::3].astype(np.float32)
    top = small.max(axis=2)
    return bool((top < 45).mean() >= 0.85 and float(grey(small).mean()) < 40.0)


@dataclass
class StateClassifier:
    centres: dict[str, np.ndarray] = field(default_factory=lambda: {k: v.copy() for k, v in DEFAULT_CENTRES.items()})
    scale: np.ndarray = field(default_factory=lambda: np.full(len(FEATURES), 0.25, dtype=np.float32))
    fitted: bool = False  # True once centres were learned from this game's own pictures; the built-in centres are only a rough guide (see the note on DEFAULT_CENTRES)

    def fit(self, labelled: list[tuple[np.ndarray, str, np.ndarray | None]]) -> "StateClassifier":
        """Re-learn the centres from `(picture, label, previous picture or None)` examples. A label with no example keeps its built-in centre."""
        by_label: dict[str, list[np.ndarray]] = {}
        for frame, label, previous in labelled:
            if label not in STATES:
                raise ValueError(f"unknown state {label!r}; use one of {STATES}")
            by_label.setdefault(label, []).append(features(frame, previous))
        self.fitted = True
        for label, rows in by_label.items():
            self.centres[label] = np.mean(rows, axis=0)
        everything = np.concatenate([np.array(rows) for rows in by_label.values()])
        if len(everything) > 1:
            self.scale = np.maximum(everything.std(axis=0), 0.08).astype(np.float32)  # never trust a feature that did not vary in the examples to be exact
        return self

    def to_json(self) -> dict:
        return {"centres": {k: [round(float(x), 5) for x in v] for k, v in self.centres.items()}, "scale": [round(float(x), 5) for x in self.scale], "fitted": self.fitted}

    @classmethod
    def from_json(cls, data: dict) -> "StateClassifier":
        model = cls()
        model.centres = {k: np.array(v, dtype=np.float32) for k, v in data["centres"].items()}
        model.scale = np.array(data["scale"], dtype=np.float32)
        model.fitted = bool(data.get("fitted", True))
        return model

    def classify(self, frame: np.ndarray, previous: np.ndarray | None = None) -> tuple[str, float]:
        """(state, confidence 0..1). Confidence is how much closer the best centre is than the second best; near 0 means "could be either"."""
        vector = features(frame, previous)
        distances = {label: float(np.sqrt((((vector - centre) / self.scale) ** 2).sum())) for label, centre in self.centres.items()}
        ranked = sorted(distances.items(), key=lambda item: item[1])
        best, second = ranked[0], ranked[1]
        confidence = 0.0 if second[1] <= 0 else max(0.0, min(1.0, (second[1] - best[1]) / second[1]))
        return best[0], confidence


@dataclass
class Verdict:
    done: bool
    matched: list[str] = field(default_factory=list)
    missing: list[str] = field(default_factory=list)


STOP_WORDS = frozenset("a an the to of and or in on at for with your my some any find get collect reach make go gather pick up open obtain".split())
NUMBER = re.compile(r"\d+")


def _words(text: str) -> list[str]:
    return [w for w in re.findall(r"[a-z0-9]+", text.lower()) if w not in STOP_WORDS]


def _close(a: str, b: str) -> bool:
    if a == b or (len(a) >= 4 and (a.startswith(b) or b.startswith(a))):
        return True
    if abs(len(a) - len(b)) > 1 or min(len(a), len(b)) < 4:
        return False
    # one letter wrong or missing: the reading of an odd font is rarely perfect
    if len(a) == len(b):
        return sum(x != y for x, y in zip(a, b)) <= 1
    short, long_ = sorted((a, b), key=len)
    return any(long_[:i] + long_[i + 1:] == short for i in range(len(long_)))


class GoalChecker:
    """Checks a plain-words goal against what is on screen. The goal's key words (and numbers) must all be found among the screen texts and reported objects."""

    def __init__(self, goal: str):
        self.goal = goal
        self.keywords = _words(goal)
        self.numbers = [int(n) for n in NUMBER.findall(goal)]

    def check(self, texts: list[str], objects: list[str] | None = None) -> Verdict:
        seen = _words(" ".join(texts + (objects or [])))
        matched, missing = [], []
        for word in self.keywords:
            if word.isdigit():
                continue
            (matched if any(_close(word, s) for s in seen) else missing).append(word)
        for number in self.numbers:
            screen_numbers = {int(n) for n in NUMBER.findall(" ".join(texts))}
            (matched if number in screen_numbers else missing).append(str(number))
        return Verdict(done=bool(self.keywords or self.numbers) and not missing, matched=matched, missing=missing)
