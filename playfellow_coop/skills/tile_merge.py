"""Slide-and-merge boards (the 2048-style skill): read the tile numbers from their colours, look two moves ahead, keep the big tile in a corner."""
from __future__ import annotations

from playfellow_coop.skills.base import Done, Frame
from playfellow_coop.skills.looks import Look, exact_look, patch_mean

SIZE, TILE, GAP, TOP = 4, 96, 8, 64
COLOURS = {0: (44, 44, 70), 2: (238, 228, 218), 4: (237, 224, 200), 8: (242, 177, 121), 16: (245, 149, 99),
           32: (246, 124, 95), 64: (246, 94, 59), 128: (237, 207, 114), 256: (237, 204, 97), 512: (60, 58, 50)}
ARENA_LOOK = exact_look("arena", {str(v): c for v, c in COLOURS.items()}, radius=14.0)  # one role per tile value
KEYS = ("left", "right", "up", "down")
WEIGHTS = [[4 ** (6 - x - y) for x in range(SIZE)] for y in range(SIZE)]  # weights fall away from the top-left corner


def read(frame: Frame, look: Look = ARENA_LOOK) -> list[list[int]]:
    """The tile numbers. Each tile is read from a small patch near its top-left corner, away from the number drawn in the middle. An unknown colour reads as empty."""
    board = []
    for gy in range(SIZE):
        row = []
        for gx in range(SIZE):
            left, top = GAP + gx * (TILE + GAP), TOP + GAP + gy * (TILE + GAP)
            role = look.classify(patch_mean(frame, left + 8, top + 8, 18, 18))
            row.append(int(role) if role and role.isdigit() else 0)
        board.append(row)
    return board


def slide_row(row):
    tiles = [v for v in row if v]
    out, i = [], 0
    while i < len(tiles):
        if i + 1 < len(tiles) and tiles[i] == tiles[i + 1]:
            out.append(tiles[i] * 2)
            i += 2
        else:
            out.append(tiles[i])
            i += 1
    return out + [0] * (SIZE - len(out))


def move(board, key):
    grid = [r[:] for r in board]
    if key in ("up", "down"):
        grid = [list(c) for c in zip(*grid)]
    if key in ("right", "down"):
        grid = [r[::-1] for r in grid]
    grid = [slide_row(r) for r in grid]
    if key in ("right", "down"):
        grid = [r[::-1] for r in grid]
    if key in ("up", "down"):
        grid = [list(c) for c in zip(*grid)]
    return grid


def score(board) -> float:
    empty = sum(row.count(0) for row in board)
    weighted = sum(WEIGHTS[y][x] * board[y][x] for y in range(SIZE) for x in range(SIZE))
    return empty * 2000.0 + weighted


def value(board, depth: int) -> float:
    """Expected value after the computer adds a tile: every empty cell, a 2 (90%) or a 4 (10%)."""
    empties = [(x, y) for y in range(SIZE) for x in range(SIZE) if not board[y][x]]
    if not empties:
        return best(board, depth)[1] if depth else score(board)
    if depth == 0:
        return score(board)
    if len(empties) > 6:  # sample a spread of cells on a roomy board; the choice hardly changes and it stays fast
        empties = empties[:: len(empties) // 6 + 1]
    total = 0.0
    for x, y in empties:
        for tile, weight in ((2, 0.9), (4, 0.1)):
            nxt = [r[:] for r in board]
            nxt[y][x] = tile
            total += weight * best(nxt, depth - 1)[1] if depth > 1 else weight * score(nxt)
    return total / len(empties)


def best(board, depth: int):
    choice, top = None, -1.0
    for key in KEYS:
        nxt = move(board, key)
        if nxt == board:
            continue
        v = value(nxt, depth)
        if v > top:
            choice, top = key, v
    return choice, top if choice else -1.0


class SlideMerge:
    name = "slide_merge"
    about = "Slide and merge numbered tiles toward a big tile in one corner, looking two moves ahead; use it for the whole game."
    max_steps = 1200

    def __init__(self, look: Look | None = None):
        self.look = look or ARENA_LOOK

    def reset(self) -> None:
        pass

    def next_key(self, frame: Frame) -> str | None:
        board = read(frame, self.look)
        choice, _ = best(board, 2)
        if choice is None:
            raise Done("no move changes the board")
        return choice
