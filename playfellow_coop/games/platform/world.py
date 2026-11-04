"""Where the buddy has been: a map built from nothing but camera motion, the way a player keeps one in their head.

Position is the sum of the camera's shifts, in view-widths. Cells it passes through are remembered. A hard screen cut starts a new
room, joined to the last one. A way it could not pass is kept with the reason, and when a new ability arrives the blocked ways that
ability might open are offered again, nearest first: the metroidvania loop of get an ability, remember the wall, go back.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass, field

CELL = 0.5  # view-widths per map cell


@dataclass
class Blocked:
    room: int
    cell: tuple[int, int]
    reason: str  # "too_high", "wall", "gap", "door", "unknown"


@dataclass
class WorldMap:
    room: int = 0
    x: float = 0.0
    y: float = 0.0
    seen: dict = field(default_factory=lambda: {0: set()})
    links: dict = field(default_factory=lambda: {0: set()})
    blocked: list = field(default_factory=list)
    abilities: set = field(default_factory=set)
    furthest: float = 0.0

    OPENS = {"double_jump": {"too_high", "gap"}, "wall_jump": {"too_high", "wall"}, "dash": {"gap", "wall"}, "key": {"door"}, "hover": {"gap"}}

    @property
    def cell(self) -> tuple[int, int]:
        return round(self.x / CELL), round(self.y / CELL)

    def move(self, dx: float, dy: float) -> None:
        self.x += dx
        self.y += dy
        self.seen[self.room].add(self.cell)
        self.furthest = max(self.furthest, self.x)

    def new_room(self) -> int:
        """A hard cut: go to a room joined to this one (a known one is not recognised yet: pictures would be needed)."""
        new = max(self.seen) + 1
        self.seen[new], self.links[new] = set(), {self.room}
        self.links[self.room].add(new)
        self.room, self.x, self.y = new, 0.0, 0.0
        return new

    def note_blocked(self, reason: str = "unknown") -> None:
        if not any(b.room == self.room and b.cell == self.cell for b in self.blocked):
            self.blocked.append(Blocked(self.room, self.cell, reason))

    def learn_ability(self, name: str) -> list[Blocked]:
        """A new ability: the blocked ways it may open, nearest room first."""
        self.abilities.add(name)
        return self.worth_trying()

    def worth_trying(self) -> list[Blocked]:
        opens = set().union(*(self.OPENS.get(a, set()) for a in self.abilities)) if self.abilities else set()
        hits = [b for b in self.blocked if b.reason in opens or b.reason == "unknown"]
        return sorted(hits, key=lambda b: self.rooms_between(self.room, b.room))

    def rooms_between(self, start: int, goal: int) -> int:
        path = self.route(start, goal)
        return len(path) - 1 if path else 1_000_000

    def route(self, start: int, goal: int) -> list[int]:
        """The shortest list of rooms from start to goal, [] when none is known."""
        seen, queue = {start: None}, deque([start])
        while queue:
            now = queue.popleft()
            if now == goal:
                out = []
                while now is not None:
                    out.append(now)
                    now = seen[now]
                return out[::-1]
            for next_room in sorted(self.links.get(now, ())):
                if next_room not in seen:
                    seen[next_room] = now
                    queue.append(next_room)
        return []
