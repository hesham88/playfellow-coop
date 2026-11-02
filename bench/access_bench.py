"""The accessibility benchmark: does the buddy do the part it was asked for, hand the controls back, and never break a safety rule?

It runs the real assist code (`playfellow_coop.assist.Assist`) and the real split-controls guard (`OwnedKeys`) on the arena games, from pixels,
with the local skills (no model, no network, $0). It does NOT simulate a disabled player: between two requests the player simply rests while the
game runs on, and every request is "make the next quarter of progress in this game", judged by the game's own progress numbers.

    python -m bench.access_bench --seeds 5          # writes results/access/access-<date>.json

Conditions:
  assist  the buddy plays each asked-for part with every key of the game;
  split   the player keeps one key and the buddy plays without it: the key the buddy pressed least (but at least once) in its own unsplit run
          on the same game and seed; the guard refuses that key and every refusal is counted;
  random  a buddy that presses random keys of the game: the floor the skills must beat.

Counted per request: done or not, buddy steps, buddy key presses (presses the player did not have to make), refused presses, and breaches: a kept
key that reached the game, or a key the game does not have. A breach count above zero is a failure of the whole run, not a statistic."""
from __future__ import annotations

import argparse
import datetime
import json
import math
import random
import subprocess
from pathlib import Path

from playfellow_coop.assist import Assist, OwnedKeys
from playfellow_coop.gym.env import PlayfellowGym
from playfellow_coop.skills.base import Done
from playfellow_coop.skills.registry import SKILLS

GAMES = ("snake", "box_push", "slide_2048", "lane_dash", "brick_breaker")
CONDITIONS = ("assist", "split", "random")
STEP = 0.25  # each request asks for the next quarter of the game's progress
REQUESTS = 4
PART_TURNS = 600  # the turn limit of one asked-for part
REST_TICKS = 10  # the player's rest between two requests: the world goes on, nothing is pressed
OUT = Path(__file__).resolve().parents[1] / "results" / "access"


class Recorder:
    """The key backend the guard wraps: it records what really reaches the game."""

    def __init__(self):
        self.down: list[str] = []

    def keyDown(self, key):  # noqa: N802
        self.down.append(key)


def wilson(k: int, n: int, z: float = 1.96) -> tuple[float, float]:
    if n == 0:
        return 0.0, 0.0
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return round(max(0.0, centre - half), 4), round(min(1.0, centre + half), 4)


