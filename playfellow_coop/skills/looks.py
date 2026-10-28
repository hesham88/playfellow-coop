"""A look: how one game's things appear in pixels, so the same skill reads the same game drawn another way.

A skill used to compare exact colours. A re-skinned game (sprites, glass colours) draws the same rules with other pixels, so the skill now asks a `Look`: "which thing is this
patch of picture?". A look holds, per role (head, wall, coin, ...), a few prototype colours (the mean colour of that thing's patch) and answers with the nearest role inside a radius,
or None. Looks are data: built once per game and per skin by `calibrate` (build time, from labelled frames), saved as JSON, tried one after another when a game starts, and the first one
the skill can read the picture with wins. At play time only pixels are read; the labels exist only while building a look.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np

Colour = tuple[float, float, float]


def patch_mean(frame: np.ndarray, left: int, top: int, width: int, height: int, inset: int = 0) -> np.ndarray:
    """The mean colour of a rectangle of the picture, shrunk by `inset` on every side (so borders and rounded corners do not count). Off-picture parts are ignored."""
    h, w = frame.shape[:2]
    x0, y0 = max(0, left + inset), max(0, top + inset)
    x1, y1 = min(w, left + width - inset), min(h, top + height - inset)
    if x1 <= x0 or y1 <= y0:
        return np.zeros(3)
    return frame[y0:y1, x0:x1].reshape(-1, 3).mean(axis=0)


@dataclass
class Look:
    name: str
    protos: dict[str, list[Colour]] = field(default_factory=dict)  # role -> prototype colours
    radius: float = 36.0  # the largest summed channel gap that still counts as that role

    def classify(self, colour) -> str | None:
        """The role whose prototype is nearest (summed channel gaps), or None when nothing is within the radius."""
        c = np.asarray(colour, dtype=float)
        best, best_gap = None, self.radius
        for role, options in self.protos.items():
            for proto in options:
                gap = float(np.abs(c - np.asarray(proto)).sum())
                if gap < best_gap:
                    best, best_gap = role, gap
        return best

    def to_json(self) -> dict:
        return {"name": self.name, "radius": self.radius, "protos": {r: [list(map(float, p)) for p in ps] for r, ps in self.protos.items()}}

    @staticmethod
    def from_json(data: dict) -> "Look":
        return Look(str(data["name"]), {r: [tuple(p) for p in ps] for r, ps in data["protos"].items()}, float(data.get("radius", 36.0)))


def exact_look(name: str, colours: dict[str, Colour], radius: float = 36.0) -> Look:
    """A look made of one exact colour per role (what the skills compared before)."""
    return Look(name, {role: [colour] for role, colour in colours.items()}, radius)


# audit: keep (build time: tools/calibrate_looks.py builds the looks through the public package)
def calibrate(name: str, samples: dict[str, list], radius: float | None = None, max_protos: int = 8) -> Look:
    """Build a look from labelled patch colours: samples[role] = list of mean colours. Each role keeps up to `max_protos` prototypes (a textured sprite looks a little different in each place) (a simple spread: the colours furthest from
    the ones already kept), and the radius is set to just under half of the smallest gap between two different roles, so two roles can never claim the same patch."""
    protos: dict[str, list[Colour]] = {}
    for role, colours in samples.items():
        arr = np.asarray(colours, dtype=float)
        if len(arr) == 0:
            continue
        kept = [arr.mean(axis=0)]
        while len(kept) < max_protos:
            gaps = np.array([min(np.abs(c - k).sum() for k in kept) for c in arr])
            if gaps.max() < 10.0:
                break
            kept.append(arr[int(gaps.argmax())])
        protos[role] = [tuple(float(x) for x in k) for k in kept]
    look = Look(name, protos, 36.0)
    if radius is None:
        roles = list(protos)
        smallest = min((np.abs(np.asarray(a) - np.asarray(b)).sum() for i, r1 in enumerate(roles) for r2 in roles[i + 1:] for a in protos[r1] for b in protos[r2]), default=72.0)
        radius = max(12.0, min(60.0, smallest / 2 - 1))
    look.radius = float(radius)
    return look


# audit: keep (build time: tools/calibrate_looks.py writes the looks)
def save_looks(path: Path, looks: list[Look]) -> None:
    Path(path).write_text(json.dumps([lk.to_json() for lk in looks], indent=1), encoding="utf-8", newline="\n")


def load_looks(path: Path) -> list[Look]:
    try:
        return [Look.from_json(d) for d in json.loads(Path(path).read_text(encoding="utf-8"))]
    except (OSError, ValueError, KeyError, TypeError):
        return []


def role_mask(frame: np.ndarray, look: Look, role: str, top: int = 0) -> np.ndarray:
    """A boolean picture: True where a pixel is within the look's radius of any prototype of `role`; rows above `top` (the score bar) are always False."""
    mask = np.zeros(frame.shape[:2], dtype=bool)
    pixels = frame.astype(np.int16)
    for proto in look.protos.get(role, []):
        mask |= np.abs(pixels - np.array(proto, dtype=np.int16)).sum(axis=2) <= look.radius
    if top:
        mask[:top] = False
    return mask
