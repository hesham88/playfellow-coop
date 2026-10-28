"""Push boxes onto goals (the puzzle skill): read walls, boxes, goals and the player from the picture, search for the whole move list, then walk it.

Search is breadth-first over (player, boxes) and finds the shortest solution; when a level has none (a box is stuck) it restarts the level.
"""
from __future__ import annotations

from collections import deque

from playfellow_coop.skills.base import Done, Frame
from playfellow_coop.skills.looks import Look, exact_look, patch_mean

TILE, TOP = 56, 64
WALL, GOAL, BOX, BOX_DONE, PLAYER = (62, 64, 86), (120, 220, 150), (196, 140, 60), (90, 190, 110), (40, 110, 255)
ARENA_LOOK = exact_look("arena", {"wall": WALL, "goal": GOAL, "box": BOX, "box_done": BOX_DONE, "player": PLAYER, "floor": (226, 232, 242)}, radius=40.0)
MOVES = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
MAX_STATES = 400_000


def _role_at(frame: Frame, look: Look, cx: int, cy: int, half: int = 8) -> str | None:
    return look.classify(patch_mean(frame, cx - half, cy - half, 2 * half, 2 * half))


def read(frame: Frame, look: Look = ARENA_LOOK):
    """(walls, boxes, goals, player, width, height) in cells, or None when the picture is not a level."""
    y = TOP + TILE // 2  # the first row of the level is wall from end to end: its extent is the level's width
    xs = [x for x in range(frame.shape[1]) if _role_at(frame, look, x, y, 1) == "wall"]
    if not xs:
        return None
    left = xs[0]
    width = max(1, round((xs[-1] + 1 - left) / TILE))
    x = left + TILE // 2
    ys = [yy for yy in range(TOP, frame.shape[0]) if _role_at(frame, look, x, yy, 1) == "wall"]
    height = max(0, round((ys[-1] + 1 - TOP) / TILE)) if ys else 0
    walls, boxes, goals, player = set(), set(), set(), None
    for gy in range(height):
        for gx in range(width):
            cx, cy = left + gx * TILE + TILE // 2, TOP + gy * TILE + TILE // 2
            role = _role_at(frame, look, cx, cy)
            if role == "wall":
                walls.add((gx, gy))
            elif role == "player":
                player = (gx, gy)
            elif role == "box":
                boxes.add((gx, gy))
            elif role == "box_done":
                boxes.add((gx, gy))
                goals.add((gx, gy))
            elif role == "goal":
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

    def __init__(self, look: Look | None = None):
        self.look = look or ARENA_LOOK

    def reset(self) -> None:
        self.plan: list[str] = []

    def next_key(self, frame: Frame) -> str | None:
        if self.plan:
            return self.plan.pop(0)
        seen = read(frame, self.look)
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
