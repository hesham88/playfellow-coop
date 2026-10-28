"""Zero-shot grounding of an unknown skin or game from the first frames (research R1 section 3.2, R2 section 3.2).

A skill that was built against one palette finds nothing on a skin it has never seen. This finds the one thing every game has, the thing that answers the player's keys, from the keys
themselves: a short balanced probe (neutral, key, neutral, key, ...) and one question, "which pixels changed only when I pressed something?".

  * the controllable avatar changes with the keys and rests in the neutral intervals (high action contingency),
  * an enemy, a projectile or a particle changes in the neutral intervals as well (it moves on its own: flow without contingency),
  * the background does not change at all.

From the pixels of the avatar the harness reads a runtime visual descriptor (its colour, its size and centre) and, from how far it moved for each key, the key bindings (which key moves it
which way): the inverse-dynamics idea of probing candidate keys one at a time to learn what they do, instead of trusting keys remembered from other games. The descriptor is then written
into a skill's look (`rebind_look`), so a skill built for one skin runs on another. numpy only; `act` and `grab` are callbacks (a real session passes its hands and its screen).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from playfellow_coop.universal.motion import components

Box = tuple[int, int, int, int]  # left, top, right, bottom (exclusive)


@dataclass
class Grounding:
    avatar_box: Box | None = None
    avatar_colour: tuple[float, float, float] | None = None
    background_colour: tuple[float, float, float] | None = None
    movers: list[Box] = field(default_factory=list)  # things that moved on their own during the neutral intervals
    bindings: dict[str, tuple[float, float]] = field(default_factory=dict)  # key -> (dx, dy) the avatar moved, in pixels
    contingency: float = 0.0  # 0..1: how much more the picture changed with a key than without one
    confidence: float = 0.0


def changed_mask(a: np.ndarray, b: np.ndarray, level: int = 24) -> np.ndarray:
    """Pixels whose colour moved by more than `level` on any channel."""
    return (np.abs(a.astype(np.int16) - b.astype(np.int16)).max(axis=-1) > level)


def background_colour(frame: np.ndarray) -> tuple[float, float, float]:
    """The most common colour (coarsely): the floor of the scene."""
    quant = (frame // 16).reshape(-1, 3).astype(np.int32)
    code = quant[:, 0] * 256 + quant[:, 1] * 16 + quant[:, 2]
    best = int(np.bincount(code).argmax())
    members = frame.reshape(-1, 3)[code == best]
    return tuple(float(v) for v in members.mean(axis=0))


def _box(mask: np.ndarray, pad: int = 0) -> Box | None:
    ys, xs = np.nonzero(mask)
    if len(xs) == 0:
        return None
    h, w = mask.shape
    return (max(0, int(xs.min()) - pad), max(0, int(ys.min()) - pad), min(w, int(xs.max()) + 1 + pad), min(h, int(ys.max()) + 1 + pad))


def probe(act: Callable[[str], None], grab: Callable[[], np.ndarray], keys: list[str], neutral: Callable[[], None] = lambda: None, rounds: int = 1,
          level: int = 24, min_area: int = 4) -> Grounding:
    """Run the micro-probe: for each key in `keys` (and `rounds` times over), look, press it once, look; and between keys let a neutral interval pass (`neutral()`, which should let the
    game advance one tick without input, or do nothing for a game that only moves on input). Returns what was found.

    `act(key)` presses the key; `grab()` returns the current picture (an RGB array)."""
    key_masks: dict[str, np.ndarray] = {}
    neutral_masks: list[np.ndarray] = []
    shifts: dict[str, list[tuple[float, float]]] = {k: [] for k in keys}
    first = grab()
    for _ in range(max(1, rounds)):
        for key in keys:
            before = grab()
            neutral()
            quiet = grab()
            neutral_masks.append(changed_mask(before, quiet, level))  # nothing pressed: whatever changed moves on its own
            act(key)
            after = grab()
            key_masks[key] = key_masks.get(key, np.zeros(before.shape[:2], bool)) | changed_mask(quiet, after, level)
            moved = _displacement(quiet, after, level)
            if moved is not None:
                shifts[key].append(moved)
    autonomous = np.zeros(first.shape[:2], bool)
    for m in neutral_masks:
        autonomous |= m
    pressed = np.zeros_like(autonomous)
    for m in key_masks.values():
        pressed |= m
    contingent = pressed & ~_grow(autonomous, 2)
    share = float(contingent.sum()) / max(1, int(pressed.sum()))  # how much of what changed with a key was NOT already changing on its own
    result = Grounding(background_colour=background_colour(first), contingency=share)
    result.movers = [(b.box[0], b.box[1], b.box[0] + b.box[2], b.box[1] + b.box[3]) for b in components(autonomous, min_area)]
    blobs = components(contingent, min_area)
    if blobs:
        # the avatar: the contingent blob that answered the most keys (a sprite that moves leaves one blob for its old and new place close together)
        blob = max(blobs, key=lambda b: b.area)
        left, top, width, height = blob.box
        result.avatar_box = (left, top, left + width, top + height)
    for key, values in shifts.items():
        if values:
            result.bindings[key] = (float(np.mean([v[0] for v in values])), float(np.mean([v[1] for v in values])))
    if result.avatar_box is not None:
        result.avatar_colour = _avatar_colour(first, key_masks, result)
        answered = sum(1 for k in keys if key_masks.get(k) is not None and key_masks[k].any())
        result.confidence = min(1.0, (answered / max(1, len(keys))) * min(1.0, 2.0 * share) * (1.0 if result.avatar_colour else 0.5))
    return result


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


def _displacement(before: np.ndarray, after: np.ndarray, level: int) -> tuple[float, float] | None:
    """How far the thing that changed moved: the centre of the pixels that appeared against the centre of the pixels that disappeared. None when nothing changed."""
    changed = changed_mask(before, after, level)
    if not changed.any():
        return None
    bg = background_colour(before)
    near_bg = lambda frame: (np.abs(frame.astype(np.float32) - np.array(bg, dtype=np.float32)).max(axis=-1) < level)  # noqa: E731
    appeared = changed & ~near_bg(after)  # now something that is not floor
    disappeared = changed & near_bg(after) & ~near_bg(before)  # was something, is floor now
    if not appeared.any() or not disappeared.any():
        return (0.0, 0.0)  # something changed but nothing clearly left or arrived (it only changed colour): no displacement
    ay, ax = np.nonzero(appeared)
    dy, dx = np.nonzero(disappeared)
    return (float(ax.mean() - dx.mean()), float(ay.mean() - dy.mean()))


def _avatar_colour(frame: np.ndarray, key_masks: dict[str, np.ndarray], g: Grounding) -> tuple[float, float, float] | None:
    """The colour of the avatar: the most common colour that is not the floor, among the pixels that changed when keys were pressed (taken from the first picture, where the avatar stood
    before the first push)."""
    if g.avatar_box is None:
        return None
    left, top, right, bottom = g.avatar_box
    patch = frame[top:bottom, left:right].reshape(-1, 3).astype(np.float32)
    bg = np.array(g.background_colour or (0, 0, 0), dtype=np.float32)
    far = patch[np.abs(patch - bg).max(axis=-1) > 24]
    if len(far) < 2:
        return None
    quant = (far // 16).astype(np.int32)
    code = quant[:, 0] * 256 + quant[:, 1] * 16 + quant[:, 2]
    best = int(np.bincount(code).argmax())
    return tuple(float(v) for v in far[code == best].mean(axis=0))


def rebind_look(look, role: str, grounding: Grounding, tolerance: int = 40):
    """A copy of a skill's Look with the avatar's role (head, player, paddle ...) re-pointed at the colour just found, so the skill built for one skin runs on another. Other roles keep
    their prototypes: this fixes a changed character skin, not a whole re-drawn world."""
    from playfellow_coop.skills.looks import Look
    if grounding.avatar_colour is None:
        return None
    protos = {r: list(p) for r, p in look.protos.items()}
    protos[role] = [tuple(grounding.avatar_colour)]
    return Look(f"{look.name}+avatar", protos, max(look.radius, float(tolerance)))
