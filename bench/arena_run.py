"""Play an arena game headless with any brain, many seeds, and write one results file: the benchmark behind the unseen-games test and the credit-day stages.

The game runs in this process (the engine's arena pack: pure rules plus a picture). The buddy's turn is the real one (`playfellow_coop.session.take_turn`: look, shrink,
optionally mark, ask, check against the controls card, act); only the screen and the hands are virtual: the screen's picture is the game's render and a key press is
`game.step(key)`, one clock tick per action, so a slow brain meets the same game as a fast one. Nothing touches the real keyboard or a window.

An episode ends when the game is won or lost, the turn cap is reached, or the call cap is reached. What is recorded per episode: won, progress, turns, game ticks, brain calls,
tokens (in, cached, out), cost as the brain reports it, wall seconds and plan validity. Intervals are Wilson 95 percent. Every number in the file is measured by the run.
"""
from __future__ import annotations

import json
import math
import random
import sys
import time
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "pf-arena-run/1"
GAMES = {  # arena pack key -> (module, class); the engine owns the games, this table only names the ones we run
    "snake": ("arena_pack.snake", "Snake"), "box_push": ("arena_pack.box_push", "BoxPush"), "slide_2048": ("arena_pack.slide_2048", "Slide2048"),
    "lane_dash": ("arena_pack.lane_dash", "LaneDash"), "maze_chase": ("arena_pack.maze_chase", "MazeChase"), "key_caves": ("arena_pack.key_caves", "KeyCaves"),
    "turn_quest": ("arena_pack.turn_quest", "TurnQuest"), "brick_breaker": ("arena_pack.brick_breaker", "BrickBreaker"), "mini_chess": ("arena_pack.mini_chess", "MiniChess"),
}


def wilson(wins: int, n: int, z: float = 1.96) -> tuple[float, float]:
    """Wilson score interval for a proportion; (0, 1) when there are no episodes."""
    if n == 0:
        return 0.0, 1.0
    p = wins / n
    denom = 1 + z * z / n
    centre = (p + z * z / (2 * n)) / denom
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / denom
    return max(0.0, centre - half), min(1.0, centre + half)


class VirtualScreen:
    def __init__(self, game):
        self.game = game

    def find(self, title):
        from eyes import WindowBox
        width, height = self.game.pixel_size
        return WindowBox(0, 0, width, height)

    def in_front(self, title):
        return True

    def grab(self, box):
        return self.game.render()


class VirtualHands:
    """A key is one step of the game: `game.step(key)` presses it and moves the clock one tick. A wait is a step with no key."""

    def __init__(self, game, card):
        self.game, self.card = game, card
        self.pressed = []

    def do(self, step, box):
        action = self.card.actions[step.action]
        if getattr(action, "kind", "keys") == "keys" and getattr(action, "keys", None):
            key = action.keys[0] if isinstance(action.keys, (list, tuple)) else str(action.keys).split("+")[0]
            self.pressed.append(key)
            self.game.step(key)
        elif getattr(action, "kind", "") == "click" and step.x is not None:
            self.game.click(step.x, step.y)
            self.game.step(None)
        else:
            self.game.step(None)

    def on_stop(self):
        pass

    def resume(self):
        pass


def _frac(a, b):
    return max(0.0, min(1.0, a / b)) if b else 0.0


# A 0 to 1 progress score per game from the game's own progress() numbers (no ground truth about how to win is used, only how far it got). p0 is the first reading.
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


@dataclass
class Episode:
    game: str
    seed: int
    won: bool = False
    lost: bool = False
    progress: float | None = None
    turns: int = 0
    ticks: int = 0
    calls: int = 0
    tokens_in: int = 0
    tokens_cached: int = 0
    tokens_out: int = 0
    cost_usd: float = 0.0
    seconds: float = 0.0
    invalid_plans: int = 0
    ended: str = ""
    extra: dict = field(default_factory=dict)


def load_game(key: str, seed: int):
    import importlib
    module, cls = GAMES[key]
    return getattr(importlib.import_module(module), cls)(seed=seed)


