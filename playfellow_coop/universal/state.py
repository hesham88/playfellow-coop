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


# A region is (top, bottom, left, right) as fractions of the picture. Many games say how a round ended with a few words in a corner ("You win!" in green, "Game over" in red) over
# a board that looks just like play; the whole-picture measurements above cannot see a few letters, a region that holds them can. `fit(..., regions=n)` finds the n regions that
# best tell this game's screens apart, at build time, from labelled pictures; at play time only the pixels in them are read.
INKS = ("ink", "green", "red", "light", "gold")  # per region: how much bright ink it holds, and which share of that ink is green, red, white-grey or gold
GRID_ROWS = 16
SPANS = ((0.0, 0.25), (0.25, 0.5), (0.5, 0.75), (0.75, 1.0), (0.0, 0.5), (0.25, 0.75), (0.5, 1.0), (0.0, 1.0))


def _ink(patch: np.ndarray) -> list[float]:
    p = patch[::2, ::2].astype(np.float32)
    if p.size == 0:
        return [0.0] * len(INKS)
    r, g, b = p[..., 0], p[..., 1], p[..., 2]
    top, bottom = p.max(axis=2), p.min(axis=2)
    bright = top > 110
    n = int(bright.sum())
    if n == 0:
        return [0.0] * len(INKS)
    green = bright & (g > r * 1.25) & (g > b * 1.05)
    red = bright & (r > g * 1.35) & (r > b * 1.05)
    light = bright & (bottom > 140) & (top - bottom < 60)
    gold = bright & (r > 150) & (g > 120) & (b < g * 0.7) & (r >= g * 0.9)
    return [min(1.0, n / bright.size * 4), float(green.sum()) / n, float(red.sum()) / n, float(light.sum()) / n, float(gold.sum()) / n]


def _crop(frame: np.ndarray, region) -> np.ndarray:
    h, w = frame.shape[:2]
    y0, y1, x0, x1 = region
    top, left = int(y0 * h), int(x0 * w)
    return frame[top:max(int(y1 * h), top + 1), left:max(int(x1 * w), left + 1)]


def region_features(frame: np.ndarray, regions) -> np.ndarray:
    """`len(INKS)` numbers per region, each 0..1: the ink in that part of the picture and its colour."""
    out: list[float] = []
    for region in regions:
        out.extend(_ink(_crop(frame, region)))
    return np.array(out, dtype=np.float32)


def candidate_regions() -> list[tuple[float, float, float, float]]:
    return [(row / GRID_ROWS, (row + 1) / GRID_ROWS, x0, x1) for row in range(GRID_ROWS) for x0, x1 in SPANS]


def _overlap(a, b) -> bool:
    return a[0] < b[1] and b[0] < a[1] and a[2] < b[3] and b[2] < a[3]


def learn_regions(labelled: list[tuple[np.ndarray, str, np.ndarray | None]], count: int) -> list[tuple[float, float, float, float]]:
    """The `count` non-overlapping regions whose ink best separates the most common screen (gameplay, as a rule) from each other kind of screen (Fisher's ratio per kind,
    summed as log(1 + ratio) so a region must help with every kind, not just one)."""
    labels = [label for _, label, _ in labelled]
    kinds = sorted(set(labels))
    if len(kinds) < 2:
        raise ValueError("learning regions needs at least two kinds of screen")
    common = max(kinds, key=labels.count)
    scored = []
    for region in candidate_regions():
        values = np.array([_ink(_crop(frame, region)) for frame, _, _ in labelled], dtype=np.float32)
        base = values[[label == common for label in labels]]
        score = 0.0
        for kind in kinds:
            if kind == common:
                continue
            other = values[[label == kind for label in labels]]
            ratio = ((other.mean(axis=0) - base.mean(axis=0)) ** 2 / (other.var(axis=0) + base.var(axis=0) + 1e-3)).sum()
            score += float(np.log1p(ratio))
        scored.append((score, region))
    scored.sort(key=lambda item: -item[0])
    chosen: list[tuple[float, float, float, float]] = []
    for _, region in scored:
        if not any(_overlap(region, kept) for kept in chosen):
            chosen.append(region)
        if len(chosen) == count:
            break
    return chosen


@dataclass
class StateClassifier:
    centres: dict[str, np.ndarray] = field(default_factory=lambda: {k: v.copy() for k, v in DEFAULT_CENTRES.items()})
    scale: np.ndarray = field(default_factory=lambda: np.full(len(FEATURES), 0.25, dtype=np.float32))
    fitted: bool = False  # True once centres were learned from this game's own pictures; the built-in centres are only a rough guide (see the note on DEFAULT_CENTRES)
    regions: list[tuple[float, float, float, float]] = field(default_factory=list)  # learned by fit(..., regions=n); empty = whole-picture measurements only

    def vector(self, frame: np.ndarray, previous: np.ndarray | None = None) -> np.ndarray:
        whole = features(frame, previous)
        return np.concatenate([whole, region_features(frame, self.regions)]) if self.regions else whole

    def fit(self, labelled: list[tuple[np.ndarray, str, np.ndarray | None]], regions: int = 0) -> "StateClassifier":
        """Re-learn the centres from `(picture, label, previous picture or None)` examples. A label with no example keeps its built-in centre.

        With `regions=n` it first learns the n regions that best tell the labels apart; such a classifier knows only the screens it was shown (a built-in centre has no region part,
        and loading screens stay with the strict `looks_loading` rule)."""
        for _, label, _ in labelled:
            if label not in STATES:
                raise ValueError(f"unknown state {label!r}; use one of {STATES}")
        if regions:
            self.regions = learn_regions(labelled, regions)
            self.centres = {}
        by_label: dict[str, list[np.ndarray]] = {}
        for frame, label, previous in labelled:
            by_label.setdefault(label, []).append(self.vector(frame, previous))
        self.fitted = True
        for label, rows in by_label.items():
            self.centres[label] = np.mean(rows, axis=0)
        everything = np.concatenate([np.array(rows) for rows in by_label.values()])
        if len(everything) > 1:
            self.scale = np.maximum(everything.std(axis=0), 0.08).astype(np.float32)  # never trust a feature that did not vary in the examples to be exact
        return self

    def to_json(self) -> dict:
        data = {"centres": {k: [round(float(x), 5) for x in v] for k, v in self.centres.items()}, "scale": [round(float(x), 5) for x in self.scale], "fitted": self.fitted}
        if self.regions:
            data["regions"] = [[round(float(x), 5) for x in region] for region in self.regions]
        return data

    @classmethod
    def from_json(cls, data: dict) -> "StateClassifier":
        model = cls()
        model.centres = {k: np.array(v, dtype=np.float32) for k, v in data["centres"].items()}
        model.scale = np.array(data["scale"], dtype=np.float32)
        model.fitted = bool(data.get("fitted", True))
        model.regions = [tuple(float(x) for x in region) for region in data.get("regions", [])]
        return model

    def classify(self, frame: np.ndarray, previous: np.ndarray | None = None) -> tuple[str, float]:
        """(state, confidence 0..1). Confidence is how much closer the best centre is than the second best; near 0 means "could be either"."""
        vector = self.vector(frame, previous)
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
