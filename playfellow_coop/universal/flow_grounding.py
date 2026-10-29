"""Grounding for worlds that move on their own (research R2 section 3.2: flow with and without contingency).

`skin_grounding.probe` asks "which pixels changed only when a key was pressed?". In a game whose avatar already moves every tick (a snake, a runner), the avatar changes in the quiet
intervals too, so that question finds nothing. The better question is about VELOCITY: every region that moves has a velocity per tick; pressing a key changes the velocity of the avatar and
of nothing else. For each key the harness measures every moving region's velocity in a quiet tick JUST BEFORE the press and in the tick of the press, and the region whose velocity changed
is the avatar for that key (a plain obstacle slides the same way whatever is pressed; the quiet tick right before is the baseline, so a heading that a key changes for good, as in a snake,
is measured against the heading it had a moment ago and not against the start of the probe). The change in velocity is that key's binding. A region that was still in the quiet tick and
moves after the press (a runner waiting in its lane) counts as a change from rest.

Velocity of a region is the slide between its crop in two consecutive pictures (the same phase correlation the odometry uses), so it needs no colour, no template and no object detector.
numpy only; `act`, `grab` and `neutral` are callbacks as in `skin_grounding.probe`.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from playfellow_coop.universal.motion import components, shift_between
from playfellow_coop.universal.skin_grounding import Box, background_colour, changed_mask

Velocity = tuple[float, float]
SLIDE_CONFIDENCE = 0.1  # a slide counts as measured only when the correlation peak is at least this clean
SLIDE_OVER_JUMP = 0.4  # a measured slide wins over a jump unless it is much smaller (4/10 of it): perspective obstacles give small, noisy slides next to a real teleport


@dataclass
class FlowGrounding:
    avatar_box: Box | None = None
    bindings: dict[str, Velocity] = field(default_factory=dict)  # key -> change of the avatar's velocity (pixels per tick)
    quiet_velocity: Velocity = (0.0, 0.0)  # how the avatar was moving in the quiet tick before the first answered key
    obstacles: list[Box] = field(default_factory=list)  # regions that moved on their own and ignored the keys
    confidence: float = 0.0


def _crop(frame: np.ndarray, box: Box, pad: int) -> np.ndarray:
    h, w = frame.shape[:2]
    left, top, right, bottom = box
    return frame[max(0, top - pad):min(h, bottom + pad), max(0, left - pad):min(w, right + pad)]


def region_velocity(before: np.ndarray, after: np.ndarray, box: Box, pad: int = 12, min_confidence: float = 0.05) -> Velocity | None:
    """How far the content of `box` slid between two pictures (dx, dy in pixels), or None when it could not be measured."""
    a, b = _crop(before, box, pad), _crop(after, box, pad)
    if a.shape != b.shape or min(a.shape[:2]) < 8:
        return None
    dx, dy, confidence = shift_between(a, b, max_shift=pad)
    if confidence < min_confidence:
        return None
    return float(dx), float(dy)


def _overlap(a: Box, b: Box) -> bool:
    return min(a[2], b[2]) > max(a[0], b[0]) and min(a[3], b[3]) > max(a[1], b[1])


def _grow(mask: np.ndarray, n: int) -> np.ndarray:
    out = mask.copy()
    for _ in range(n):
        g = out.copy()
        g[1:] |= out[:-1]
        g[:-1] |= out[1:]
        g[:, 1:] |= out[:, :-1]
        g[:, :-1] |= out[:, 1:]
        out = g
    return out


def _regions(*masks: np.ndarray, min_area: int) -> list[Box]:
    union = np.zeros_like(masks[0])
    for m in masks:
        union |= m
    return [(b.box[0], b.box[1], b.box[0] + b.box[2], b.box[1] + b.box[3]) for b in components(_grow(union, 3), min_area)]


def jump(before: np.ndarray, quiet: np.ndarray, after: np.ndarray, level: int = 24, min_area: int = 6) -> tuple[Box, Velocity] | None:
    """A move too big to be a slide (a runner changing lane, a piece jumping a tile): what changed with the key where the quiet tick had no change nearby, as the centre of what appeared
    against the centre of what disappeared. None when nothing changed that way."""
    mask = changed_mask(quiet, after, level) & ~_grow(changed_mask(before, quiet, level), 4)
    if int(mask.sum()) < min_area:
        return None
    bg = np.array(background_colour(before), dtype=np.float32)
    near = lambda frame: np.abs(frame.astype(np.float32) - bg).max(axis=-1) < level  # noqa: E731
    appeared = mask & ~near(after)
    gone = mask & near(after) & ~near(quiet)
    if not appeared.any() or not gone.any():
        return None
    ay, ax = np.nonzero(appeared)
    gy, gx = np.nonzero(gone)
    ys, xs = np.nonzero(mask)
    return (int(xs.min()), int(ys.min()), int(xs.max()) + 1, int(ys.max()) + 1), (float(ax.mean() - gx.mean()), float(ay.mean() - gy.mean()))


def probe_flow(act: Callable[[str], None], grab: Callable[[], np.ndarray], keys: list[str], neutral: Callable[[], None] = lambda: None, restart: Callable[[], None] | None = None,
               rounds: int = 1, level: int = 24, min_area: int = 6, min_response: float = 1.0, press_ticks: bool = False) -> FlowGrounding:
    """For each key: a quiet tick (`neutral()`), then the key pressed and a tick. `press_ticks=True` is for a game where pressing a key already advances one tick (then no extra tick is
    run after it). `restart()` is called before each key when given: a game that can end during the probe (a snake that meets the wall) starts again, so every key is measured in a live
    game. Returns the avatar (the region whose velocity changed with the keys), the change per key, and the regions that did not respond."""
    winners: dict[str, list[tuple[Box, Velocity, Velocity]]] = {k: [] for k in keys}  # key -> [(box, velocity before, change)]
    others: list[Box] = []
    for _ in range(max(1, rounds)):
        for key in keys:
            if restart is not None:
                restart()
            before = grab()
            neutral()
            quiet = grab()
            act(key)
            if not press_ticks:
                neutral()
            after = grab()
            boxes = _regions(changed_mask(before, quiet, level), changed_mask(quiet, after, level), min_area=min_area)
            best = None
            measured: list[Box] = []  # regions whose slide was measured cleanly: what they did is already explained, so it is not also a jump
            for box in boxes:
                pad = max(12, box[2] - box[0], box[3] - box[1])
                v0 = region_velocity(before, quiet, box, pad) or (0.0, 0.0)
                v1 = region_velocity(quiet, after, box, pad, SLIDE_CONFIDENCE)
                if v1 is None:
                    continue
                measured.append(box)
                change = (v1[0] - v0[0], v1[1] - v0[1])
                size = float(np.hypot(*change))
                if size >= min_response and (best is None or size > best[0]):
                    best = (size, box, v0, change)
            moved = jump(before, quiet, after, level, min_area)
            if moved is not None and any(_overlap(moved[0], m) for m in measured):
                moved = None
            if moved is not None and float(np.hypot(*moved[1])) >= 2.0 * min_response and (best is None or best[0] < SLIDE_OVER_JUMP * float(np.hypot(*moved[1]))):
                best = (float(np.hypot(*moved[1])), moved[0], (0.0, 0.0), moved[1])
            others.extend(b for b in boxes if best is None or b != best[1])
            if best is not None:
                winners[key].append((best[1], best[2], best[3]))
    answered = {k: v for k, v in winners.items() if v}
    others = _distinct(others)
    if not answered:
        return FlowGrounding(obstacles=others[:8])
    # The avatar is the place the keys keep answering at: the winning box that overlaps the most winning boxes of other keys (a runner moves a little between keys, so exact boxes
    # differ), the largest total change breaking a tie. A single stray winner from one key therefore cannot beat a region that several keys agree on.
    flat = [(key, w) for key, v in answered.items() for w in v]
    near = lambda a, b: _overlap(_pad(a, 12), b)  # noqa: E731 - reads as a sentence at the call site; a little slack for a sprite that moved between keys
    def support(item):
        key, (box, _, change) = item
        agreeing = {k for k, (b, _, _) in flat if near(box, b)}
        return (len(agreeing), float(np.hypot(*change)))
    _, (avatar, quiet, _) = max(flat, key=support)
    result = FlowGrounding(avatar_box=avatar, quiet_velocity=quiet)
    for key, found in answered.items():
        mine = [c for b, _, c in found if near(avatar, b)]  # only winners at the avatar's place: a stray region does not pollute the average
        if mine:
            result.bindings[key] = (float(np.mean([c[0] for c in mine])), float(np.mean([c[1] for c in mine])))
    result.obstacles = [b for b in others if not near(avatar, b)][:8]
    agree = len(result.bindings) / max(1, len(keys))  # the share of keys that answered at the avatar's place
    result.confidence = min(1.0, agree)
    return result


def _pad(box: Box, n: int) -> Box:
    return (box[0] - n, box[1] - n, box[2] + n, box[3] + n)


def _distinct(boxes: list[Box]) -> list[Box]:
    """The boxes with near-duplicates removed (the same region seen again for every key and round)."""
    out: list[Box] = []
    for b in boxes:
        if not any(_overlap(_pad(b, 4), _pad(o, 4)) for o in out):
            out.append(b)
    return out
