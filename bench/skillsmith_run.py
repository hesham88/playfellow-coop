"""SkillSmith end to end (ladder rung 3, model-written skills): a model writes a skill from a blank folder, the sandbox and the held-out promotion gate decide, then the promoted skill plays the held-out seeds through the gym at the game's own step limit.

  python -m bench.skillsmith_run --fake --games maze_chase --out tmp/skillsmith-fake.json --library tmp/skillsmith-lib

Offline with `--fake` no paid call is made: a stand-in model answers with one fixed skill, so a full round (propose, probe on validation seeds, promote or refuse, held-out play when promoted) can be checked for free. Live with `--brain muse|open` the existing clients are capped per run (`--budget-usd`, the call that would pass it is never sent), every paid call lands in the spend ledger, and `--dry-run` prints the planned calls and their dollar estimate while sending nothing. A judge replays a saved run with `--replay <file>` ($0, no key). The key itself is read only by the existing key loader and is never printed. Read-only inputs: `skillsmith/**`, `gym/**`, `bench/arena_run.py`.
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


class ReplayRefused(Exception):
    """A replay was refused: the saved skill is not the skill that was checked, or it no longer passes the checks."""


class CappedBrain:
    """A live brain behind the skillsmith ask(prompt) shape, with a hard per-run dollar cap and a spend ledger.

    Before every call the next call is priced at its worst case (the whole prompt in, a full answer out); when what has
    already been spent plus that price would pass the cap, the call is refused and nothing is sent. After a call the
    provider's own reported tokens and cost are what count, and one line is appended to the ledger. The key never
    passes through here: it stays inside the brain."""

    def __init__(self, brain, cap_usd: float, provider: str, run_id: str = "run", ledger_path: Path | None = None):
        self.brain, self.cap_usd, self.provider, self.run_id = brain, float(cap_usd), provider, run_id
        self.model = str(getattr(brain, "model", provider))
        self.ledger_path = Path(ledger_path) if ledger_path is not None else None
        self.calls = 0
        self.tokens_in = 0
        self.tokens_out = 0
        self.spent_usd = 0.0

    def estimate_next_usd(self, prompt: str) -> float:
        from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN
        from playfellow_coop.skillsmith.synth import estimate_tokens

        return estimate_tokens(prompt) * INPUT_USD_PER_TOKEN + int(getattr(self.brain, "max_tokens", 1000)) * OUTPUT_USD_PER_TOKEN

    def ask(self, prompt: str) -> str:
        from playfellow_coop.skillsmith.promote import BudgetExceeded

        estimate = self.estimate_next_usd(prompt)
        if self.spent_usd + estimate > self.cap_usd + 1e-12:
            raise BudgetExceeded(f"the per-run cap (${self.cap_usd:.2f}) would be passed by the next call "
                                 f"(spent ${self.spent_usd:.5f}, next call priced at up to ${estimate:.5f}); nothing was sent")
        answer = self.brain.ask("", prompt, [])
        request = getattr(self.brain, "last_request", None) or {}
        tokens_in, tokens_out = int(request.get("tokens_in") or 0), int(request.get("tokens_out") or 0)
        cost = request.get("cost_usd")
        if cost is None:
            from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN

            cost = tokens_in * INPUT_USD_PER_TOKEN + tokens_out * OUTPUT_USD_PER_TOKEN if (tokens_in or tokens_out) else estimate
        self.calls += 1
        self.tokens_in += tokens_in
        self.tokens_out += tokens_out
        self.spent_usd += float(cost)
        if self.ledger_path is not None:
            self.ledger_path.parent.mkdir(parents=True, exist_ok=True)
            left = self.cap_usd - self.spent_usd
            line = (f"| {datetime.now().astimezone().isoformat(timespec='seconds')} | {self.run_id} | {self.provider} | {self.model} "
                    f"| {tokens_in}/{tokens_out} | ${float(cost):.5f} | ${left:.5f} left of ${self.cap_usd:.2f} |\n")
            with open(self.ledger_path, "a", encoding="utf-8", newline="\n") as handle:
                handle.write(line)
        return answer

    def usage(self) -> dict:
        return {"calls": self.calls, "tokens_in": self.tokens_in, "tokens_out": self.tokens_out, "cost_usd": round(self.spent_usd, 5)}


def safety_checks(code: str | None, promoted: str | None, reason: str) -> dict:
    """The verdict of each safety layer for one promoted skill: the static gate, one sandboxed step, the held-out promotion."""
    from playfellow_coop.skillsmith import ast_gate

    checks: dict = {"static_gate": {"passed": None, "detail": "no model-written skill was promoted, so no skill reached this check"},
                    "sandbox": {"passed": None, "detail": "no model-written skill was promoted, so no skill reached this check"},
                    "held_out_promote": {"promoted": promoted, "detail": reason}}
    if code is None:
        return checks
    ok, why = ast_gate.check(code)
    checks["static_gate"] = {"passed": bool(ok), "detail": why}
    if not ok:
        return checks
    from playfellow_coop.skillsmith.sandbox import SandboxedSkill

    with SandboxedSkill(code, step_timeout_ms=2000.0) as skill:
        skill.step({"self": [0.5, 0.5], "items": [], "enemies": [], "hud": {}, "t": 0, "danger": 0.0, "escape": None})
        checks["sandbox"] = {"passed": not skill.faulted, "detail": skill.fault or "answered one step inside the sandbox",
                             "containment": skill.containment}
    return checks


def plan_run(games: list[str], brain: str = "muse", candidates: int = 1) -> dict:
    """The dry run: the planned calls per game and their dollar estimate, priced before anything is sent (a full answer out)."""
    from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN
    from playfellow_coop.skillsmith.synth import build_prompt, estimate_tokens, example_for, progress_text

    if brain == "open":
        from bench.open_weights_brain import OPEN_MAX_TOKENS

        max_out = OPEN_MAX_TOKENS
    else:
        from playfellow_coop.muse_brain import MAX_TOKENS

        max_out = MAX_TOKENS
    rows, total_calls, total_usd = {}, 0, 0.0
    for game in games:
        prompt = build_prompt(game, GOALS.get(game, "win the game"), [], [], keys=("up", "down", "left", "right"),
                              progress=progress_text(game), example=example_for(game))
        tokens_in = estimate_tokens(prompt)
        planned = int(candidates) * 2  # one proposal plus its one retry, per candidate
        usd = planned * (tokens_in * INPUT_USD_PER_TOKEN + max_out * OUTPUT_USD_PER_TOKEN)
        rows[game] = {"planned_calls": planned, "tokens_in_est_per_call": tokens_in, "tokens_out_est_per_call": max_out,
                      "estimated_usd": round(usd, 5)}
        total_calls += planned
        total_usd += usd
    return {"brain": brain, "games": rows, "planned_calls": total_calls, "estimated_usd": round(total_usd, 5),
            "note": "planned only: a full answer is priced for every call, so a real run should cost less; nothing was sent"}


def make_live_brain(brain_name: str, cap_usd: float, ledger_path: Path | None, run_id: str):
    """One live brain (the existing clients, nothing re-implemented), capped per run and backstopped by the daily cap."""
    ensure_engine()
    from playfellow_coop.budget import DailyBudget

    budget_file = (Path(ledger_path).parent / "daily-budget.json") if ledger_path is not None else ROOT / "results" / "skillsmith" / "daily-budget.json"
    daily = DailyBudget(budget_file, cap_usd=cap_usd, max_calls=10000)
    if brain_name == "muse":
        from playfellow_coop.__main__ import load_muse_key
        from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

        key = load_muse_key()
        if not key:
            raise SystemExit("MODEL_API_KEY is not set (environment or credential manager): no live call can be made")
        brain = MuseBrain(DEFAULT_MODEL, key, budget=daily)
    else:
        import os

        from bench.open_weights_brain import OpenWeightsBrain

        key = (os.environ.get("OPEN_BRAIN_API_KEY") or "").strip()
        if not key:
            raise SystemExit("OPEN_BRAIN_API_KEY is not set: no live call can be made")
        brain = OpenWeightsBrain(key, budget=daily)
    return CappedBrain(brain, cap_usd=cap_usd, provider=brain_name, run_id=run_id, ledger_path=ledger_path)


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
    game_keys = tuple(probe.keys)
    observer, mapper = _observer_mapper(game, game_keys)
    library = SkillLibrary(Path(library_root))
    budget = Budget(max_usd=budget_usd, max_calls=budget_calls)
    from playfellow_coop.skillsmith.synth import example_for, progress_text

    example = example_for(game)
    synth = Synthesizer(ask_fn, library, budget, cost_per_call_usd=cost_per_call_usd,
                        keys=game_keys, progress=progress_text(game), example=example)
    result = improve(game, GOALS.get(game, "win the game"), library, synth, CURRENT_NAME, IDLE_CODE,
                     _make_env_factory(game), observer, mapper, validation_seeds, test_seeds,
                     selector=Selector(), candidates=candidates, max_steps=validation_steps or min(step_limit, 600))
    verdicts = {name: {"mean_progress": round(s.mean_progress, 4), "wins": s.wins, "episodes": s.episodes,
                       "faults": s.faults, "steps": s.steps} for name, s in result.scores.items()}
    usage = ask.usage() if hasattr(ask, "usage") else {"calls": budget.calls, "tokens_in": NOT_MEASURED,
                                                       "tokens_out": NOT_MEASURED, "cost_usd": round(budget.spent_usd, 5)}
    reported = usage.get("cost_usd")
    writing = {"calls": int(budget.calls), "cost_usd": round(float(reported), 5) if isinstance(reported, (int, float)) and not isinstance(reported, bool) else round(float(budget.spent_usd), 5),
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
            "skill_source": promoted_code, "skill_sha256": hashlib.sha256(promoted_code.encode("utf-8")).hexdigest() if promoted_code else None,
            "current_sha256": hashlib.sha256(IDLE_CODE.encode("utf-8")).hexdigest(),
            "keys": list(game_keys), "example_game": example[0],
            "example_sha256": hashlib.sha256(example[1].encode("utf-8")).hexdigest(),
            "held_out_steps": int(held_out_steps or step_limit),
            "safety_checks": safety_checks(promoted_code, result.promoted, result.reason),
            "writing": writing, "held_out": held_out,
            "sandbox": "skillsmith SandboxedSkill: static gate, separate worker on the real python.exe, osjail containment on Windows"}


def replay_file(path: Path) -> dict:
    """Replay one saved run for a judge: $0, no key. The saved source must hash to the saved fingerprint, pass the same
    static gate and sandbox, and reproduce the saved held-out numbers on the saved seeds, or the replay fails."""
    ensure_engine()
    document = json.loads(Path(path).read_text(encoding="utf-8"))
    games: dict = {}
    ok = True
    for game, row in (document.get("games") or {}).items():
        if not row.get("supported") or not row.get("promoted"):
            games[game] = {"promoted": None, "matches": not (row.get("held_out") or {}).get("played", False)}
            ok = ok and games[game]["matches"]
            continue
        source = row.get("skill_source")
        if not source:
            raise ReplayRefused(f"{game}: the file carries no skill source, so there is nothing to replay")
        if hashlib.sha256(source.encode("utf-8")).hexdigest() != row.get("skill_sha256"):
            raise ReplayRefused(f"{game}: the saved source does not match its saved fingerprint; the file was changed after the run")
        checks = safety_checks(source, row["promoted"], row.get("selector_reason", ""))
        if checks["static_gate"]["passed"] is not True:
            raise ReplayRefused(f"{game}: the saved source fails the static gate: {checks['static_gate']['detail']}")
        if checks["sandbox"]["passed"] is not True:
            raise ReplayRefused(f"{game}: the saved source fails in the sandbox: {checks['sandbox']['detail']}")
        from bench import arena_run as ar

        probe = ar.load_game(game, row["test_seeds"][0])
        observer, mapper = _observer_mapper(game, tuple(probe.keys))
        replayed = play_held_out(source, _make_env_factory(game), observer, mapper, list(row["test_seeds"]),
                                 int(row.get("held_out_steps") or row["step_limit"]))
        saved = row["held_out"]
        matches = (replayed["wins"] == saved["wins"] and len(replayed["episodes"]) == len(saved["episodes"])
                   and all(a["won"] == b["won"] and abs(a["progress"] - b["progress"]) < 0.001
                           for a, b in zip(replayed["episodes"], saved["episodes"])))
        games[game] = {"promoted": row["promoted"], "saved_wins": saved["wins"], "replayed_wins": replayed["wins"],
                       "saved_progress_iqm": saved.get("progress_iqm"), "replayed_progress_iqm": replayed["progress_iqm"],
                       "matches": bool(matches)}
        ok = ok and bool(matches)
    return {"ok": ok, "refused": None, "games": games}


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
    parser.add_argument("--brain", choices=("muse", "open"), default=None, help="a live brain through the existing clients (the run that owns the key)")
    parser.add_argument("--dry-run", action="store_true", help="print the planned calls and their dollar estimate, and send nothing")
    parser.add_argument("--replay", type=Path, default=None, help="replay one saved result file for a judge ($0, no key)")
    parser.add_argument("--validation-seeds", default="0,1")
    parser.add_argument("--test-seeds", default="100,101")
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--validation-steps", type=int, default=None)
    parser.add_argument("--held-out-steps", type=int, default=None)
    parser.add_argument("--budget-usd", type=float, default=1.0, help="the hard per-run cap: the call that would pass it is never sent")
    parser.add_argument("--budget-calls", type=int, default=10)
    parser.add_argument("--ledger", type=Path, default=None, help="the spend ledger file: one line per paid call (live brains only)")
    parser.add_argument("--run-id", default=None)
    parser.add_argument("--library", type=Path, default=None, help="the skill library folder (use a blank folder for a from-blank run)")
    parser.add_argument("--out", type=Path, default=None)
    args = parser.parse_args(argv)
    games = [g.strip() for g in args.games.split(",") if g.strip()]
    if args.replay is not None:
        try:
            report = replay_file(args.replay)
        except ReplayRefused as refused:
            print(f"replay refused: {refused}")
            return 2
        for game, row in report["games"].items():
            if row.get("promoted"):
                print(f"{game:12} saved wins {row['saved_wins']} IQM {row['saved_progress_iqm']} | replayed wins {row['replayed_wins']} "
                      f"IQM {row['replayed_progress_iqm']} | {'matches' if row['matches'] else 'DOES NOT MATCH'}")
            else:
                print(f"{game:12} nothing was promoted in the saved run")
        return 0 if report["ok"] else 1
    if args.dry_run:
        if not args.brain:
            raise SystemExit("--dry-run needs --brain muse or --brain open, so the estimate prices the right model")
        plan = plan_run(games, brain=args.brain, candidates=args.candidates)
        for game, row in plan["games"].items():
            print(f"{game:12} planned calls {row['planned_calls']} (about {row['tokens_in_est_per_call']} tokens in, "
                  f"up to {row['tokens_out_est_per_call']} out each) ${row['estimated_usd']:.5f}")
        print(f"total: {plan['planned_calls']} planned calls, ${plan['estimated_usd']:.5f} estimated; nothing was sent")
        return 0
    if bool(args.fake) == bool(args.brain):
        raise SystemExit("choose exactly one of --fake (offline, no call) or --brain muse|open (live, capped)")
    if args.library is None:
        raise SystemExit("--library is required for a run (use a blank folder for a from-blank run)")
    seeds = lambda text: [int(s) for s in text.split(",") if s.strip()]  # noqa: E731
    if args.fake:
        out = args.out
        if out is not None and (ROOT / "results") in Path(out).resolve().parents:
            raise SystemExit("a --fake run is a wiring check, not a model result: it never writes under results/")
        if out is None:
            raise SystemExit("--out is required for a --fake run (outside results/)")
        results = []
        for game in games:
            results.append(run_game(game, FakeModel(), args.library, seeds(args.validation_seeds), seeds(args.test_seeds),
                                    candidates=args.candidates, validation_steps=args.validation_steps,
                                    held_out_steps=args.held_out_steps, budget_usd=args.budget_usd, budget_calls=args.budget_calls))
        document = build_document(results, "fake", "fake-stand-in (not a model result)")
    else:
        date = datetime.now().strftime("%Y%m%d")
        run_id = args.run_id or f"skillsmith-{args.brain}-{date}"
        ledger = args.ledger if args.ledger is not None else ROOT / "results" / "skillsmith" / "spend-ledger.md"
        out = args.out if args.out is not None else ROOT / "results" / "skillsmith" / f"skillsmith-{args.brain}-{date}.json"
        capped = make_live_brain(args.brain, cap_usd=args.budget_usd, ledger_path=ledger, run_id=run_id)
        results = []
        for game in games:
            results.append(run_game(game, capped, args.library, seeds(args.validation_seeds), seeds(args.test_seeds),
                                    candidates=args.candidates, validation_steps=args.validation_steps,
                                    held_out_steps=args.held_out_steps, budget_usd=args.budget_usd, budget_calls=args.budget_calls))
        document = build_document(results, args.brain, capped.model)
        document["run_id"] = run_id
        document["cap_usd"] = args.budget_usd
        document["spend_ledger"] = ledger.name
    out.parent.mkdir(parents=True, exist_ok=True)
    with open(out, "x", encoding="utf-8", newline="\n") as handle:
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
