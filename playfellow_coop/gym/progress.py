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
}
