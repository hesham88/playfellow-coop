"""Building a look (BUILD TIME only): turn labelled patch colours into prototypes, and save looks as JSON. Not shipped inside the app: the app only reads looks (see looks.py)."""
from __future__ import annotations

import json
from pathlib import Path

import numpy as np

from playfellow_coop.skills.looks import Look


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


def save_looks(path: Path, looks: list[Look]) -> None:
    Path(path).write_text(json.dumps([lk.to_json() for lk in looks], indent=1), encoding="utf-8", newline="\n")
