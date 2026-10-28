"""Tycho: a model-written program as a world model, checked against reality, used to look ahead, repaired when wrong (research R3 section 6.3).

A small class `GeneratedWorldModel` with `init_state(obs)`, `transition(state, action)` and `render(state)` is written by a model from the interaction log and run in the isolated worker (it
is model-written code, so it gets exactly the same two layers of safety as a skill). `check` replays recorded (observation, action, next observation) triples through it: how often it
predicts the next observation right, and how often it abstains (`render` may answer None for what it cannot determine; abstaining is honest, guessing is not). `lookahead` searches action
sequences inside the model, in memory, before anything irreversible is done in the real game. The `Orchestrator` is the metareasoning policy: act directly, build a model, plan with it, or
repair it, so the expensive steps are only taken when they pay.
"""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from playfellow_coop.skillsmith.sandbox import SandboxedProgram

CLASS = "GeneratedWorldModel"
METHODS = ("init_state", "transition", "render")


class WorldModel:
    """A sandboxed program with the three functions. Use as a context manager so the worker is always stopped."""

    def __init__(self, code: str, step_timeout_ms: float = 200.0):
        self.program = SandboxedProgram(code, CLASS, METHODS, step_timeout_ms=step_timeout_ms)

    @property
    def faulted(self) -> bool:
        return self.program.faulted

    def init_state(self, obs):
        return self.program.call("init_state", obs)

    def transition(self, state, action):
        return self.program.call("transition", state, action)

    def render(self, state):
        return self.program.call("render", state)

    def close(self) -> None:
        self.program.close()

    def __enter__(self) -> "WorldModel":
        return self

    def __exit__(self, *exc) -> None:
        self.program.__exit__(*exc)


@dataclass
class Fit:
    accuracy: float  # of the predictions it made, the share that were right
    coverage: float  # the share of steps it dared to predict (the rest it abstained on)
    checked: int
    first_error: int | None = None  # index of the first wrong prediction (what a repair prompt should show)


def check(model: WorldModel, log: list[tuple[dict, str, dict]]) -> Fit:
    """Replay (obs, action, next_obs) triples: the model's prediction of the next observation against the real one. A fault counts as every remaining step wrong."""
    right = wrong = abstained = 0
    first = None
    for i, (obs, action, nxt) in enumerate(log):
        state = model.init_state(obs)
        state = model.transition(state, action) if state is not None else None
        predicted = model.render(state) if state is not None else None
        if model.faulted:
            wrong += len(log) - i
            first = i if first is None else first
            break
        if predicted is None:
            abstained += 1
        elif predicted == nxt:
            right += 1
        else:
            wrong += 1
            first = i if first is None else first
    made = right + wrong
    return Fit(right / made if made else 0.0, made / len(log) if log else 0.0, len(log), first)


def lookahead(model: WorldModel, obs: dict, actions: list[str], reached: Callable[[dict], bool], depth: int = 6, max_nodes: int = 400) -> list[str] | None:
    """Breadth-first search inside the model for the shortest action sequence whose predicted observation satisfies `reached`. None when none is found within the depth and node limits,
    or when the model abstains or faults along the way. Nothing here touches the real game."""
    start = model.init_state(obs)
    if start is None:
        return None
    queue = deque([(start, [])])
    seen = {repr(start)}
    nodes = 0
    while queue and nodes < max_nodes:
        state, path = queue.popleft()
        if len(path) >= depth:
            continue
        for a in actions:
            nxt = model.transition(state, a)
            nodes += 1
            if nxt is None or model.faulted:
                return None
            seen_key = repr(nxt)
            predicted = model.render(nxt)
            if predicted is not None and reached(predicted):
                return path + [a]
            if seen_key not in seen:
                seen.add(seen_key)
                queue.append((nxt, path + [a]))
    return None


ACT, BUILD, PLAN, REPAIR = "act_directly", "build_model", "plan_with_model", "repair_model"


@dataclass
class Orchestrator:
    """When is a world model worth its cost? Build one only after enough experience and while budget remains; plan with it only when it has earned trust; repair it when its predictions
    start failing; otherwise just act."""
    min_log: int = 12
    trust: float = 0.9
    min_coverage: float = 0.5
    max_repairs: int = 3
    build_cost_usd: float = 0.05
    repairs: int = 0
    spent_usd: float = 0.0
    budget_usd: float = 0.25

    def decide(self, log_size: int, fit: Fit | None, recent_mismatches: int = 0) -> str:
        affordable = self.spent_usd + self.build_cost_usd <= self.budget_usd
        if fit is None:
            return BUILD if log_size >= self.min_log and affordable else ACT
        if fit.accuracy >= self.trust and fit.coverage >= self.min_coverage and recent_mismatches == 0:
            return PLAN
        if self.repairs < self.max_repairs and affordable and log_size >= self.min_log:
            return REPAIR
        return ACT

    def charge(self, decision: str) -> None:
        if decision in (BUILD, REPAIR):
            self.spent_usd += self.build_cost_usd
            if decision == REPAIR:
                self.repairs += 1
