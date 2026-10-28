"""Learning the rules of an unseen game: beliefs that are tested and revised, a model-written world model that is checked and used for lookahead, and short summaries of earlier episodes."""
from __future__ import annotations

import pytest

from playfellow_coop.agent.beliefs import DEMOTED, HYPOTHESIS, VALIDATED, BeliefStore, effect_of
from playfellow_coop.agent.context import ContextWindow, EpisodeSummary, tokens
from playfellow_coop.agent.worldmodel import ACT, BUILD, PLAN, REPAIR, Fit, Orchestrator, WorldModel, check, lookahead


# ---- beliefs ------------------------------------------------------------------------------------------------------------------------
class KeyWorld:
    """A line. Key a moves left and key b right, until the game SILENTLY swaps them at `swap_at` (nobody says so)."""

    def __init__(self, swap_at=40):
        self.pos, self.t, self.swap_at = 0, 0, swap_at

    def state(self):
        return {"pos": self.pos, "t": self.t}

    def step(self, action):
        swapped = self.t >= self.swap_at
        move = {"a": -1, "b": 1}[action] * (-1 if swapped else 1)
        self.pos += move
        self.t += 1
        return self.state()


def play(store, steps=160, swap_at=40):
    env = KeyWorld(swap_at)
    state = env.state()
    goal, reached_after_swap, reached = 5, 0, 0
    store.new_episode()
    for _ in range(steps):
        actions = ["a", "b"]
        act = store.next_experiment(state, actions)
        if act is None:
            direction = 1 if goal > state["pos"] else -1
            act = store.best_action(state, actions, lambda effect, d=direction: effect.get("pos", 0) * d) or "a"
        after = env.step(act)
        store.observe(state, act, after)
        state = after
        if state["pos"] == goal:
            reached += 1
            reached_after_swap += int(state["t"] > swap_at)
            goal = -goal  # the next goal is on the other side
    return reached, reached_after_swap


def test_a_rule_is_only_trusted_after_repeated_evidence_and_its_effect_is_recorded_as_a_delta():
    store = BeliefStore(min_support=2)
    before, after = {"pos": 0, "t": 0}, {"pos": 1, "t": 1}
    surprise = store.observe(before, "b", after)
    assert surprise.kind == "unknown" and store.rules[0].status == HYPOTHESIS and store.predict(before, "b") is None
    store.observe({"pos": 3, "t": 2}, "b", {"pos": 4, "t": 3})
    assert store.rules[0].status == VALIDATED and store.predict({"pos": 9}, "b") == {"pos": 1} and ("validated", "b under {} changes {'pos': 1} (seen 2 times)") in store.log
    assert effect_of({"a": 1, "t": 1}, {"a": 2, "t": 2}, frozenset({"t"})) == {"a": (1, 2)}


def test_a_silent_change_of_the_rules_is_noticed_demoted_and_relearned_while_a_rule_that_never_revises_keeps_failing():
    smart = BeliefStore(min_support=2, demote_after=2)
    class NeverRevises(BeliefStore):
        def _contradict(self, before, action, predicted, actual):  # a rule learned once is believed for ever: contradictions are simply not recorded
            return None

    naive = NeverRevises(min_support=2)
    smart_total, smart_after = play(smart)
    naive_total, naive_after = play(naive)
    assert smart_after >= 4 and naive_after <= 1 and smart_total > naive_total
    kinds = [event for event, _ in smart.log]
    assert "counterexample" in kinds and "demoted" in kinds and kinds.count("validated") >= 4  # two rules learned, the swap noticed, two rules learned again
    assert any(r.status == DEMOTED for r in smart.rules) and len(smart.trusted()) == 2


def test_experiments_target_actions_with_no_validated_rule_least_tried_first_and_stop_when_everything_is_known():
    store = BeliefStore(context_features=("mode",), min_support=1)
    state = {"pos": 0, "mode": "day"}
    assert store.next_experiment(state, ["a", "b"]) == "a"
    store.observe(state, "a", {"pos": -1, "mode": "day"})
    assert store.next_experiment(state, ["a", "b"]) == "b"  # a is known here now
    store.observe(state, "b", {"pos": 1, "mode": "day"})
    assert store.next_experiment(state, ["a", "b"]) is None
    assert store.next_experiment({"pos": 0, "mode": "night"}, ["a", "b"]) == "a"  # a different condition: the rules do not carry over, so it is explored again
    assert store.best_action(state, ["a", "b"], lambda e: e["pos"]) == "b" and store.best_action(state, ["a", "b"], lambda e: -abs(e["pos"])) is None


