"""A 0 to 1 progress score per game, from the game's own progress() numbers: how far it got, never how to win. The single definition used by the benchmark and the gym."""
from __future__ import annotations

import math


def _frac(a, b):
    return max(0.0, min(1.0, a / b)) if b else 0.0


# p0 is the first reading of the episode.
PROGRESS = {
    "snake": lambda p0, p: _frac(p["length"] - p0["length"], p["target"] - p0["length"]),
    "box_push": lambda p0, p: _frac((p["level"] - 1) + (p["boxes_on_goals"] / p["boxes"] if p["boxes"] else 0), p["levels"]),
    "slide_2048": lambda p0, p: _frac(math.log2(max(2, p["best_tile"])) - math.log2(max(2, p0["best_tile"])), math.log2(p["target"]) - math.log2(max(2, p0["best_tile"]))),
    "lane_dash": lambda p0, p: _frac(p["coins"], p["goal_coins"]),
    "maze_chase": lambda p0, p: 0.7 * _frac(p0["coins_left"] - p["coins_left"], p0["coins_left"]) + (0.3 if p["has_key"] else 0.0) + (0.0 if not p.get("won") else 0.0),
    "key_caves": lambda p0, p: _frac((p["room"] - 1) + (0.5 if p["has_key"] else 0) + (0.25 if p["has_boots"] else 0), p["rooms"]),
    "brick_breaker": lambda p0, p: _frac((p["level"] - 1) + 1 - _frac(p["bricks_left"], p0["bricks_left"]), p["levels"]),
    "mini_chess": lambda p0, p: _frac(p["moves"], p["survive"]),
    # the other seven built-in games (2 Nov): each stays below 1.0 until the game's own win; the gym adds the rest at the win
    "action_quest": lambda p0, p: min(0.99, _frac(p0["boss_hp"] - p["boss_hp"], p0["boss_hp"])),
    "mini_fighter": lambda p0, p: min(0.99, 0.5 * p["rounds"][0] + 0.45 * _frac(p0["cpu_hp"] - p["cpu_hp"], p0["cpu_hp"])),
    "ray_maze": lambda p0, p: 0.8 * _frac(p["hits"], p["targets"]),
    "tiny_kingdom": lambda p0, p: 0.9 * _frac(p["wave"], p["waves"]) if p["castle"] > 0 else 0.0,
    "top_racer": lambda p0, p: 0.95 * _frac(p["lap"] - p0["lap"], p["laps"]),
    "turn_quest": lambda p0, p: 0.6 * _frac(p["level"] - p0["level"], 4) + (0.2 if p["sword"] else 0.0) + (0.15 if p["enemy"] == "dragon" else 0.0),
}

# Open-source games played in a browser, scored by the same kind of function but NOT built-in arena games: kept apart so every loop
# over PROGRESS (the arena bench, the gym, the MCP server) still means "the arena's games".
OPEN_SOURCE_PROGRESS = {
    "osg_2048": lambda p0, p: _osg_2048(p0, p),  # the open-source 2048 (bench/osg_progress.py): best-tile climb, the score alone earns nothing
}


def _osg_2048(p0, p):
    from bench.osg_progress import progress  # imported on use: the bench file brings the open-source game's own score

    return progress(p0, p)
