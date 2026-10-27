"""Push boxes onto goals (the puzzle skill): read walls, boxes, goals and the player from the picture, search for the whole move list, then walk it.

Search is breadth-first over (player, boxes) and finds the shortest solution; when a level has none (a box is stuck) it restarts the level.
"""
from __future__ import annotations

from collections import deque

from playfellow_coop.skills.base import Done, Frame
from playfellow_coop.skills.pixels import near

TILE, TOP, VIEW_W = 56, 64, 480
WALL, GOAL, BOX, BOX_DONE, PLAYER = (62, 64, 86), (120, 220, 150), (196, 140, 60), (90, 190, 110), (40, 110, 255)
MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
MAX_STATES = 400_000


def read(frame: Frame):
    """(walls, boxes, goals, player, width, height) in cells, or None when the picture is not a level."""
    rows, cols = [], []
    y = TOP + TILE // 2
    xs = [x for x in range(VIEW_W) if near(frame, x, y, WALL, 8)]
    if not xs:
        return None
    left, width = xs[0], (xs[-1] - xs[0] + 1) // TILE
    x = left + TILE // 2
    ys = [yy for yy in range(TOP, frame.shape[0]) if near(frame, x, yy, WALL, 8)]
    height = (ys[-1] - TOP + 1) // TILE if ys else 0
    walls, boxes, goals, player = set(), set(), set(), None
    for gy in range(height):
        for gx in range(width):
            cx, cy = left + gx * TILE + TILE // 2, TOP + gy * TILE + TILE // 2
            if near(frame, cx, cy, WALL, 8):
                walls.add((gx, gy))
            elif near(frame, cx, cy, PLAYER, 20):
                player = (gx, gy)
            elif near(frame, cx, cy, BOX, 20):
                boxes.add((gx, gy))
            elif near(frame, cx, cy, BOX_DONE, 20):
                boxes.add((gx, gy))
                goals.add((gx, gy))
            elif near(frame, cx, cy, GOAL, 20):
                goals.add((gx, gy))
    if player is None:
        return None
    return walls, boxes, goals, player, width, height


def solve(walls, boxes, goals, player):
    """The shortest list of keys that puts every box on a goal, or None."""
    start = (player, frozenset(boxes))
    if start[1] == goals:
        return []
    queue, came = deque([start]), {start: None}
    while queue and len(came) < MAX_STATES:
        state = queue.popleft()
        (px, py), bxs = state
        for key, (dx, dy) in MOVES.items():
            target = (px + dx, py + dy)
            if target in walls:
                continue
            new_boxes = bxs
            if target in bxs:
                beyond = (target[0] + dx, target[1] + dy)
                if beyond in walls or beyond in bxs:
                    continue
                new_boxes = (bxs - {target}) | {beyond}
            nxt = (target, new_boxes)
            if nxt in came:
                continue
            came[nxt] = (state, key)
            if new_boxes == goals:
                keys = []
                while came[nxt]:
                    nxt, k = came[nxt][0], came[nxt][1]
                    keys.append(k)
                return keys[::-1]
            queue.append(nxt)
    return None


class PushBoxes:
    name = "push_boxes"
    about = "Solve box-pushing levels: find the shortest way to put every box on a goal and walk it, level after level."
    max_steps = 400

    def reset(self) -> None:
        self.plan: list[str] = []

    def next_key(self, frame: Frame) -> str | None:
        if self.plan:
            return self.plan.pop(0)
        seen = read(frame)
        if seen is None:
            raise Done("no level in the picture")
        walls, boxes, goals, player, _, _ = seen
        keys = solve(walls, boxes, goals, player)
        if keys is None:
            self.plan = []
            return "r"  # a box is stuck: start the level again
        if not keys:
            raise Done("every box is on a goal")
        self.plan = keys
        return self.plan.pop(0)