# ---- world model --------------------------------------------------------------------------------------------------------------------
GOOD = '''
class GeneratedWorldModel:
    def init_state(self, obs):
        return {"x": obs["x"]}

    def transition(self, state, action):
        step = {"inc": 1, "dec": -1}.get(action, 0)
        return {"x": state["x"] + step}

    def render(self, state):
        return {"x": state["x"]}
'''
WRONG = GOOD.replace('"inc": 1', '"inc": 2')
SHY = GOOD.replace("        return {\"x\": state[\"x\"]}\n", "        return {\"x\": state[\"x\"]} if state[\"x\"] >= 0 else None\n")
BROKEN = GOOD.replace('return {"x": state["x"] + step}', 'return {"x": state["x"] / 0}')
LOG = [({"x": i}, "inc", {"x": i + 1}) for i in range(6)] + [({"x": i}, "dec", {"x": i - 1}) for i in range(1, 7)]


def test_a_world_model_is_checked_against_what_really_happened_and_abstaining_is_not_guessing():
    with WorldModel(GOOD, step_timeout_ms=2000) as model:
        fit = check(model, LOG)
        assert fit.accuracy == 1.0 and fit.coverage == 1.0 and fit.checked == 12 and fit.first_error is None
    with WorldModel(WRONG, step_timeout_ms=2000) as model:
        fit = check(model, LOG)
        assert fit.accuracy == pytest.approx(6 / 12) and fit.first_error == 0  # the decrements still come out right: half of the replay
    with WorldModel(SHY, step_timeout_ms=2000) as model:
        fit = check(model, [({"x": 0}, "dec", {"x": -1}), ({"x": 3}, "inc", {"x": 4})])
        assert fit.coverage == 0.5 and fit.accuracy == 1.0  # it declined the one it could not determine
    with WorldModel(BROKEN, step_timeout_ms=2000) as model:
        fit = check(model, LOG)
        assert fit.accuracy == 0.0 and fit.first_error == 0 and model.faulted


def test_lookahead_finds_the_shortest_plan_inside_the_model_and_gives_up_cleanly():
    with WorldModel(GOOD, step_timeout_ms=2000) as model:
        assert lookahead(model, {"x": 0}, ["inc", "dec"], lambda o: o["x"] == 3) == ["inc", "inc", "inc"]
        assert lookahead(model, {"x": 0}, ["inc", "dec"], lambda o: o["x"] == 99, depth=4) is None
        assert lookahead(model, {"x": 5}, ["inc", "dec"], lambda o: o["x"] == 5 + 1) == ["inc"]
    with WorldModel(BROKEN, step_timeout_ms=2000) as model:
        assert lookahead(model, {"x": 0}, ["inc"], lambda o: o["x"] == 1) is None


def test_model_written_world_models_pass_through_the_same_static_gate_as_skills():
    from playfellow_coop.skillsmith.ast_gate import SkillRejected
    with pytest.raises(SkillRejected):
        WorldModel("import os\nclass GeneratedWorldModel:\n    def init_state(self, obs):\n        return {}\n    def transition(self, s, a):\n        return s\n    def render(self, s):\n        return s\n")
    with pytest.raises(SkillRejected):
        WorldModel("class GeneratedWorldModel:\n    def init_state(self, obs):\n        return {}\n")  # transition and render are missing


def test_the_orchestrator_builds_plans_repairs_or_just_acts_depending_on_evidence_trust_and_budget():
    o = Orchestrator(min_log=12, trust=0.9, build_cost_usd=0.05, budget_usd=0.12)
    assert o.decide(5, None) == ACT and o.decide(20, None) == BUILD
    o.charge(BUILD)
    assert o.decide(20, Fit(0.97, 0.8, 20)) == PLAN and o.decide(20, Fit(0.97, 0.8, 20), recent_mismatches=1) == REPAIR
    assert o.decide(20, Fit(0.5, 0.9, 20)) == REPAIR
    o.charge(REPAIR)
    assert o.repairs == 1 and o.spent_usd == pytest.approx(0.10) and o.decide(20, Fit(0.5, 0.9, 20)) == ACT  # the budget is nearly gone: stop paying
    assert o.decide(20, Fit(0.97, 0.3, 20)) == ACT  # accurate but silent about most steps: not enough to plan with


# ---- context ------------------------------------------------------------------------------------------------------------------------
def test_the_context_window_keeps_the_best_and_the_latest_within_the_token_budget_and_reports_the_trend():
    window = ContextWindow(max_tokens=60)
    for i, score in enumerate([0.1, 0.4, 0.2, 0.5, 0.6, 0.7]):
        window.add(EpisodeSummary(i + 1, score, tried=[f"approach {i}"], learned=["key a moves left"] if i > 2 else [], failure="" if score > 0.6 else "ran out of lives"))
    text = window.render()
    assert "best was episode 6" in text and "Episode 6" in text and "Episode 1:" not in text and "trend +0.12" in text
    assert tokens(text) <= 60 + 40  # the header and the best episode ride on top of the budget
    assert ContextWindow().render() == "" and ContextWindow().trend() == 0.0
    lines = text.splitlines()[1:]
    assert [int(l.split(":")[0].split()[1]) for l in lines] == sorted(int(l.split(":")[0].split()[1]) for l in lines)  # in the order they happened
