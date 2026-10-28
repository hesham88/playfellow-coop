"""Propose, Probe, Compose: the self-improvement loop (Harness² and TORSI, research R2 section 1.2 and 4.1, R5), run offline between matches.

  Propose  one or more candidate controllers from a model (through `Synthesizer`; the model sees the raw structured trace of how the current one behaved).
  Probe    each candidate plays the SAME validation seeds in the gym through the sandbox, the same way the current skill does, so the comparison is matched.
  Compose  `Selector` promotes a candidate only if its validation score strictly beats the current skill's; the held-out test seeds are never touched; every decision, kept or not, is written to
           EXPERIENCE.md with the numbers behind it; and the whole thing stops at a hard spend cap.

`Rollout` is what a policy needs to run in an environment: it turns a picture into the structured observation, asks the policy for an action, maps it to a key and steps the gym. A policy is
either a sandboxed model-written skill or any callable (the hand-written skill, a random policy as the floor).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable

from playfellow_coop.gym.env import PlayfellowGym
from playfellow_coop.gym.obs import ActionMapper, PixelObserver
from playfellow_coop.skillsmith.library import SkillLibrary
from playfellow_coop.skillsmith.promote import Budget, BudgetExceeded, Selector
from playfellow_coop.skillsmith.sandbox import NEUTRAL, SandboxedSkill
from playfellow_coop.skillsmith.synth import Synthesizer


@dataclass
class Score:
    mean_progress: float
    wins: int
    episodes: int
    faults: int = 0
    steps: int = 0


def rollout_code(code: str, make_env: Callable[[int], PlayfellowGym], observer: PixelObserver, mapper: ActionMapper, seed: int, max_steps: int, step_timeout_ms: float = 200.0) -> tuple[float, bool, bool, list[dict]]:
    """Play one episode with a model-written skill inside the sandbox. Returns (progress, won, faulted, trace of the observations it saw)."""
    env = make_env(seed)
    frame, _ = env.reset(seed)
    observer.reset()
    trace: list[dict] = []
    faulted = False
    with SandboxedSkill(code, step_timeout_ms=step_timeout_ms) as skill:
        for _ in range(max_steps):
            obs = observer.build(frame)
            if len(trace) < 400:
                trace.append(obs)
            action = skill.step(obs)
            if skill.faulted:
                faulted = True
            key = mapper.key_for(action) if not skill.faulted else None
            frame, _, terminated, truncated, _ = env.step(key)
            if terminated or truncated:
                break
    card = env.card()
    return card.progress, card.won, faulted, trace


def score_code(code: str, make_env, observer, mapper, seeds, max_steps: int) -> Score:
    progress, wins, faults, steps = [], 0, 0, 0
    for seed in seeds:
        p, won, faulted, trace = rollout_code(code, make_env, observer, mapper, seed, max_steps)
        progress.append(p)
        wins += int(won)
        faults += int(faulted)
        steps += len(trace)
    return Score(sum(progress) / max(1, len(progress)), wins, len(progress), faults, steps)


@dataclass
class RoundResult:
    promoted: str | None
    scores: dict[str, Score] = field(default_factory=dict)
    reason: str = ""
    spent_usd: float = 0.0


def improve(game: str, goal: str, library: SkillLibrary, synth: Synthesizer, current_name: str, current_code: str, make_env, observer: PixelObserver, mapper: ActionMapper,
            validation_seeds, test_seeds, selector: Selector, candidates: int = 2, max_steps: int = 600) -> RoundResult:
    """One round. Proposes up to `candidates` skills, probes them and the current one on the validation seeds, and promotes at most one. The held-out `test_seeds` are only checked for
    overlap, never played. Raises BudgetExceeded when the search budget runs out (the library is left as it was)."""
    baseline = score_code(current_code, make_env, observer, mapper, validation_seeds, max_steps)
    # the current skill's own recorded behaviour is the trace the model reads
    _, _, _, trace = rollout_code(current_code, make_env, observer, mapper, list(validation_seeds)[0], max_steps)
    scores: dict[str, Score] = {current_name: baseline}
    codes: dict[str, str] = {}
    result = RoundResult(None, scores)
    for index in range(candidates):
        try:
            attempt = synth.propose(game, goal, trace)
        except BudgetExceeded:
            result.reason = "the search budget ran out"
            break
        if attempt.code is None:
            library.note(game, "a proposal was rejected by the static gate", "; ".join(attempt.reasons)[:200])
            continue
        name = f"cand{index + 1}_{abs(hash(attempt.code)) % 10_000:04d}"
        codes[name] = attempt.code
        scores[name] = score_code(attempt.code, make_env, observer, mapper, validation_seeds, max_steps)
    decision = selector.choose(current_name, {n: s.mean_progress for n, s in scores.items()}, validation_seeds, test_seeds)
    result.reason = decision.reason
    if decision.promote and decision.chosen in codes:
        chosen = decision.chosen
        receipt = library.add(game, chosen, codes[chosen])
        library.note(game, f"promoted {chosen} over {current_name}", f"validation progress {scores[chosen].mean_progress:.3f} vs {baseline.mean_progress:.3f}; sha {receipt.sha256[:12]}")
        result.promoted = chosen
    else:
        library.note(game, f"kept {current_name}", f"{decision.reason}; scores " + ", ".join(f"{n} {s.mean_progress:.3f}" for n, s in scores.items()))
    result.spent_usd = synth.budget.spent_usd
    return result


__all__ = ["Budget", "NEUTRAL", "RoundResult", "Score", "improve", "rollout_code", "score_code"]
