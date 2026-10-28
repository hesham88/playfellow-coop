"""From pixels to the structured observation a model-written skill reads (research R1 section 3.3: "the generated method receives pre-parsed normalised coordinates").

The skill never sees pixels. `PixelObserver` reads a picture through a skill's `Look` (the same colour prototypes the hand-written skills use, or the avatar colour found by key probing) and
returns the dict the synthesizer's contract promises: "self": [x, y], "items" and "enemies": lists of [x, y, vx, vy], everything in 0..1, plus "t", "hud" and a danger level with the
direction away from it. `ActionMapper` turns the skill's action back into the game's keys. Both are generic: a game is described by an `ObsSpec` naming which roles are the avatar, the
things to collect and the things to avoid.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.skills.looks import Look, role_mask


@dataclass
class ObsSpec:
    self_role: str
    item_roles: tuple[str, ...] = ()
    enemy_roles: tuple[str, ...] = ()
    top: int = 0  # rows above this are the score bar and are ignored
    danger_radius: float = 0.15


def _centroids(mask: np.ndarray, cap: int = 24) -> list[tuple[float, float]]:
    """Centres of the connected groups of a role mask (at most `cap`, the biggest first), as (x, y) pixels."""
    from playfellow_coop.universal.motion import components
    blobs = sorted(components(mask, min_area=3), key=lambda b: -b.area)[:cap]
    return [b.centre for b in blobs]


class PixelObserver:
    def __init__(self, look: Look, spec: ObsSpec):
        self.look, self.spec = look, spec
        self._previous: dict[str, list[tuple[float, float]]] = {}
        self.t = 0

    def reset(self) -> None:
        self._previous, self.t = {}, 0

    def _read(self, frame: np.ndarray, role: str) -> list[tuple[float, float]]:
        return _centroids(role_mask(frame, self.look, role, self.spec.top))

    def build(self, frame: np.ndarray) -> dict:
        h, w = frame.shape[:2]
        norm = lambda p: (p[0] / w, p[1] / h)  # noqa: E731
        me = self._read(frame, self.spec.self_role)
        position = norm(me[0]) if me else None
        obs: dict = {"self": [position[0], position[1]] if position else [0.5, 0.5], "items": [], "enemies": [], "hud": {}, "t": self.t, "danger": 0.0, "escape": None,
                     "visible": position is not None}
        for kind, roles in (("items", self.spec.item_roles), ("enemies", self.spec.enemy_roles)):
            found = [norm(c) for r in roles for c in self._read(frame, r)]
            previous = [norm(c) for r in roles for c in self._previous.get(r, [])]
            rows = []
            for p in found:
                before = min(previous, key=lambda q: (q[0] - p[0]) ** 2 + (q[1] - p[1]) ** 2) if previous else p
                rows.append([p[0], p[1], p[0] - before[0], p[1] - before[1]])
            obs[kind] = rows
        for role in set(self.spec.item_roles) | set(self.spec.enemy_roles):
            self._previous[role] = self._read(frame, role)
        if position and obs["enemies"]:
            nearest = min(obs["enemies"], key=lambda e: (e[0] - position[0]) ** 2 + (e[1] - position[1]) ** 2)
            dx, dy = position[0] - nearest[0], position[1] - nearest[1]
            distance = float(np.hypot(dx, dy))
            if distance < self.spec.danger_radius:
                obs["danger"] = float(min(1.0, 1.0 - distance / self.spec.danger_radius + 0.5))
                obs["escape"] = [dx / (distance or 1.0), dy / (distance or 1.0)]
        self.t += 1
        return obs


@dataclass
class ActionMapper:
    """The skill's {"move": [dx, dy], "buttons": [...]} as one key of the game's own set. The dominant axis wins; a button maps through `buttons`; nothing to do is None."""
    keys: tuple[str, ...]
    buttons: dict[str, str] = field(default_factory=dict)  # button name -> key, e.g. {"fire": "space", "jump": "space"}
    dead_zone: float = 0.3

    def key_for(self, action: dict) -> str | None:
        for name in action.get("buttons", []):
            key = self.buttons.get(name)
            if key in self.keys:
                return key
        dx, dy = action["move"]
        if max(abs(dx), abs(dy)) < self.dead_zone:
            return None
        if abs(dx) >= abs(dy):
            key = "right" if dx > 0 else "left"
        else:
            key = "down" if dy > 0 else "up"
        return key if key in self.keys else None
