"""The self-improvement loop end to end on a real game: a model-written controller (here a scripted stand-in for the model) is checked by the static gate, run in the sandbox against pixels read
through a look, scored by the gym on validation seeds, promoted only if it strictly beats the current skill, and the held-out seeds are never played."""
from __future__ import annotations

import pytest

from bench import arena_run as ar
from playfellow_coop.gym import PlayfellowGym
from playfellow_coop.gym.obs import ActionMapper, ObsSpec, PixelObserver
from playfellow_coop.skills.paddle_track import ARENA_LOOK
from playfellow_coop.skillsmith.library import SkillLibrary
from playfellow_coop.skillsmith.loop import improve, score_code
from playfellow_coop.skillsmith.promote import Budget, BudgetExceeded, HeldOutLeak, Selector
from playfellow_coop.skillsmith.synth import Synthesizer

IDLE = '''
class GeneratedArenaSkill:
    def compute_action(self, obs):
        return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
'''

TRACKER = '''
class GeneratedArenaSkill:
    """Launch the ball, then keep the paddle under it."""
    def __init__(self):
        self.last = None

    def compute_action(self, obs):
        items = obs.get("items") or []
        sx = obs["self"][0]
        if not items:
            return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
        bx, by, vx, vy = items[0]
        if abs(vx) < 1e-6 and abs(vy) < 1e-6:
            return {"move": [0.0, 0.0], "buttons": ["fire"], "hold_ms": 0}
        gap = bx - sx
        if abs(gap) < 0.012:
            return {"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}
        return {"move": [1.0 if gap > 0 else -1.0, 0.0], "buttons": [], "hold_ms": 0}
'''

SPEC = ObsSpec(self_role="paddle", item_roles=("ball",), top=64)
MAPPER = ActionMapper(keys=("left", "right", "space"), buttons={"fire": "space"})
STEPS = 1200


def make_env_factory(played):
    def make(seed):
        played.append(seed)
        return PlayfellowGym("brick_breaker", lambda s: ar.load_game("brick_breaker", s), seed=seed)
    return make


@pytest.fixture
def observer():
    return PixelObserver(ARENA_LOOK, SPEC)


def test_a_model_written_controller_that_plays_better_is_promoted_and_the_held_out_seeds_are_never_played(tmp_path, observer):
    played = []
    library = SkillLibrary(tmp_path)
    synth = Synthesizer(lambda prompt: "```python\n" + TRACKER + "```", library, Budget(1.0, 20), cost_per_call_usd=0.05)
    result = improve("brick_breaker", "break every brick", library, synth, "idle", IDLE, make_env_factory(played), observer, MAPPER, validation_seeds=[0], test_seeds=[100, 101],
                     selector=Selector(), candidates=1, max_steps=STEPS)
    assert result.promoted is not None and result.scores[result.promoted].mean_progress > result.scores["idle"].mean_progress
    assert result.scores["idle"].mean_progress == 0.0 and result.scores[result.promoted].faults == 0
    assert set(played) == {0} and library.names("brick_breaker") == [result.promoted]  # only the validation seed was ever played; the skill is stored
    notes = library.experience("brick_breaker")
    assert any("promoted" in n and "validation progress" in n for n in notes) and library.get("brick_breaker", result.promoted) is not None
    assert synth.budget.calls == 1


def test_a_candidate_that_does_not_beat_the_current_skill_is_not_promoted_and_the_lesson_is_still_written(tmp_path, observer):
    library = SkillLibrary(tmp_path)
    synth = Synthesizer(lambda prompt: "```python\n" + IDLE + "```", library, Budget(1.0, 20), cost_per_call_usd=0.05)
    result = improve("brick_breaker", "goal", library, synth, "idle", IDLE, make_env_factory([]), observer, MAPPER, validation_seeds=[0], test_seeds=[100], selector=Selector(),
                     candidates=1, max_steps=60)
    assert result.promoted is None and library.names("brick_breaker") == [] and any("kept idle" in n for n in library.experience("brick_breaker"))


def test_a_rejected_proposal_the_budget_cap_the_reused_validation_set_and_a_held_out_leak_are_all_refused(tmp_path, observer):
    library = SkillLibrary(tmp_path)
    bad = Synthesizer(lambda prompt: "```python\nimport os\nclass GeneratedArenaSkill:\n    def compute_action(self, obs):\n        return {}\n```", library, Budget(1.0, 20), cost_per_call_usd=0.05)
    result = improve("brick_breaker", "goal", library, bad, "idle", IDLE, make_env_factory([]), observer, MAPPER, [0], [100], Selector(), candidates=1, max_steps=30)
    assert result.promoted is None and any("rejected" in n for n in library.experience("brick_breaker")) and bad.budget.calls == 2  # one retry, then give up
    tight = Synthesizer(lambda prompt: "x", library, Budget(0.05, 20), cost_per_call_usd=0.05)
    result = improve("brick_breaker", "goal", library, tight, "idle", IDLE, make_env_factory([]), observer, MAPPER, [1], [100], Selector(), candidates=2, max_steps=30)
    assert "budget" in result.reason or result.promoted is None
    selector = Selector()
    selector.choose("idle", {"idle": 0.0}, [5])
    with pytest.raises(HeldOutLeak):
        improve("brick_breaker", "goal", library, bad, "idle", IDLE, make_env_factory([]), observer, MAPPER, [7], [7], Selector(), candidates=0, max_steps=30)


def test_the_observer_reads_the_structured_observation_from_pixels_and_the_mapper_turns_actions_into_keys(observer):
    env = PlayfellowGym("brick_breaker", lambda s: ar.load_game("brick_breaker", s), seed=0)
    frame, _ = env.reset()
    obs = observer.build(frame)
    assert obs["visible"] and 0.0 < obs["self"][0] < 1.0 and obs["items"] and obs["t"] == 0 and obs["danger"] == 0.0
    frame, *_ = env.step("space")
    frame, *_ = env.step(None)
    moving = observer.build(frame)
    assert moving["t"] == 1 and moving["items"] and (abs(moving["items"][0][2]) > 0 or abs(moving["items"][0][3]) > 0)  # the launched ball has a velocity now
    assert MAPPER.key_for({"move": [1.0, 0.1], "buttons": []}) == "right" and MAPPER.key_for({"move": [-1.0, 0.0], "buttons": []}) == "left"
    assert MAPPER.key_for({"move": [0.1, 0.1], "buttons": []}) is None and MAPPER.key_for({"move": [0, 0], "buttons": ["fire"]}) == "space"
    assert MAPPER.key_for({"move": [0.0, 1.0], "buttons": []}) is None  # no down key in this game: nothing is pressed
    assert score_code(IDLE, make_env_factory([]), observer, MAPPER, [0], 20).mean_progress == 0.0
