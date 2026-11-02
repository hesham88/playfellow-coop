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
    "osg_2048": "slide the tiles, join equals, and reach the 2048 tile",
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


class ImprovingFakeModel:
    """The offline stand-in that gets better on purpose, for the learning curve: its first answer does nothing, every later answer is the fixed chasing skill. No key, no network, no cost."""

    def __init__(self):
        self.calls = 0

    def ask(self, prompt: str) -> str:
        self.calls += 1
        code = IDLE_CODE if self.calls == 1 else FAKE_CODE
        return "```python\n" + code + "```"

    def usage(self) -> dict:
        return {"calls": self.calls, "tokens_in": NOT_MEASURED, "tokens_out": NOT_MEASURED, "cost_usd": 0.0}


def _prompt_shown(prompt: str) -> dict:
    """What one skill-writing prompt showed the model: how many recorded observations and how many lessons. Parsed from the prompt itself, so the curve records what was sent, not what was meant to be sent."""
    import re

    trace_shown: object = NOT_MEASURED
    match = re.search(r"Recorded observations \(raw, in order\):\n(\[.*?\])\n\n", prompt or "", re.S)
    if match:
        try:
            trace_shown = len(json.loads(match.group(1)))
        except ValueError:
            trace_shown = NOT_MEASURED
    lessons_shown: object = NOT_MEASURED
    lessons_match = re.search(r"Lessons already learned about this game:\n(.*?)\n\nRecorded observations", prompt or "", re.S)
    if lessons_match:
        text = lessons_match.group(1).strip()
        lessons_shown = 0 if text in ("", "(none yet)") else len([line for line in text.splitlines() if line.strip()])
    return {"trace_shown": trace_shown, "lessons_shown": lessons_shown}


class _RecordingAsk:
    """Wraps the model's ask(prompt) and records every proposal's fate, so a candidate that is never scored still says why in the result file.

    An answered proposal records whether code was extracted and what the static gate said. A proposal whose call itself failed records the error
    (type and message, never a key) and returns a no-code answer, so the round still reports instead of vanishing or masquerading as an idle score.
    The per-run budget refusal is not a provider failure: it still raises, so the cap stops the search."""

    def __init__(self, ask):
        self._ask = ask
        self._fn = ask.ask if hasattr(ask, "ask") else ask
        self.records: list[dict] = []
        self.round = 0

    def __call__(self, prompt: str) -> str:
        from playfellow_coop.skillsmith import ast_gate
        from playfellow_coop.skillsmith.promote import BudgetExceeded
        from playfellow_coop.skillsmith.synth import extract_code

        shown = _prompt_shown(prompt)
        try:
            answer = self._fn(prompt)
        except BudgetExceeded:
            raise
        except Exception as error:  # noqa: BLE001 (recorded, then reported as a failed proposal; the key never appears here)
            detail = f"{type(error).__name__}: {str(error)[:200]}"
            self.records.append({"round": self.round, "outcome": "error", "extracted": False, "gate_passed": None,
                                 "detail": detail, "answer_chars": 0, **shown})
            return f"<{type(error).__name__}>"
        code = extract_code(answer) if isinstance(answer, str) else None
        if code is None:
            detail = "the answer contained no code block"
            gate_passed = None
        else:
            gate_ok, gate_why = ast_gate.check(code)
            detail, gate_passed = gate_why, bool(gate_ok)
        self.records.append({"round": self.round, "outcome": "answered", "extracted": code is not None,
                             "gate_passed": gate_passed, "detail": detail,
                             "answer_chars": len(answer) if isinstance(answer, str) else 0, **shown})
        return answer

    def usage(self) -> dict:
        if hasattr(self._ask, "usage"):
            return self._ask.usage()
        raise AttributeError("usage")


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
                              progress=_osg_progress_text() if game == "osg_2048" else progress_text(game), example=example_for(game))
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
    """Whether this game can be scored today. An unsupported game is reported, never crashed on."""
    from playfellow_coop.gym.progress import PROGRESS

    if game == "osg_2048":
        try:
            import bench.osg_progress  # noqa: F401 (the score this file brings; gym/progress.py still needs the architect's one-line hook)
        except ImportError as error:
            return False, f"bench/osg_progress.py cannot be loaded ({error}), so the web 2048 cannot be scored"
        return True, ""
    if game not in PROGRESS:
        return False, f"the gym has no progress score for {game}, so no episode can be scored or promoted"
    return True, ""


def _osg_progress_text() -> str:
    return ("progress is how far the best tile has climbed toward the 2048 tile on a doubling (log2) scale, relative to the "
            "first board; the score number alone earns nothing, and only the 2048 tile itself reaches 1.0")


def _osg_observer_mapper():
    from playfellow_coop.gym.obs import ActionMapper, ObsSpec, PixelObserver
    from playfellow_coop.skills.looks import Look

    return PixelObserver(Look("osg_2048-unfitted", {}), ObsSpec(self_role="player")), ActionMapper(keys=("left", "right", "up", "down"))


