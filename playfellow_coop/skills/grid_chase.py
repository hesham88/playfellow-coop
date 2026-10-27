"""Chase the food on a grid without trapping yourself (the snake-style skill).

It reads the head, the body and the food from the picture, finds the shortest safe way to the food, and keeps enough free room to stay alive.
"""
from __future__ import annotations

from collections import deque

from playfellow_coop.skills.base import Frame
from playfellow_coop.skills.pixels import near

GRID, TILE, TOP = 10, 44, 64
HEAD, BODY, FOOD = (182, 255, 59), (110, 220, 120), (255, 61, 203)
STEPS = {"up": (0, -1), "down": (0, 1), "left": (-1, 0), "right": (1, 0)}
OPPOSITE = {"up": "down", "down": "up", "left": "right", "right": "left"}


def read(frame: Frame):
    head, body, food = None, set(), None
    for gy in range(GRID):
        for gx in range(GRID):
            x, y = gx * TILE + TILE // 2, TOP + gy * TILE + TILE // 2
            if near(frame, x, y, HEAD):
                head = (gx, gy)
            elif near(frame, x, y, BODY):
                body.add((gx, gy))
            elif near(frame, x, y, FOOD):
                food = (gx, gy)
    return head, body, food


def ordered(head, body):
    """The body cells from the neck to the tail, by walking from the head."""
    chain, seen, here = [], {head}, head
    while True:
        step = next(((here[0] + dx, here[1] + dy) for dx, dy in STEPS.values() if (here[0] + dx, here[1] + dy) in body and (here[0] + dx, here[1] + dy) not in seen), None)
        if step is None:
            return chain
        chain.append(step)
        seen.add(step)
        here = step


def inside(cell) -> bool:
    return 0 <= cell[0] < GRID and 0 <= cell[1] < GRID


def distance(start, goal, blocked) -> int | None:
    queue, seen = deque([(start, 0)]), {start}
    while queue:
        cell, d = queue.popleft()
        if cell == goal:
            return d
        for dx, dy in STEPS.values():
            nxt = (cell[0] + dx, cell[1] + dy)
            if inside(nxt) and nxt not in blocked and nxt not in seen:
                seen.add(nxt)
                queue.append((nxt, d + 1))
    return None


def path_to(start, goal, blocked):
    """The shortest list of cells from `start` (excluded) to `goal` (included) avoiding `blocked`, or None."""
    queue, came = deque([start]), {start: None}
    while queue:
        cell = queue.popleft()
        if cell == goal:
            out = []
            while cell != start:
                out.append(cell)
                cell = came[cell]
            return out[::-1]
        for dx, dy in STEPS.values():
            nxt = (cell[0] + dx, cell[1] + dy)
            if inside(nxt) and nxt not in blocked and nxt not in came:
                came[nxt] = cell
                queue.append(nxt)
    return None


def stays_alive_after(snake, way) -> bool:
    """Walk the snake along `way` (it grows only on the last cell); after eating, can it still reach its own tail with room to spare?"""
    cells = list(snake)
    for i, cell in enumerate(way):
        cells.insert(0, cell)
        if i < len(way) - 1:
            cells.pop()
    head, rest = cells[0], cells[1:]
    return room(head, set(rest)) >= len(cells) and (len(cells) < 3 or distance(head, cells[-1], set(rest[:-1])) is not None)


def room(start, blocked) -> int:
    queue, seen = deque([start]), {start}
    while queue:
        cell = queue.popleft()
        for dx, dy in STEPS.values():
            nxt = (cell[0] + dx, cell[1] + dy)
            if inside(nxt) and nxt not in blocked and nxt not in seen:
                seen.add(nxt)
                queue.append(nxt)
    return len(seen)


class ChaseFood:
    name = "chase_food"
    about = "Steer a growing snake to the food, avoiding walls and its own body; use it for the whole game."
    max_steps = 1500

    def reset(self) -> None:
        self.cells: list = []  # the snake, head first, kept up to date from the pictures (a coiled snake cannot be ordered from one picture)
        self.heading = (1, 0)  # the game starts moving right

    def _track(self, head, body) -> list:
        if self.cells and head != self.cells[0]:
            self.cells.insert(0, head)
        if not self.cells:
            self.cells = [head] + ordered(head, body)
        while len(self.cells) > len(body) + 1:
            self.cells.pop()
        if set(self.cells[1:]) != body or self.cells[0] != head:  # out of step with the picture: start again from it
            self.cells = [head] + ordered(head, body)
        return self.cells

    def next_key(self, frame: Frame) -> str | None:
        from playfellow_coop.skills.base import Done
        head, body, food = read(frame)
        if head is None:
            raise Done("no head in the picture")
        snake = self._track(head, body)
        heading = self.heading
        if food is not None:  # the plain way first: the shortest path, if eating at the end still leaves the snake a way out
            way = path_to(head, food, set(snake[:-1]))
            if way and stays_alive_after(snake, way):
                step = (way[0][0] - head[0], way[0][1] - head[1])
                if step != (-heading[0], -heading[1]):
                    return self._go(step)
        best, best_score = None, None
        for key, (dx, dy) in STEPS.items():
            if (dx, dy) == (-heading[0], -heading[1]):
                continue
            nxt = (head[0] + dx, head[1] + dy)
            if not inside(nxt):
                continue
            eats = nxt == food
            kept = snake if eats else snake[:-1]  # the tail leaves its cell unless the snake grows
            if nxt in kept:
                continue
            after = [nxt] + kept
            free = room(nxt, set(kept))
            safe = free >= len(after)
            d = 0 if eats else (distance(nxt, food, set(kept)) if food else None)
            tail_d = distance(nxt, after[-1], set(kept[:-1])) if len(after) > 2 else 0
            score = (0 if safe else 1, d if d is not None else 999, 0 if tail_d is not None else 1, -free)
            if best_score is None or score < best_score:
                best, best_score = key, score
        if best is None:
            return None  # boxed in: nothing safe, let the game decide
        return self._go(STEPS[best])

    def _go(self, step):
        self.heading = step
        return next(key for key, delta in STEPS.items() if delta == step)
