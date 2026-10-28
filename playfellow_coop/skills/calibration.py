"""Build a Look for a game by watching it be played (BUILD TIME only).

While a look is being built, the labels come from the game's own state (where the head really is, which tile is a wall): that is how we learn what each thing looks like in a given skin.
Nothing here runs while a skill plays; a skill only ever reads pixels through the finished look. A game with a new skin gets a new look by running `calibrate_look` once on it.
"""
from __future__ import annotations

import random

import numpy as np

from playfellow_coop.skills import grid_chase, lane_runner, paddle_track, tile_merge
from playfellow_coop.skills.box_pusher import TILE as BOX_TILE, TOP as BOX_TOP
from playfellow_coop.skills.looks import Look, patch_mean
from playfellow_coop.skills.looks_build import calibrate

KEYS = {"snake": ("up", "down", "left", "right"), "box_push": ("up", "down", "left", "right"), "slide_2048": ("up", "down", "left", "right"),
        "lane_dash": ("left", "right", "up", "down") + (None,) * 10, "brick_breaker": ("left", "right", "space", None)}


def _frame(game) -> np.ndarray:
    return np.asarray(game.render().convert("RGB"))


def sample_snake(game, frame, out) -> None:
    cells = {tuple(c): ("head" if i == 0 else "body") for i, c in enumerate(game.body)}
    if game.food:
        cells[tuple(game.food)] = "food"
    for gy in range(grid_chase.GRID):
        for gx in range(grid_chase.GRID):
            role = cells.get((gx, gy), "floor")
            out.setdefault(role, []).append(patch_mean(frame, gx * grid_chase.TILE, grid_chase.TOP + gy * grid_chase.TILE, grid_chase.TILE, grid_chase.TILE, grid_chase.INSET))


def sample_box_push(game, frame, out) -> None:
    from arena_pack import box_push as bp  # the game module itself (public or re-skinned): only its rules data is used
    rows = bp.LEVELS[game.level_no]
    width = max(len(r) for r in rows)
    left = (frame.shape[1] - width * BOX_TILE) // 2  # a level is centred in the picture
    for y, row in enumerate(rows):
        for x in range(len(row)):
            cell = (x, y)
            if cell in game.walls:
                role = "wall"
            elif cell == game.player:
                role = "player"
            elif cell in game.boxes:
                role = "box_done" if cell in game.goals else "box"
            elif cell in game.goals:
                role = "goal"
            else:
                role = "floor"
            cx, cy = left + x * BOX_TILE + BOX_TILE // 2, BOX_TOP + y * BOX_TILE + BOX_TILE // 2
            out.setdefault(role, []).append(patch_mean(frame, cx - 8, cy - 8, 16, 16))


def sample_2048(game, frame, out) -> None:
    for gy in range(tile_merge.SIZE):
        for gx in range(tile_merge.SIZE):
            left, top = tile_merge.GAP + gx * (tile_merge.TILE + tile_merge.GAP), tile_merge.TOP + tile_merge.GAP + gy * (tile_merge.TILE + tile_merge.GAP)
            out.setdefault(str(game.board[gy][gx]), []).append(patch_mean(frame, left + 8, top + 8, 18, 18))


def sample_lane(game, frame, out) -> None:
    bottom = lane_runner.TOP + lane_runner.HORIZON * lane_runner.ROW_H
    at = {(lane, ahead): kind for lane, ahead, kind in game.items}
    for lane in range(lane_runner.LANES):
        left = lane * lane_runner.LANE_W
        for ahead in range(0, lane_runner.HORIZON + 1):
            upper = bottom - ahead * lane_runner.ROW_H
            kind = at.get((lane, ahead))
            for probe, (dx, dy) in lane_runner.PROBES.items():
                role = probe if probe == kind else "road"
                if kind is not None and probe != kind:
                    continue  # another kind of thing sits here: only its own probe is labelled
                if ahead <= 1 and lane == game.lane:
                    continue  # the runner stands here (a jump lifts it into the next row too)
                out.setdefault(role, []).append(patch_mean(frame, left + dx - 5, upper + dy - 3, 10, 6))
    lift = 14 if game.air else 0
    tall = 14 if game.slide else 34
    rect_top, rect_bottom = bottom + lane_runner.ROW_H - 4 - tall - lift, bottom + lane_runner.ROW_H - 4 - lift
    x = game.lane * lane_runner.LANE_W + 55
    for y in range(rect_top + 2, rect_bottom - 2, 2):
        out.setdefault("player", []).append(patch_mean(frame, x, y, 10, 2))


def sample_brick(game, frame, out) -> None:
    from arena_pack import brick_breaker as bb
    top = 64
    out.setdefault("paddle", []).append(patch_mean(frame, int(game.paddle) - 30, top + bb.PADDLE_Y + 3, 60, 4))
    x, y = game.ball
    out.setdefault("ball", []).append(patch_mean(frame, int(x) - 2, top + int(y) - 2, 4, 4))
    for (bx, by), hp in game.bricks.items():
        out.setdefault("brick", []).append(patch_mean(frame, int(bx) + 6, top + int(by) + 5, bb.BRICK_W - 12, bb.BRICK_H - 10))


def augment_lane(game, samples) -> None:
    """Fill the track with one kind of thing at every place, one kind at a time, so each thing is seen in every lane and row (a textured sprite looks a little different in each).
    Build time only: the game state is set directly, which a skill never does."""
    for kind in ("train", "low", "high", "coin"):
        game.items = [[lane, ahead, kind] for lane in range(lane_runner.LANES) for ahead in range(2, lane_runner.HORIZON + 1)]
        sample_lane(game, _frame(game), samples)
    game.items = []


def augment_brick(game, samples) -> None:
    """Show every level's bricks, so every strength a brick can have (each is drawn in its own colour) is in the look, not only the strengths of the first level. Build time only."""
    from arena_pack import brick_breaker as bb
    for level in range(len(bb.LEVELS)):
        game.level_no = level
        game._load()
        sample_brick(game, _frame(game), samples)


AUGMENT = {"lane_dash": augment_lane, "brick_breaker": augment_brick}
SAMPLERS = {"snake": sample_snake, "box_push": sample_box_push, "slide_2048": sample_2048, "lane_dash": sample_lane, "brick_breaker": sample_brick}


def calibrate_look(game_key: str, name: str, make_game, seeds=range(8), steps: int = 90, rng_seed: int = 0) -> Look:
    """Play the game with random keys, label every frame from the game's state, and build the look from what each thing looked like."""
    samples: dict[str, list] = {}
    rng = random.Random(rng_seed)
    for seed in seeds:
        game = make_game(seed)
        for _ in range(steps):
            if game.done:
                break
            SAMPLERS[game_key](game, _frame(game), samples)
            game.step(rng.choice(KEYS[game_key]))
        if game_key in AUGMENT and not game.done:
            AUGMENT[game_key](game, samples)
    return calibrate(name, samples)
