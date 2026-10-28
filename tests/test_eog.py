"""End-of-game detection: the signals fire on a finished or cut-away game without any "game over" banner, stay quiet in play, and never end a match on an unreadable answer."""
from __future__ import annotations

import numpy as np
import pytest

from playfellow_coop.universal.eog import EoGDetector, ProbeVerifier, cheap_embedding, contact_sheet

RNG = np.random.default_rng(11)


def scene(x: int, background: int = 0) -> np.ndarray:
    """A 90 x 160 picture: a bright square (the avatar) at column x over a smooth wavy background that slides by `background` pixels."""
    base = (120 + 60 * np.sin((np.arange(160)[None, :, None] + background) / 12.0)).astype(np.uint8)
    base = np.tile(base, (90, 1, 3))
    base[40:56, x:x + 16] = (250, 60, 60)
    return base


def play_frames(count, start=10, background=False):
    x, frames = start, []
    for i in range(count):
        x = (x + 3) % 120
        frames.append(scene(x, i * 2 if background else 0))
    return frames


BAND = (0, 30, 160, 70)  # where the tracker says the avatar lives: the whole row it moves along


def run(detector, frames, action=1.0, hud=None):
    out = []
    prev = frames[0]
    for cur in frames[1:]:
        out.append(detector.update(prev, cur, action, avatar_box=BAND, hud=hud))
        prev = cur
    return out


def test_normal_play_never_triggers_even_with_a_busy_background():
    detector = EoGDetector(fps=30)
    verdicts = run(detector, play_frames(150, background=True))
    assert all(not v.ended and v.outcome == "ACTIVE_PLAY" for v in verdicts)


def test_a_finished_match_that_keeps_animating_elsewhere_collapses_contingency_and_the_verifier_ends_it_once():
    calls = []

    def verifier(sheet, hud, triggers):
        calls.append((sheet.shape, list(triggers)))
        return {"outcome": "MATCH_TERMINATED"}

    detector = EoGDetector(fps=30, verifier=verifier)
    play = play_frames(60)
    frozen_avatar = [scene(60, i * 2) for i in range(80)]  # the avatar no longer answers; the background slides on (a victory camera pan)
    verdicts = run(detector, play + frozen_avatar)
    ended = [i for i, v in enumerate(verdicts) if v.ended]
    assert ended and ended[0] >= 59 and calls and calls[0][0] == (432, 768, 3) and "action_contingency_collapse" in calls[0][1]
    assert verdicts[ended[0]].outcome == "MATCH_TERMINATED" and verdicts[ended[0]].verified


def test_a_blocked_key_is_not_the_end_the_probe_verifier_sees_other_keys_still_answer_and_the_detector_rests():
    state = {"x": 60, "blocked": {"right"}}
    frames = []

    def grab():
        return scene(state["x"])

    def act(key):
        if key not in state["blocked"]:
            state["x"] = (state["x"] + (6 if key == "right" else -6)) % 120

    verifier = ProbeVerifier(act, grab, ["right", "left", "up"])
    detector = EoGDetector(fps=30, verifier=verifier)
    stuck = [scene(60) for _ in range(40)]  # pressing the blocked key: nothing moves
    verdicts = run(detector, play_frames(20) + stuck)
    assert not any(v.ended for v in verdicts)
    asked = [v for v in verdicts if v.triggers]
    assert asked and asked[0].outcome == "ACTIVE_PLAY" and asked[0].verified
    # when NO key answers any more, the same probe ends the match
    dead = ProbeVerifier(lambda k: None, lambda: scene(60), ["right", "left", "up"])
    assert dead(contact_sheet([scene(1)]), {}, [])["outcome"] == "MATCH_TERMINATED"


def test_an_unreadable_or_unknown_verifier_answer_never_ends_a_match_and_no_verifier_means_a_candidate_only():
    for answer in (None, {}, {"outcome": "BANANA"}, "nonsense"):
        detector = EoGDetector(fps=30, verifier=lambda s, h, t, a=answer: a)
        verdicts = run(detector, play_frames(10) + [scene(60)] * 60)
        assert not any(v.ended for v in verdicts)
    detector = EoGDetector(fps=30)
    verdicts = run(detector, play_frames(10) + [scene(60)] * 60)
    first = next(v for v in verdicts if v.candidate)
    assert first.outcome == "CANDIDATE" and not first.ended and not first.verified and "action_contingency_collapse" in first.triggers


def test_hud_signals_fire_on_a_score_reset_an_empty_health_bar_and_vanished_anchors():
    seen = []
    detector = EoGDetector(fps=30, verifier=lambda s, h, t: seen.append(list(t)) or {"outcome": "ACTIVE_PLAY"})
    frames = play_frames(40)
    prev = frames[0]
    scores = [10] * 20 + [0] * 20
    for cur, score in zip(frames[1:], scores):
        detector.update(prev, cur, 0.0, hud={"score": score, "anchors": 4})
        prev = cur
    assert ["score_reset"] in seen
    detector = EoGDetector(fps=30, verifier=lambda s, h, t: seen.append(list(t)) or {"outcome": "ACTIVE_PLAY"})
    prev = frames[0]
    for cur in frames[1:]:
        detector.update(prev, cur, 0.0, hud={"health_ratio": 0.0, "anchors": 4})
        prev = cur
    assert ["health_depleted"] in seen
    detector = EoGDetector(fps=30, verifier=lambda s, h, t: seen.append(list(t)) or {"outcome": "ACTIVE_PLAY"})
    prev = frames[0]
    for i, cur in enumerate(frames[1:]):
        detector.update(prev, cur, 0.0, hud={"anchors": 4 if i < 5 else 0})
        prev = cur
    assert ["hud_vanished"] in seen


def test_a_cut_to_a_different_scene_trips_the_regime_shift_test_without_any_input():
    seen = []
    detector = EoGDetector(fps=30, verifier=lambda s, h, t: seen.append(list(t)) or {"outcome": "TEMP_CUTSCENE"})
    play = play_frames(50)
    lobby = [(RNG.random((90, 160, 3)) * 255).astype(np.uint8) for _ in range(30)]
    verdicts = run(detector, play + lobby, action=0.0)
    assert any("regime_shift" in t for t in seen) and not any(v.ended for v in verdicts)


def test_contact_sheet_and_embedding_shapes():
    sheet = contact_sheet([scene(i) for i in range(10)], tile=(64, 36))
    assert sheet.shape == (72, 128, 3)
    assert contact_sheet([scene(1)], tile=(32, 18)).shape == (36, 64, 3)
    assert cheap_embedding(scene(5)).shape == (64 + 8 + 4,)
    with pytest.raises(ValueError):
        contact_sheet([])
    detector = EoGDetector(fps=30)
    detector.reset()
    assert detector.state.low_contingency == 0