def episode(game_key: str, seed: int, condition: str, load_game, requests: int = REQUESTS, part_turns: int | None = None, owned=()) -> dict:
    env = PlayfellowGym(game_key, load_game, seed=seed)
    obs, info = env.reset()
    if part_turns is None:  # a quarter of the game's own maximum length, never less than PART_TURNS (brick breaker needs ~1,300 steps a quarter)
        part_turns = max(PART_TURNS, int(getattr(env.game, "max_ticks", 0) or 0) // requests)
    keys = list(env.action_space)
    owned = set(owned) if condition == "split" else set()
    rec = Recorder()
    guard = OwnedKeys(rec, owned)
    skill = SKILLS[game_key]() if condition != "random" else None
    if skill is not None:
        skill.reset()
    rng = random.Random(seed * 7919 + 17)
    ended = {"over": False}
    target = {"p": 0.0}
    assist = Assist(max_turns=part_turns, done=lambda request, _p: "game_progress" if (ended["over"] or env._last >= target["p"] - 1e-9) else False)
    parts_out, breaches, skill_done = [], 0, False
    for n in range(requests):
        if ended["over"]:
            break
        target["p"] = min(1.0, round(env._last + STEP, 6))
        assist.begin(f"make the next quarter of progress ({n + 1}/{requests})", 0)
        line = None
        while line is None:
            key = None
            if skill is not None and not skill_done:
                try:
                    key = skill.next_key(obs)
                except Done:
                    skill_done = True
            elif skill is None:
                key = rng.choice(keys)
            pressed = 0
            if key is not None:
                before = len(rec.down)
                guard.keyDown(key)
                if len(rec.down) > before:  # it reached the game
                    pressed = 1
                    if key in owned or key not in keys:
                        breaches += 1
                else:
                    key = None  # refused: the game gets no key this tick
            obs, _, terminated, truncated, info = env.step(key)
            ended["over"] = bool(terminated or truncated)
            line = assist.after_turn(None, pressed, 0)
        record = dict(assist.log[-1])
        record["done"] = bool(record["done"]) and env._last >= target["p"] - 1e-9  # a game that ended short of the target is not "done"
        record.pop("seconds", None)
        record.pop("ai_calls", None)
        parts_out.append(record)
        for _ in range(REST_TICKS):  # the player's turn: nothing is pressed, the world goes on
            if ended["over"]:
                break
            obs, _, terminated, truncated, info = env.step(None)
            ended["over"] = bool(terminated or truncated)
    card = env.card()
    used = {k: rec.down.count(k) for k in keys}
    return {"game": game_key, "seed": seed, "condition": condition, "owned": sorted(owned), "parts": parts_out, "key_use": used,
            "refused": guard.refused, "breaches": breaches, "won": card.won, "progress": round(card.progress, 4)}


def summarise(episodes: list[dict]) -> dict:
    rows = {}
    for cond in CONDITIONS:
        for game in sorted({e["game"] for e in episodes}) + ["ALL"]:
            eps = [e for e in episodes if e["condition"] == cond and (game == "ALL" or e["game"] == game)]
            if not eps:
                continue
            parts = [p for e in eps for p in e["parts"]]
            done = [p for p in parts if p["done"]]
            rows[f"{cond}/{game}"] = {
                "condition": cond, "game": game, "episodes": len(eps), "requests": len(parts), "done": len(done),
                "done_rate": round(len(done) / len(parts), 4) if parts else 0.0, "done_rate_95": wilson(len(done), len(parts)),
                "mean_steps_when_done": round(sum(p["turns"] for p in done) / len(done), 1) if done else None,
                "presses_spared": sum(p["actions"] for p in parts), "refused": sum(e["refused"] for e in eps),
                "breaches": sum(e["breaches"] for e in eps), "games_won": sum(e["won"] for e in eps),
            }
    return rows


def _commit() -> str:
    try:
        return subprocess.run(["git", "rev-parse", "--short", "HEAD"], capture_output=True, text=True, cwd=Path(__file__).parent, timeout=10).stdout.strip()
    except Exception:
        return "unknown"


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--games", default=",".join(GAMES))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    from bench import arena_run as ar

    episodes = []
    for game in [g for g in args.games.split(",") if g]:
        for seed in range(args.seeds):
            load = lambda s, g=game: ar.load_game(g, s)  # noqa: E731
            plain = episode(game, seed, "assist", load)
            used = {k: n for k, n in plain["key_use"].items() if n > 0}
            keep = [min(used, key=lambda k: (used[k], k))] if len(used) > 1 else []
            episodes += [plain, episode(game, seed, "split", load, owned=keep), episode(game, seed, "random", load)]
    rows = summarise(episodes)
    result = {"schema": "pf-access/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "brain": "local skills (no model, no network, $0)", "step": STEP, "requests_per_episode": REQUESTS, "part_turns": PART_TURNS,
              "part_turns_rule": "max(PART_TURNS, the game's max_ticks / requests)", "rest_ticks": REST_TICKS, "split_rule": "the player keeps the key the buddy pressed least (at least once) in its unsplit run on the same game and seed", "split_note": "The arena skills are not told about the split: a refused key is simply a lost move, so the split column here measures "
              "safety (no kept key reaches the game) and the cost of losing a key to a buddy that cannot plan around it, not split-aware "
              "play. bench/osg_2048.py shows a buddy that picks its best remaining key.",
              "honesty": "No disabled player was simulated or involved: the player rests between requests. "
              "Each request is 'the next quarter of progress', judged by the game's own numbers.", "summary": rows, "episodes": episodes}
    out = Path(args.out) if args.out else OUT / f"access-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    breaches = sum(e["breaches"] for e in episodes)
    for key in sorted(r for r in rows if r.endswith("/ALL")):
        r = rows[key]
        print(f"{key:12} done {r['done']}/{r['requests']} ({r['done_rate']:.0%}, 95% {r['done_rate_95']}) spared {r['presses_spared']} refused {r['refused']} breaches {r['breaches']}")
    print("wrote", out)
    return 1 if breaches else 0


if __name__ == "__main__":
    raise SystemExit(main())
