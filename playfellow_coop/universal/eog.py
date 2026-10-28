"""End-of-game detection from pixels, without needing a distinct "game over" screen (research R1 section 3.1, R2 section 3.1).

A learned screen classifier memorises fonts and banners and fails on a game that just keeps animating after the match. These signals do not care what the screen looks like:

  1. action contingency: while the agent sends non-neutral input, the picture around the avatar should move with it. When input stops mattering (the match is over, the avatar is dead, a
     cut-scene took over) the correlation collapses, whatever is still animating elsewhere.
  2. the HUD: anchors that vanish, a score that resets to zero, a health bar that stays empty.
  3. a frozen central viewport while keys are pressed, and a slow cumulative-sum test (CUSUM) on a cheap frame embedding for a change of regime (a cut to a podium or lobby).
  4. a cheap verifier called only when 1 to 3 fire: it looks at a 2 x 2 contact sheet of four frames (t-3.0 s, t-1.5 s, t-0.5 s, t) and the HUD difference and answers one of
     ACTIVE_PLAY, TEMP_CUTSCENE, ROUND_OVER, MATCH_TERMINATED. A vision model can be that verifier, and so can `ProbeVerifier` below, which costs nothing: it presses a few different keys
     and sees whether anything answers.

All thresholds are the research's defaults and are parameters. numpy only.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from playfellow_coop.universal.frames import resize
from playfellow_coop.universal.motion import grey

OUTCOMES = ("ACTIVE_PLAY", "TEMP_CUTSCENE", "ROUND_OVER", "MATCH_TERMINATED")
ENDED = ("ROUND_OVER", "MATCH_TERMINATED")


@dataclass
class Verdict:
    ended: bool  # the match or round is over (only after a verifier said so, or when no verifier is set and `candidate` is the best we know)
    outcome: str  # one of OUTCOMES, or "CANDIDATE" when signals fired but no verifier was available
    triggers: list[str] = field(default_factory=list)
    verified: bool = False
    candidate: bool = False


@dataclass
class Signals:
    contingency: float = 0.5
    reference: float = 0.0  # the strongest recent motion seen while acting (decays slowly): what "the picture answers my input" looks like in THIS game
    low_contingency: int = 0
    still_viewport: int = 0
    cusum: float = 0.0
    last_score: float | None = None
    hud_baseline: int = 0
    hud_missing: int = 0
    empty_health: int = 0


def cheap_embedding(frame: np.ndarray) -> np.ndarray:
    """A tiny appearance vector that survives a scrolling or sliding scene but not a cut: a coarse colour histogram, an edge-strength histogram and four quadrant brightnesses.
    A stronger encoder (DINOv2) can replace it through `embed=`."""
    small = resize(frame, 64, 36)
    quant = (small // 64).reshape(-1, 3).astype(int)
    colour = np.bincount(quant[:, 0] * 16 + quant[:, 1] * 4 + quant[:, 2], minlength=64).astype(np.float32)
    colour /= max(colour.sum(), 1.0)
    g = grey(small)
    edge = np.abs(np.diff(g, axis=1)).ravel()
    strength = np.histogram(edge, bins=8, range=(0, 128))[0].astype(np.float32)
    strength /= max(strength.sum(), 1.0)
    quads = np.array([g[:18, :32].mean(), g[:18, 32:].mean(), g[18:, :32].mean(), g[18:, 32:].mean()], dtype=np.float32) / 255.0
    unit = lambda v: v / (np.linalg.norm(v) + 1e-8)  # noqa: E731  each block counts the same, so a cut moves the whole vector, not one corner of it
    return np.concatenate([unit(colour), unit(strength), 0.3 * unit(quads - quads.mean() + 1e-3)]).astype(np.float32)


def contact_sheet(frames: list[np.ndarray], tile: tuple[int, int] = (384, 216)) -> np.ndarray:
    """Four frames as one 2 x 2 picture (oldest top-left, newest bottom-right), each shrunk to `tile` (width, height). Fewer than four are repeated from the oldest."""
    if not frames:
        raise ValueError("a contact sheet needs at least one frame")
    four = (list(frames) + [frames[-1]] * 4)[:4] if len(frames) < 4 else list(frames)[-4:]
    tiles = [resize(f, tile[0], tile[1]) for f in four]
    return np.vstack([np.hstack(tiles[:2]), np.hstack(tiles[2:])])


class EoGDetector:
    def __init__(self, fps: float = 60.0, verifier: Callable[[np.ndarray, dict, list[str]], dict] | None = None, embed: Callable[[np.ndarray], np.ndarray] = cheap_embedding,
                 contingency_floor: float = 0.08, contingency_seconds: float = 0.75, still_seconds: float = 1.2, still_level: float = 0.45, hud_missing_seconds: float = 0.8,
                 cusum_drift: float = 0.10, cusum_limit: float = 2.5, cooldown_seconds: float = 2.0, sheet_times: tuple[float, ...] = (3.0, 1.5, 0.5, 0.0),
                 ema_alpha: float = 0.03, change_level: int = 24):
        self.fps, self.verifier, self.embed = fps, verifier, embed
        self.contingency_floor, self.still_level, self.cusum_drift, self.cusum_limit = contingency_floor, still_level, cusum_drift, cusum_limit
        self.ema_alpha, self.change_level = ema_alpha, change_level
        self.contingency_frames = max(1, int(contingency_seconds * fps))
        self.still_frames = max(1, int(still_seconds * fps))
        self.hud_missing_frames = max(1, int(hud_missing_seconds * fps))
        self.cooldown_frames = int(cooldown_seconds * fps)
        self.sheet_offsets = [int(t * fps) for t in sheet_times]
        self.state = Signals()
        self._ema: np.ndarray | None = None
        self._history: deque[np.ndarray] = deque(maxlen=max(self.sheet_offsets) + 1)
        self._cooldown = 0
        self._frame_no = 0

    def reset(self) -> None:
        """A new round: signals and history start over."""
        self.state, self._ema, self._cooldown, self._frame_no = Signals(), None, 0, 0
        self._history.clear()

    def _sheet(self) -> np.ndarray:
        frames = list(self._history)
        picks = []
        for offset in self.sheet_offsets:
            index = max(0, len(frames) - 1 - offset)
            picks.append(frames[index])
        return contact_sheet(picks)

    def update(self, prev: np.ndarray, cur: np.ndarray, action_magnitude: float = 0.0, avatar_box: tuple[int, int, int, int] | None = None,
               hud: dict | None = None) -> Verdict:
        """Call once per frame. `action_magnitude`: 0 for neutral input, up to 1. `avatar_box`: (left, top, right, bottom) when known, else the middle of the picture.
        `hud`: optional readings: `score`, `health_ratio` (0..1), `anchors` (how many HUD anchor regions were found)."""
        hud = hud or {}
        s = self.state
        self._history.append(cur)
        self._frame_no += 1
        g0, g1 = grey(prev), grey(cur)
        h, w = g1.shape
        if avatar_box is not None:
            x0, y0, x1, y1 = avatar_box
        else:
            x0, y0, x1, y1 = int(w * 0.25), int(h * 0.25), int(w * 0.75), int(h * 0.75)
        box = (slice(max(0, y0), min(h, y1)), slice(max(0, x0), min(w, x1)))
        before, after = prev[box].astype(np.int16), cur[box].astype(np.int16)
        # how much of the avatar's surroundings changed: the share of pixels whose colour moved by more than `change_level` on any channel (robust to a sprite that is
        # close in brightness to its background, which a plain grey difference is not)
        energy = float((np.abs(after - before).max(axis=-1) > self.change_level).mean()) if before.size and before.shape == after.shape else 0.0
        if action_magnitude > 0.1:
            s.reference = max(s.reference * 0.999, energy)
            instant = min(1.0, energy / s.reference) if s.reference > 0 else 0.0
            s.contingency = 0.85 * s.contingency + 0.15 * instant
            s.low_contingency = s.low_contingency + 1 if s.contingency < self.contingency_floor else max(0, s.low_contingency - 2)
        centre = (slice(int(h * 0.15), int(h * 0.85)), slice(int(w * 0.15), int(w * 0.85)))
        still = float(np.abs(g1[centre] - g0[centre]).mean())
        s.still_viewport = s.still_viewport + 1 if (still < self.still_level and action_magnitude > 0.1) else 0
        score = hud.get("score")
        reset = s.last_score is not None and s.last_score > 0 and score == 0
        if score is not None:
            s.last_score = score
        anchors = int(hud.get("anchors", 0) or 0)
        if s.hud_baseline == 0 and anchors > 0:
            s.hud_baseline = anchors
        s.hud_missing = s.hud_missing + 1 if (s.hud_baseline > 0 and anchors < 0.3 * s.hud_baseline) else 0
        health = hud.get("health_ratio")
        s.empty_health = s.empty_health + 1 if (health is not None and health <= 0.01) else 0
        vector = self.embed(cur)
        vector = vector / (np.linalg.norm(vector) + 1e-8)
        if self._ema is None:
            self._ema = vector
        distance = 1.0 - float(np.dot(vector, self._ema))
        self._ema = (1 - self.ema_alpha) * self._ema + self.ema_alpha * vector
        s.cusum = max(0.0, s.cusum + distance - self.cusum_drift)

        triggers = []
        if s.low_contingency >= self.contingency_frames:
            triggers.append("action_contingency_collapse")
        if s.still_viewport >= self.still_frames:
            triggers.append("viewport_freeze")
        if reset:
            triggers.append("score_reset")
        if s.empty_health >= max(1, int(0.5 * self.fps)):
            triggers.append("health_depleted")
        if s.hud_missing >= self.hud_missing_frames:
            triggers.append("hud_vanished")
        if s.cusum > self.cusum_limit:
            triggers.append("regime_shift")
            s.cusum = 0.0
        if self._cooldown > 0:
            self._cooldown -= 1
            return Verdict(False, "ACTIVE_PLAY")
        if not triggers:
            return Verdict(False, "ACTIVE_PLAY")
        if self.verifier is None:
            return Verdict(False, "CANDIDATE", triggers, verified=False, candidate=True)
        answer = self.verifier(self._sheet(), hud, triggers)
        outcome = answer.get("outcome") if isinstance(answer, dict) else None
        if outcome not in OUTCOMES:
            outcome = "ACTIVE_PLAY"  # an unreadable answer never ends a match
        if outcome in ENDED:
            return Verdict(True, outcome, triggers, verified=True)
        self._cooldown = self.cooldown_frames  # it was a stun, a cut-scene or a blocked key: look again later, not at once
        s.low_contingency = s.still_viewport = 0
        return Verdict(False, outcome, triggers, verified=True)


class ProbeVerifier:
    """A free verifier: press a few different keys and see whether the picture answers. `act(key)` presses it, `grab()` returns the picture afterwards.
    A blocked key (walking into a wall) leaves the picture unchanged for that key only; a finished game leaves it unchanged for every key."""

    def __init__(self, act: Callable[[str], None], grab: Callable[[], np.ndarray], keys: list[str], min_pixels: int = 4, level: int = 24, settle: Callable[[], None] = lambda: None):
        self.act, self.grab, self.keys, self.min_pixels, self.level, self.settle = act, grab, list(keys), min_pixels, level, settle

    def __call__(self, sheet: np.ndarray, hud: dict, triggers: list[str]) -> dict:
        moved = 0
        for key in self.keys:
            before = self.grab()
            self.act(key)
            self.settle()
            after = self.grab()
            if before.shape == after.shape and int((np.abs(after.astype(np.int16) - before.astype(np.int16)).max(axis=-1) > self.level).sum()) >= self.min_pixels:
                moved += 1  # at least a few pixels changed in colour: something answered (a small paddle counts, a rounding error does not)
        return {"outcome": "ACTIVE_PLAY" if moved else "MATCH_TERMINATED", "keys_that_answered": moved}