def _make_osg_env_factory():
    from bench.osg_progress import make_env

    def factory(seed: int):
        return make_env(seed)

    return factory


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
             budget_usd: float = 1.0, budget_calls: int = 10, cost_per_call_usd: float = 0.0,
             example: tuple[str, str] | None = None, rounds: int = 1) -> dict:
    """SkillSmith rounds on one game, from the library folder as it stands (pass a blank folder for a from-blank run).

    With `rounds` above 1 this is the learning curve: each round gets fresh validation seeds (a spent set is never reused to
    choose), the promoted skill becomes the next round's current skill, and `curve` gains exactly one point per round holding the
    current and best validation progress, what the first prompt of the round showed (trace and lessons), and the verdict."""
    ensure_engine()
    if int(rounds) < 1:
        raise ValueError("rounds must be at least 1")
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
    if game == "osg_2048":
        probe_keys, step_limit = ("left", "right", "up", "down"), 2000
        observer, mapper = _osg_observer_mapper()
        make_env = _make_osg_env_factory()
        probe = None
    else:
        probe = ar.load_game(game, validation_seeds[0])
        step_limit = int(probe.max_ticks)
        game_keys_probe = tuple(probe.keys)
        observer, mapper = _observer_mapper(game, game_keys_probe)
        make_env = _make_env_factory(game)
        game_keys = game_keys_probe
    if game == "osg_2048":
        game_keys = probe_keys
    library = SkillLibrary(Path(library_root))
    budget = Budget(max_usd=budget_usd, max_calls=budget_calls)
    from playfellow_coop.skillsmith.synth import example_for, progress_text

    example = example if example is not None else example_for(game)
    recorder = _RecordingAsk(ask)
    synth = Synthesizer(recorder, library, budget, cost_per_call_usd=cost_per_call_usd,
                        keys=game_keys, progress=progress_text(game) if game != "osg_2048" else _osg_progress_text(), example=example)
    selector = Selector()
    current_name, current_code = CURRENT_NAME, IDLE_CODE
    curve: list[dict] = []
    verdicts: dict = {}
    last_reason = ""
    max_steps = validation_steps or min(step_limit, 600)
    for round_index in range(int(rounds)):
        round_validation = list(validation_seeds) if round_index == 0 else [int(s) + round_index * 1000 for s in validation_seeds]
        assert_disjoint(round_validation, test_seeds)
        recorder.round = round_index
        slice_start = len(recorder.records)
        lessons_before = library.experience(game)
        result = improve(game, GOALS.get(game, "win the game"), library, synth, current_name, current_code,
                         make_env, observer, mapper, round_validation, test_seeds,
                         selector=selector, candidates=candidates, max_steps=max_steps)
        verdicts = {name: {"mean_progress": round(s.mean_progress, 4), "wins": s.wins, "episodes": s.episodes,
                           "faults": s.faults, "steps": s.steps} for name, s in result.scores.items()}
        last_reason = result.reason
        current_progress = round(float(result.scores[current_name].mean_progress), 4) if current_name in result.scores else NOT_MEASURED
        others = {n: s for n, s in result.scores.items() if n != current_name}
        best_name = max(others, key=lambda n: others[n].mean_progress) if others else None
        best_progress = round(float(others[best_name].mean_progress), 4) if best_name is not None else current_progress
        shown_records = recorder.records[slice_start:]
        first_shown = shown_records[0] if shown_records else {"trace_shown": NOT_MEASURED, "lessons_shown": len(lessons_before)}
        curve.append({"round": round_index, "validation_seeds": round_validation, "current": current_name,
                      "current_progress": current_progress, "best_candidate": best_name, "best_progress": best_progress,
                      "promoted": result.promoted, "reason": result.reason,
                      "trace_shown": first_shown.get("trace_shown", NOT_MEASURED),
                      "lessons_shown": first_shown.get("lessons_shown", len(lessons_before)),
                      "lessons": list(lessons_before), "proposals": len(shown_records)})
        if result.promoted:
            promoted_code_next = library.get(game, result.promoted)
            if promoted_code_next is not None:
                current_name, current_code = result.promoted, promoted_code_next
    usage = ask.usage() if hasattr(ask, "usage") else {"calls": budget.calls, "tokens_in": NOT_MEASURED,
                                                       "tokens_out": NOT_MEASURED, "cost_usd": round(budget.spent_usd, 5)}
    reported = usage.get("cost_usd")
    writing = {"calls": int(budget.calls), "cost_usd": round(float(reported), 5) if isinstance(reported, (int, float)) and not isinstance(reported, bool) else round(float(budget.spent_usd), 5),
               "tokens_in": usage.get("tokens_in", NOT_MEASURED), "tokens_out": usage.get("tokens_out", NOT_MEASURED)}
    promoted_final = current_name if current_name != CURRENT_NAME else None
    promoted_code = library.get(game, current_name) if promoted_final else None
    held_out: dict = {"played": False, "reason": last_reason, "wins": NOT_MEASURED, "local_step_ms": NOT_MEASURED,
                      "play_calls": 0, "play_cost_usd": 0.0}
    if promoted_final and promoted_code is not None:
        held_out = play_held_out(promoted_code, make_env, observer, mapper, test_seeds,
                                 held_out_steps or step_limit)
    return {"game": game, "supported": True, "goal": GOALS.get(game, "win the game"), "step_limit": step_limit,
            "validation_seeds": validation_seeds, "test_seeds": test_seeds, "current": CURRENT_NAME,
            "promoted": promoted_final, "selector_reason": last_reason, "gate_verdicts": verdicts,
            "curve": curve, "proposals": list(recorder.records),
            "skill_source": promoted_code, "skill_sha256": hashlib.sha256(promoted_code.encode("utf-8")).hexdigest() if promoted_code else None,
            "current_sha256": hashlib.sha256(IDLE_CODE.encode("utf-8")).hexdigest(),
            "keys": list(game_keys), "example_game": example[0],
            "example_sha256": hashlib.sha256(example[1].encode("utf-8")).hexdigest(),
            "held_out_steps": int(held_out_steps or step_limit),
            "safety_checks": safety_checks(promoted_code, promoted_final, last_reason),
            "writing": writing, "held_out": held_out,
            "sandbox": "skillsmith SandboxedSkill: static gate, separate worker on the real python.exe, osjail containment on Windows"}


