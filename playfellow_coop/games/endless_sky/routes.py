"""Routes through the star map, from the game's own data/map systems.txt (the same links the hyperdrive follows).

The map's Find refuses a system the pilot has not explored, so a route to a new system is keyed the way the game keys it: with no plan set, the
jump key on the map picks the link at the smallest clockwise angle from straight up, and each further press moves clockwise to the next link
(MapDetailPanel::KeyDown). One hop at a time: on arrival the route is worked out again from where the ship really is.
"""
from __future__ import annotations

import math
from collections import deque
from pathlib import Path

from playfellow_coop.games.endless_sky.save import parse

MAP_FILE = Path(r"F:\Program Files\Endless Sky\data\map systems.txt")


class StarMap:
    def __init__(self, positions: dict[str, tuple[float, float]], links: dict[str, list[str]]):
        self.positions, self.links = positions, links

    @classmethod
    def from_text(cls, text: str) -> "StarMap":
        positions, links = {}, {}
        for node in parse(text).find_all("system"):
            pos = node.find("pos")
            if pos is None or len(pos.tokens) < 3:
                continue
            name = node.value()
            positions[name] = (float(pos.tokens[1]), float(pos.tokens[2]))
            links[name] = [c.value() for c in node.find_all("link")]
        return cls(positions, links)

    @classmethod
    def load(cls, path: Path = MAP_FILE) -> "StarMap":
        return cls.from_text(Path(path).read_text(encoding="utf-8"))

    def route(self, start: str, goal: str) -> list[str]:
        """The systems to pass through after `start`, ending with `goal`; empty when there is no way."""
        if start == goal:
            return []
        came = {start: None}
        queue = deque([start])
        while queue:
            here = queue.popleft()
            for near in self.links.get(here, []):
                if near not in came:
                    came[near] = here
                    if near == goal:
                        path = [goal]
                        while came[path[-1]] != start:
                            path.append(came[path[-1]])
                        return path[::-1]
                    queue.append(near)
        return []

    def clockwise_links(self, system: str) -> list[str]:
        """The links out of `system` in the order the map's jump key walks them: clockwise from straight up (screen y grows downward)."""
        x, y = self.positions[system]

        def angle(other: str) -> float:
            ox, oy = self.positions[other]
            return math.atan2(ox - x, -(oy - y)) % (2 * math.pi)

        return sorted((s for s in self.links.get(system, []) if s in self.positions), key=angle)

    def presses_to(self, system: str, near: str) -> int:
        """How many presses of the map's jump key select the link `near` from `system`, starting with no plan set."""
        return self.clockwise_links(system).index(near) + 1

    def map_offset(self, here: str, other: str, zoom: float = 1.0) -> tuple[float, float]:
        """Where `other` is drawn on the map, in pixels from the window's centre, when the map is centred on `here` (it opens so)."""
        hx, hy = self.positions[here]
        ox, oy = self.positions[other]
        return (ox - hx) * zoom, (oy - hy) * zoom

    def fuel_jumps(self, fuel_share: float, capacity: float = 300.0, per_jump: float = 100.0) -> int:
        """Whole jumps left in the tank (a Sparrow: 300 fuel, 100 a hyperdrive jump)."""
        return int(fuel_share * capacity / per_jump + 0.15)
