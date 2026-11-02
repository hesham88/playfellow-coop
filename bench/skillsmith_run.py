"""SkillSmith end to end (ladder rung 3, model-written skills): a model writes a skill from a blank folder, the sandbox and the held-out promotion gate decide, then the promoted skill plays the held-out seeds through the gym at the game's own step limit.

  python -m bench.skillsmith_run --fake --games maze_chase --out tmp/skillsmith-fake.json --library tmp/skillsmith-lib

Offline with `--fake` no paid call is made: a stand-in model answers with one fixed skill, so a full round (propose, probe on validation seeds, promote or refuse, held-out play when promoted) can be checked for free. The live ask is wired by the run that owns the key; this file never reads a key. Read-only inputs: `skillsmith/**`, `gym/**`, `bench/arena_run.py`.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "pf-arena-run/1"
LABEL = "[Assisted: Model-Written Skill]"
CURRENT_NAME = "idle"
NOT_MEASURED = "not measured"

IDLE_CODE = """class GeneratedArenaSkill:
    def compute_action(self, obs):
        return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
"""

FAKE_CODE = """import math

class GeneratedArenaSkill:
    def __init__(self):
        self.t = 0

    def compute_action(self, obs):
        self.t += 1
        if obs.get("danger", 0) >= 0.5 and obs.get("escape"):
            ex, ey = obs["escape"]
            return {"move": [max(-1.0, min(1.0, ex)), max(-1.0, min(1.0, ey))], "buttons": [], "hold_ms": 0}
        items = obs.get("items") or []
        if items:
            sx, sy = obs["self"]
            ix, iy = items[0][0], items[0][1]
            dx, dy = ix - sx, iy - sy
            n = math.hypot(dx, dy) or 1.0
            return {"move": [dx / n, dy / n], "buttons": [], "hold_ms": 0}
        dirs = [[1.0, 0.0], [0.0, 1.0], [-1.0, 0.0], [0.0, -1.0]]
        return {"move": dirs[(self.t // 20) % 4], "buttons": [], "hold_ms": 0}
"""

GOALS = {
    "maze_chase": "collect the coins, take the key and reach the door",
    "key_caves": "cross the rooms, take the key and open the door",
    "action_quest": "defeat the boss",
}
DEFAULT_GAMES = ("maze_chase", "key_caves", "action_quest")


def engine_dir() -> Path:
    import os

    named = os.environ.get("PLAYFELLOW_ENGINE")
    return Path(named) if named else ROOT.parent / "playfellow" / "software"


def ensure_engine() -> None:
    folder = engine_dir()
    if folder.is_dir() and str(folder) not in sys.path:
        sys.path.insert(0, str(folder))


class FakeModel:
    """The offline stand-in model: always answers with the same fixed skill. No key, no network, no cost."""

    def __init__(self, code: str = FAKE_CODE):
        self.code = code
        self.calls = 0

    def ask(self, prompt: str) -> str:
        self.calls += 1
        return "```python\n" + self.code + "```"

    def usage(self) -> dict:
        return {"calls": self.calls, "tokens_in": NOT_MEASURED, "tokens_out": NOT_MEASURED, "cost_usd": 0.0}


def game_support(game: str) -> tuple[bool, str]:
    """Whether the gym can score this game today. An unsupported game is reported, never crashed on."""
    from playfellow_coop.gym.progress import PROGRESS

    if game == "osg_2048":
        if not (ROOT / "bench" / "osg_2048.py").is_file():
            return False, "bench/osg_2048.py is not in this repo yet, so the web path cannot be driven"
        if game not in PROGRESS:
            return False, "the gym has no progress score for osg_2048"
    if game not in PROGRESS:
        return False, f"the gym has no progress score for {game}, so no episode can be scored or promoted"
    return True, ""


def _observer_mapper(game: str, keys: tuple[str, ...]):
    """Pixels to the skill's observation for one game. Colours come from the engine's own constants; a game whose colours cannot be read gets an unfitted look (the skill then sees no things, which the result states)."""
    from playfellow_coop.gym.obs import ActionMapper, ObsSpec, PixelObserver
    from playfellow_coop.skills.looks import Look, exact_look

    look: Look = Look(f"{game}-unfitted", {})
    spec = ObsSpec(self_role="player")
    try:
        if game == "maze_chase":
            import arena_pack.maze_chase as pack

            look = exact_look("arena", {"player": tuple(pack.PLAYER_COLOR), "coin": tuple(pack.COIN_COLOR),
                                        "key": tuple(pack.KEY_COLOR), "chaser": tuple(pack.CHASER_COLOR)}, radius=36.0)
            spec = ObsSpec(self_role="player", item_roles=("coin", "key"), enemy_roles=("chaser",), top=32)
        elif game == "key_caves":
            import arena_pack.key_caves as pack

            look = exact_look("arena", {"player": tuple(pack.PLAYER), "key": tuple(pack.KEY)}, radius=36.0)
            spec = ObsSpec(self_role="player", item_roles=("key",), top=32)
    except Exception:  # noqa: BLE001 (an unreadable look is a stated limit of the run, not a crash)
        look = Look(f"{game}-unfitted", {})
    buttons = {name: key for name, key in (("jump", "space"), ("fire", "z"), ("attack", "z")) if key in keys}
    return PixelObserver(look, spec), ActionMapper(keys=tuple(keys), buttons=buttons)


def _make_env_factory(game: str):
    from bench import arena_run as ar
    from playfellow_coop.gym import PlayfellowGym

    def make_env(seed: int) -> PlayfellowGym:
        return PlayfellowGym(game, lambda s: ar.load_game(game, s), seed=seed)

    return make_env


def play_held_out(code: str, make_env, observer, mapper, seeds, max_steps: int) -> dict:
    """Play one written skill on held-out seeds through the gym. Every step is local: no model call, and the sandbox's own step times are the speed evidence."""
    import statistics

    from playfellow_coop.skillsmith.sandbox import SandboxedSkill

    episodes, latencies = [], []
    for seed in seeds:
        env = make_env(seed)
        frame, _ = env.reset(seed)
        observer.reset()
        faulted = False
        with SandboxedSkill(code, step_timeout_ms=200.0) as skill:
            for _ in range(max_steps):
                action = skill.step(observer.build(frame))
                if skill.faulted:
                    faulted = True
                key = mapper.key_for(action) if not skill.faulted else None
                frame, _, terminated, truncated, _ = env.step(key)
                if terminated or truncated:
                    break
            latencies.extend(skill.latencies_ms)
        card = env.card()
        episodes.append({"seed": int(seed), "won": bool(card.won), "progress": round(float(card.progress), 4),
                         "steps": int(card.steps), "faulted": faulted})
    from bench.arena_run import wilson
    from playfellow_coop.evalkit.stats import iqm, stratified_bootstrap

    wins = sum(1 for e in episodes if e["won"])
    lo, hi = wilson(wins, len(episodes))
    progresses = [e["progress"] for e in episodes]
    point = float(iqm(progresses)) if progresses else 0.0
    _, ci_lo, ci_hi = stratified_bootstrap({"held_out": progresses}, reps=200, seed=0) if progresses else (0.0, 0.0, 0.0)
    step_ms = ({"n": len(latencies), "p50_ms": round(statistics.median(latencies), 3),
                "mean_ms": round(statistics.fmean(latencies), 3)} if latencies else NOT_MEASURED)
    return {"played": True, "episodes": episodes, "wins": wins, "win_rate": round(wins / len(episodes), 3) if episodes else None,
            "wilson95": [round(lo, 3), round(hi, 3)], "progress_iqm": round(point, 4),
            "progress_iqm_95": [round(float(ci_lo), 4), round(float(ci_hi), 4)], "local_step_ms": step_ms,
            "play_calls": 0, "play_cost_usd": 0.0}


def run_game(game: str, ask, library_root: Path, validation_seeds, test_seeds, candidates: int = 1,
             validation_steps: int | None = None, held_out_steps: int | None = None,
             budget_usd: float = 1.0, budget_calls: int = 10, cost_per_call_usd: float = 0.0) -> dict:
    """One full SkillSmith round on one game, from the library folder as it stands (pass a blank folder for a from-blank run)."""
    ensure_engine()
    supported, reason = game_support(game)
    if not supported:
        return {"game": game, "supported": False, "reason": reason, "promoted": None}
    from bench import arena_run as ar
    from playfellow_coop.skillsmith.library import SkillLibrary
    from playfellow_coop.skillsmith.loop import improve
    from playfellow_coop.skillsmith.promote import Budget, Selector, assert_disjoint
    from playfellow_coop.skillsmith.synth import Synthesizer

    validation_seeds, test_seeds = list(validation_seeds), list(test_seeds)
    assert_disjoint(validation_seeds, test_seeds)  # the held-out split is checked before anything plays
    ask_fn = ask.ask if hasattr(ask, "ask") else ask
    probe = ar.load_game(game, validation_seeds[0])
    step_limit = int(probe.max_ticks)
    observer, mapper = _observer_mapper(game, tuple(probe.keys))
    library = SkillLibrary(Path(library_root))
    budget = Budget(max_usd=budget_usd, max_calls=budget_calls)
    synth = Synthesizer(ask_fn, library, budget, cost_per_call_usd=cost_per_call_usd)
    result = improve(game, GOALS.get(game, "win the game"), library, synth, CURRENT_NAME, IDLE_CODE,
                     _make_env_factory(game), observer, mapper, validation_seeds, test_seeds,
                     selector=Selector(), candidates=candidates, max_steps=validation_steps or min(step_limit, 600))
    verdicts = {name: {"mean_progress": round(s.mean_progress, 4), "wins": s.wins, "episodes": s.episodes,
                       "faults": s.faults, "steps": s.steps} for name, s in result.scores.items()}
    usage = ask.usage() if hasattr(ask, "usage") else {"calls": budget.calls, "tokens_in": NOT_MEASURED,
                                                       "tokens_out": NOT_MEASURED, "cost_usd": round(budget.spent_usd, 5)}
    writing = {"calls": int(budget.calls), "cost_usd": round(float(budget.spent_usd), 5),
               "tokens_in": usage.get("tokens_in", NOT_MEASURED), "tokens_out": usage.get("tokens_out", NOT_MEASURED)}
    promoted_code = library.get(game, result.promoted) if result.promoted else None
    held_out: dict = {"played": False, "reason": result.reason, "wins": NOT_MEASURED, "local_step_ms": NOT_MEASURED,
                      "play_calls": 0, "play_cost_usd": 0.0}
    if result.promoted and promoted_code is not None:
        held_out = play_held_out(promoted_code, _make_env_factory(game), observer, mapper, test_seeds,
                                 held_out_steps or step_limit)
    return {"game": game, "supported": True, "goal": GOALS.get(game, "win the game"), "step_limit": step_limit,
            "validation_seeds": validation_seeds, "test_seeds": test_seeds, "current": CURRENT_NAME,
            "promoted": result.promoted, "selector_reason": result.reason, "gate_verdicts": verdicts,
            "skill_sha256": hashlib.sha256(promoted_code.encode("utf-8")).hexdigest() if promoted_code else None,
            "current_sha256": hashlib.sha256(IDLE_CODE.encode("utf-8")).hexdigest(),
            "writing": writing, "held_out": held_out,
            "sandbox": "skillsmith SandboxedSkill: static gate, separate worker on the real python.exe, osjail containment on Windows"}


def build_document(game_results: list[dict], brain: str, model: str) -> dict:
    from playfellow_coop.evalkit.ladder import BY_KEY

    rung = BY_KEY["model_skills"]
    played = [g["held_out"] for g in game_results if g.get("supported") and g["held_out"].get("played")]
    episodes = [e for h in played for e in h["episodes"]]
    return {"schema": SCHEMA, "written": datetime.now().astimezone().isoformat(timespec="seconds"),
            "condition": f"skillsmith-{brain}", "brain": brain, "model": model,
            "rung": {"key": rung.key, "number": rung.number, "title": rung.title},
            "label": LABEL,
            "note": "Writing cost is the model's; play after promotion is local (0 calls, $0). A refused candidate plays no held-out seed. Fake-brain files are wiring checks, not model results.",
            "games": {g["game"]: g for g in game_results},
            "held_out_overall": {"episodes": len(episodes), "wins": sum(1 for e in episodes if e["won"])} if episodes else
            {"episodes": 0, "wins": NOT_MEASURED}}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--games", default=",".join(DEFAULT_GAMES))
    parser.add_argument("--fake", action="store_true", help="offline stand-in model (no key, no network, no paid call)")
    parser.add_argument("--validation-seeds", default="0,1")
    parser.add_argument("--test-seeds", default="100,101")
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--validation-steps", type=int, default=None)
    parser.add_argument("--held-out-steps", type=int, default=None)
    parser.add_argument("--budget-usd", type=float, default=1.0)
    parser.add_argument("--budget-calls", type=int, default=10)
    parser.add_argument("--library", type=Path, required=True, help="the skill library folder (use a blank folder for a from-blank run)")
    parser.add_argument("--out", type=Path, required=True)
    args = parser.parse_args(argv)
    if not args.fake:
        raise SystemExit("only --fake runs here: the live ask is wired by the run that owns the key, and no paid call is made from this harness")
    seeds = lambda text: [int(s) for s in text.split(",") if s.strip()]  # noqa: E731
    games = [g.strip() for g in args.games.split(",") if g.strip()]
    results = []
    for game in games:
        fake = FakeModel()
        results.append(run_game(game, fake, args.library, seeds(args.validation_seeds), seeds(args.test_seeds),
                                candidates=args.candidates, validation_steps=args.validation_steps,
                                held_out_steps=args.held_out_steps, budget_usd=args.budget_usd, budget_calls=args.budget_calls))
    document = build_document(results, "fake", "fake-stand-in (not a model result)")
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, indent=1)
    for game in games:
        result = document["games"][game]
        if not result["supported"]:
            print(f"{game:12} unsupported: {result['reason']}")
        elif result["promoted"]:
            held = result["held_out"]
            print(f"{game:12} promoted {result['promoted']}: held-out wins {held['wins']}/{len(held['episodes'])} IQM {held['progress_iqm']} step {held['local_step_ms']}")
        else:
            print(f"{game:12} refused: {result['selector_reason']}")
    print(f"wrote {args.out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
