"""EvoBelief: learn the rules of a new game by running small experiments, and notice when a rule stops being true (research R3 section 6.2).

Two timescales. The FAST state is what the agent believes about this episode (where things are, what it holds) and is wiped at each episode. The SLOW store holds RULES: "when `when` holds,
`action` changes the state by `effect`", each with the evidence behind it. A rule begins as a hypothesis, is promoted to validated only after `min_support` identical observations, and every
time it is used its prediction is compared with what really happened. A mismatch is a counterexample: the rule is narrowed (its conditions are tightened by what differed) or, after
`demote_after` counterexamples, demoted, which reopens experimentation. Experiments change one thing at a time: try the action whose effect is unknown, under the same conditions, again.

State is a dict of small values. `context_features` names the features that count as the conditions of a rule (a level number, whether the player holds a key); everything else is the
effect side. The store never calls a model: a model can be asked for hypotheses, but the evidence is what promotes them.
"""
from __future__ import annotations

from dataclasses import dataclass, field

HYPOTHESIS, VALIDATED, DEMOTED = "hypothesis", "validated", "demoted"


def effect_of(before: dict, after: dict, ignore: frozenset[str] = frozenset()) -> dict:
    """What changed: {feature: (old, new)} for every feature that differs (numbers also carry their difference through the tuple)."""
    return {k: (before.get(k), after.get(k)) for k in set(before) | set(after) if k not in ignore and before.get(k) != after.get(k)}


@dataclass
class Rule:
    action: str
    when: dict
    effect: dict  # feature -> delta for numbers, or the new value for anything else
    support: int = 1
    counterexamples: int = 0
    status: str = HYPOTHESIS

    def matches(self, state: dict) -> bool:
        return all(state.get(k) == v for k, v in self.when.items())

    def specificity(self) -> int:
        return len(self.when)


def _delta(old, new):
    if isinstance(old, (int, float)) and isinstance(new, (int, float)) and not isinstance(old, bool):
        return new - old
    return new


@dataclass
class Surprise:
    kind: str  # "mismatch" (a validated rule predicted something else) or "unknown" (nothing is known about this action here)
    action: str
    predicted: dict | None
    actual: dict


class BeliefStore:
    def __init__(self, context_features: tuple[str, ...] = (), min_support: int = 2, demote_after: int = 2, ignore: tuple[str, ...] = ("t", "step")):
        self.context_features, self.min_support, self.demote_after = tuple(context_features), min_support, demote_after
        self.ignore = frozenset(ignore)
        self.fast: dict = {}
        self.rules: list[Rule] = []
        self.tried: dict[tuple, int] = {}  # (action, conditions) -> how many times it has been tried
        self.log: list[tuple[str, str]] = []  # (event, text) for the report: the evidence trail

    # ---- the fast state ------------------------------------------------------------------------------------------------------------
    def new_episode(self) -> None:
        self.fast = {}
        self.tried_this_episode: dict[tuple, int] = {}

    def conditions(self, state: dict) -> dict:
        return {k: state.get(k) for k in self.context_features}

    # ---- prediction ----------------------------------------------------------------------------------------------------------------
    def predict(self, state: dict, action: str) -> dict | None:
        """The effect the most specific matching VALIDATED rule expects, or None when nothing validated applies."""
        matching = [r for r in self.rules if r.status == VALIDATED and r.action == action and r.matches(state)]
        if not matching:
            return None
        return max(matching, key=lambda r: (r.specificity(), r.support - r.counterexamples)).effect

    # ---- learning from what happened -----------------------------------------------------------------------------------------------
    def observe(self, before: dict, action: str, after: dict) -> Surprise | None:
        diff = effect_of(before, after, self.ignore)
        actual = {k: _delta(o, n) for k, (o, n) in diff.items()}
        cond = self.conditions(before)
        key = (action, tuple(sorted(cond.items())))
        self.tried[key] = self.tried.get(key, 0) + 1
        predicted = self.predict(before, action)
        if predicted is not None:
            if predicted == actual:
                for r in self.rules:
                    if r.status == VALIDATED and r.action == action and r.matches(before) and r.effect == predicted:
                        r.support += 1
                return None
            self._contradict(before, action, predicted, actual)
            return Surprise("mismatch", action, predicted, actual)
        self._record(action, cond, actual)
        return Surprise("unknown", action, None, actual) if not self._has_validated(action, cond) else None

    def _has_validated(self, action: str, cond: dict) -> bool:
        return any(r.status == VALIDATED and r.action == action and r.matches(cond) for r in self.rules)

    def _record(self, action: str, cond: dict, actual: dict) -> None:
        for r in self.rules:
            if r.action == action and r.when == cond and r.effect == actual and r.status != DEMOTED:
                r.support += 1
                if r.status == HYPOTHESIS and r.support >= self.min_support:
                    r.status = VALIDATED
                    self.log.append(("validated", f"{action} under {cond} changes {actual} (seen {r.support} times)"))
                return
        self.rules.append(Rule(action, dict(cond), dict(actual), 1, 0, HYPOTHESIS))
        if self.min_support <= 1:
            self.rules[-1].status = VALIDATED

    def _contradict(self, before: dict, action: str, predicted: dict, actual: dict) -> None:
        for r in self.rules:
            if r.status == VALIDATED and r.action == action and r.matches(before) and r.effect == predicted:
                r.counterexamples += 1
                self.log.append(("counterexample", f"{action} was expected to change {predicted} but changed {actual}"))
                if r.counterexamples >= self.demote_after:
                    r.status = DEMOTED
                    self.log.append(("demoted", f"rule {action} -> {predicted} no longer holds"))
        # the new behaviour becomes a competing hypothesis straight away: it is promoted by repeating it, not by being asserted
        self._record(action, self.conditions(before), actual)

    # ---- experiments ---------------------------------------------------------------------------------------------------------------
    def next_experiment(self, state: dict, actions: list[str]) -> str | None:
        """The action worth trying next to learn something: one with no validated rule here (a decision-critical unknown), preferring those tried least, and re-trying a hypothesis until it
        is validated or contradicted. None when every action's effect is known here."""
        cond = self.conditions(state)
        unknown = [a for a in actions if not self._has_validated(a, cond)]
        if not unknown:
            return None
        return min(unknown, key=lambda a: (self.tried.get((a, tuple(sorted(cond.items()))), 0), a))

    def best_action(self, state: dict, actions: list[str], score: "callable") -> str | None:
        """The action whose predicted effect scores highest by `score(effect)`; only validated rules are trusted. None when none predicts anything useful (score <= 0)."""
        best, best_score = None, 0.0
        for a in actions:
            effect = self.predict(state, a)
            if effect is None:
                continue
            value = score(effect)
            if value > best_score:
                best, best_score = a, value
        return best

    def trusted(self) -> list[Rule]:
        return [r for r in self.rules if r.status == VALIDATED]
