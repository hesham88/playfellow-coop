"""Rung 4 of the ladder: the model writes its own skill for a game, starting from a skill that does nothing.

    MODEL_API_KEY=... python -m bench.skillsmith_live --games brick_breaker,lane_dash --rounds 3 --max-usd 2.0

For each game: the current skill is IDLE (does nothing; the hand-written skill for that game is never used or shown). Each round Muse Spark
reads the current skill's recorded observations and writes candidate controllers; each must pass the static gate, runs sandboxed, and is
scored by the gym on the VALIDATION seeds; a candidate is promoted only if it strictly beats the current skill there. After the rounds the
final skill is played on HELD-OUT seeds it was never selected on, and its wins and progress are what this file reports. Pixels in, keys out:
the skill reads a picture through colour prototypes, like the hand-written skills."""
from __future__ import annotations

import argparse
import datetime
import json
import os
import tempfile
from pathlib import Path

from bench import arena_run as ar
from bench.access_bench import _commit, wilson

ROOT = Path(__file__).resolve().parents[1]
IDLE = '''
class GeneratedArenaSkill:
    def compute_action(self, obs):
        return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
'''


def setups():
    from playfellow_coop.gym.obs import ActionMapper, ObsSpec
    from playfellow_coop.skills import lane_runner, paddle_track
    return {
        "brick_breaker": ("break every brick without losing the ball", paddle_track.ARENA_LOOK, ObsSpec(self_role="paddle", item_roles=("ball",), top=64),
                          ActionMapper(keys=("left", "right", "space"), buttons={"fire": "space"}), 3000),
        "lane_dash": ("collect coins and dodge trains, low and high bars", lane_runner.ARENA_LOOK,
                      ObsSpec(self_role="player", item_roles=("coin",), enemy_roles=("train", "low", "high"), top=64),
                      ActionMapper(keys=("left", "right", "up", "down"), buttons={"jump": "up", "dash": "down"}), 700),
    }


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default="brick_breaker,lane_dash")
    ap.add_argument("--rounds", type=int, default=3)
    ap.add_argument("--candidates", type=int, default=2)
    ap.add_argument("--max-usd", type=float, default=2.0)
    args = ap.parse_args(argv)
    from playfellow_coop.gym import PlayfellowGym
    from playfellow_coop.gym.obs import PixelObserver
    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain
    from playfellow_coop.skillsmith.library import SkillLibrary
    from playfellow_coop.skillsmith.loop import improve, score_code
    from playfellow_coop.skillsmith.promote import Budget, BudgetExceeded, Selector
    from playfellow_coop.skillsmith.synth import Synthesizer

    brain = MuseBrain(DEFAULT_MODEL, os.environ["MODEL_API_KEY"], cache_key=None, effort="medium")
    brain.max_tokens = 8000
    spent = {"usd": 0.0}

    def ask(prompt: str) -> str:
        try:
            answer = brain.ask("You write small, safe Python game controllers.", prompt, [])
        except Exception as error:  # a failed call is a rejected proposal, recorded by the loop
            answer = f"<{type(error).__name__}>"
        spent["usd"] += float((brain.last_request or {}).get("cost_usd") or 0.0)
        return answer

    rows = []
    for game in [g for g in args.games.split(",") if g]:
        goal, look, spec, mapper, steps = setups()[game]
        make_env = lambda seed, g=game: PlayfellowGym(g, lambda s: ar.load_game(g, s), seed=seed)  # noqa: E731
        observer = PixelObserver(look, spec)
        library = SkillLibrary(Path(tempfile.mkdtemp(prefix=f"skills-{game}-")))
        synth = Synthesizer(ask, library, Budget(max_usd=args.max_usd, max_calls=60))
        selector = Selector()
        name, code, history = "idle", IDLE, []
        for round_no in range(args.rounds):
            validation = [10 * round_no, 10 * round_no + 1]  # new tasks every round: a validation set is used once
            try:
                result = improve(game, goal, library, synth, name, code, make_env, observer, mapper, validation_seeds=validation,
                                 test_seeds=[100, 101, 102], selector=selector, candidates=args.candidates, max_steps=steps)
            except BudgetExceeded:
                history.append({"round": round_no, "stopped": "budget"})
                break
            history.append({"round": round_no, "promoted": result.promoted, "reason": result.reason,
                            "scores": {n: round(s.mean_progress, 4) for n, s in result.scores.items()}})
            print(f"{game} round {round_no}: promoted={result.promoted} scores={history[-1]['scores']}", flush=True)
            if result.promoted:
                name = result.promoted
                code = (library.root / ".agents" / "skills" / game / f"{name}.py").read_text(encoding="utf-8") if (library.root / ".agents" / "skills" / game / f"{name}.py").exists() else code
        final = score_code(code, make_env, observer, mapper, [100, 101, 102], steps)
        idle = score_code(IDLE, make_env, observer, mapper, [100, 101, 102], steps)
        row = {"game": game, "final_skill": name, "held_out_seeds": [100, 101, 102], "held_out_progress": round(final.mean_progress, 4),
               "held_out_wins": getattr(final, "wins", None), "idle_progress": round(idle.mean_progress, 4), "rounds": history,
               "code": code if name != "idle" else None}
        rows.append(row)
        print(f"{game}: final {name} held-out progress {row['held_out_progress']} wins {row['held_out_wins']} (idle {row['idle_progress']})", flush=True)
    result = {"schema": "pf-skillsmith-live/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "model": DEFAULT_MODEL, "rounds": args.rounds, "candidates_per_round": args.candidates, "cost_usd": round(spent["usd"], 4),
              "games": rows, "honesty": "The model wrote every promoted skill; the hand-written skills were never used or shown. Held-out seeds "
              "were never used to select. Model-written skill = assisted by the model's own code, not the model choosing every key."}
    out = ROOT / "results" / "skillsmith" / f"skillsmith-live-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(f"cost ${spent['usd']:.4f}\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