def run_episode(game_key: str, seed: int, brain, *, max_turns: int = 30, max_calls: int = 30, settings=None, system: str | None = None,
                marker=None, tracer=None, engine_dir: Path | None = None) -> Episode:
    import controls
    import settings as engine_settings
    from brain.prompts import system_prompt
    from memory import Memory
    from safety import Safety
    from playfellow_coop import session
    from playfellow_coop.stage_timer import StageTimer

    engine_dir = engine_dir or ROOT.parent / "playfellow" / "software"
    game = load_game(game_key, seed)
    card = controls.load_card(engine_dir / "controls" / f"arena_{game_key}.yaml")
    cfg = settings or engine_settings.Settings(look_every_seconds=0.2, max_actions_per_step=4, image_width=480, goal=getattr(game, "goal", "") or engine_settings.Settings().goal)
    parts = type("Parts", (), {})()
    parts.brain, parts.card, parts.screen, parts.hands = brain, card, VirtualScreen(game), VirtualHands(game, card)
    parts.safety, parts.memory = Safety(60, max_calls), Memory(cfg.memory_steps)
    if marker is not None:
        parts.marker = marker
    if tracer is not None:
        parts.tracer = tracer
    sys_text = system or system_prompt(cfg, card)
    timer = StageTimer()
    episode = Episode(game_key, seed)
    parts.safety.start()
    p0 = dict(game.progress())
    started = time.perf_counter()
    while not game.done and episode.turns < max_turns and parts.safety.check() is None:
        timer.begin_turn()
        try:
            reply = session.take_turn(parts, cfg, sys_text, timer)
        except Exception as error:  # a brain error ends the episode, and says so
            episode.ended = "error:" + type(error).__name__
            break
        timer.end_turn()
        episode.turns += 1
        if reply is None or reply.confused or not reply.steps:
            episode.invalid_plans += 1
        usage = getattr(brain, "last_request", None) or {}
        episode.tokens_in += usage.get("tokens_in") or 0
        episode.tokens_cached += usage.get("tokens_cached") or 0
        episode.tokens_out += usage.get("tokens_out") or 0
        episode.cost_usd += usage.get("cost_usd") or 0.0
    episode.calls = getattr(parts.safety, "ai_calls", episode.turns)
    episode.seconds = round(time.perf_counter() - started, 2)
    episode.won, episode.lost, episode.ticks = bool(game.is_won()), bool(game.is_lost()), int(game.ticks)
    try:
        score = PROGRESS[game_key](p0, game.progress())
        episode.progress = round(1.0 if episode.won else score, 4)
    except Exception:
        episode.progress = None
    episode.ended = episode.ended or ("won" if episode.won else "lost" if episode.lost else "turn_cap")
    return episode


class RandomBrain:
    """The floor: a random allowed action each turn, in the same JSON the planner would send."""

    def __init__(self, card_keys, seed=0):
        self.keys, self.rng, self.last_request = list(card_keys), random.Random(seed), {}

    def ask(self, system, text, images):
        return json.dumps({"thought": "random", "say": "", "actions": [self.rng.choice(self.keys)]})


def summarise(episodes: list[Episode]) -> dict:
    n = len(episodes)
    wins = sum(e.won for e in episodes)
    lo, hi = wilson(wins, n)
    prog = [e.progress for e in episodes if e.progress is not None]
    return {"episodes": n, "wins": wins, "win_rate": round(wins / n, 3) if n else None, "wilson95": [round(lo, 3), round(hi, 3)],
            "mean_progress": round(sum(prog) / len(prog), 3) if prog else None, "mean_turns": round(sum(e.turns for e in episodes) / n, 2) if n else None,
            "mean_seconds": round(sum(e.seconds for e in episodes) / n, 2) if n else None, "invalid_plan_rate": round(sum(e.invalid_plans for e in episodes) / max(1, sum(e.turns for e in episodes)), 3),
            "tokens_in": sum(e.tokens_in for e in episodes), "tokens_cached": sum(e.tokens_cached for e in episodes), "tokens_out": sum(e.tokens_out for e in episodes),
            "cost_usd": round(sum(e.cost_usd for e in episodes), 5),
            "tokens_per_win": round((sum(e.tokens_in + e.tokens_out for e in episodes) / wins), 1) if wins else None,
            "usd_per_win": round(sum(e.cost_usd for e in episodes) / wins, 5) if wins else None}


def write_results(path: Path, condition: str, brain_name: str, model: str, games: list[str], episodes: list[Episode], note: str = "") -> None:
    by_game = {g: summarise([e for e in episodes if e.game == g]) for g in games}
    doc = {"schema": SCHEMA, "written": datetime.now().astimezone().isoformat(timespec="seconds"), "condition": condition, "brain": brain_name, "model": model,
           "note": note, "overall": summarise(episodes), "by_game": by_game, "episodes": [e.__dict__ for e in episodes]}
    with open(path, "x", encoding="utf-8", newline="\n") as handle:  # never overwrites a results file
        json.dump(doc, handle, indent=1)