def find_latest_live(root: Path | None = None) -> Path | None:
    """The newest live SkillSmith file under results/skillsmith (skillsmith-<brain>-<date>.json, never a fake wiring check), or None when no live file is there yet."""
    folder = Path(root) / "results" / "skillsmith" if root is not None else ROOT / "results" / "skillsmith"
    if not folder.is_dir():
        return None
    candidates = []
    for path in folder.glob("skillsmith-*.json"):
        if path.name.startswith("skillsmith-fake"):
            continue
        try:
            document = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        if document.get("brain") == "fake":
            continue
        candidates.append(path)
    return sorted(candidates)[-1] if candidates else None


def latest_sandbox_proof(root: Path | None = None) -> Path | None:
    folder = Path(root) / "results" / "skillsmith" if root is not None else ROOT / "results" / "skillsmith"
    if not folder.is_dir():
        return None
    files = sorted(folder.glob("sandbox-proof-*.json"))
    return files[-1] if files else None


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
        if game == "osg_2048":
            observer, mapper = _osg_observer_mapper()
            replayed = play_held_out(source, _make_osg_env_factory(), observer, mapper, list(row["test_seeds"]),
                                     int(row.get("held_out_steps") or row["step_limit"]))
        else:
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
    parser.add_argument("--replay", default=None, help="replay one saved result file for a judge ($0, no key), or 'latest' for the newest live file")
    parser.add_argument("--validation-seeds", default="0,1")
    parser.add_argument("--test-seeds", default="100,101")
    parser.add_argument("--candidates", type=int, default=1)
    parser.add_argument("--rounds", type=int, default=1, help="SkillSmith rounds per game (the learning curve has one point per round)")
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
        replay_path = find_latest_live() if str(args.replay) == "latest" else Path(args.replay)
        if replay_path is None:
            print("no live file yet: no committed live SkillSmith file under results/skillsmith/ to replay")
            return 0
        try:
            report = replay_file(replay_path)
        except ReplayRefused as refused:
            print(f"replay refused: {refused}")
            return 2
        for game, row in report["games"].items():
            if row.get("promoted"):
                print(f"{game:12} saved wins {row['saved_wins']} IQM {row['saved_progress_iqm']} | replayed wins {row['replayed_wins']} "
                      f"IQM {row['replayed_progress_iqm']} | {'matches' if row['matches'] else 'DOES NOT MATCH'}")
            else:
                print(f"{game:12} nothing was promoted in the saved run")
        proof_path = latest_sandbox_proof()
        if proof_path is not None and proof_path.is_file():
            proof = json.loads(proof_path.read_text(encoding="utf-8"))
            print(f"sandbox proof ({proof_path.name}):")
            for proof_row in proof.get("rows", []):
                state = f"stopped by {proof_row.get('layer')}" if proof_row.get("stopped") else "NOT STOPPED"
                print(f"  {proof_row.get('name'):34} {state}")
            for proof_row in proof.get("harmless", []):
                print(f"  {proof_row.get('name'):34} {'passed' if proof_row.get('passed') else 'FAILED (harmless)'}")
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
        fake_model = ImprovingFakeModel() if int(args.rounds) > 1 else FakeModel()
        results = []
        for game in games:
            results.append(run_game(game, fake_model, args.library, seeds(args.validation_seeds), seeds(args.test_seeds),
                                    candidates=args.candidates, validation_steps=args.validation_steps,
                                    held_out_steps=args.held_out_steps, budget_usd=args.budget_usd, budget_calls=args.budget_calls,
                                    rounds=int(args.rounds)))
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
                                    held_out_steps=args.held_out_steps, budget_usd=args.budget_usd, budget_calls=args.budget_calls,
                                    rounds=int(args.rounds)))
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
    print(f"wrote {out}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
