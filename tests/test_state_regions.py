"""The screen-state classifier learns WHERE a game writes how a round ended, and ships one fitted file per look.

The arena games end with a few words in a corner of the HUD ("You win!" in green, "Game over" in red) over a board that looks just like play: the ten whole-picture
measurements cannot see them, a learned region can. Synthetic pictures only; no engine, no network.
"""
import json

import numpy as np
import pytest

from playfellow_coop.universal import state_fit
from playfellow_coop.universal.state import INKS, StateClassifier, features, region_features

RNG = np.random.default_rng(11)
GREY_TEXT, GREEN_TEXT, RED_TEXT = (190, 190, 205), (90, 225, 120), (240, 95, 115)


def board(seed: int) -> np.ndarray:
    """A busy game board with a dark HUD strip on top; the strip's second line is where the game writes its status."""
    rng = np.random.default_rng(seed)
    frame = (rng.random((240, 320, 3)) * 120 + 40).astype(np.uint8)
    frame[:30] = (18, 20, 34)
    frame[6:12, 8:80] = GREY_TEXT  # "Snake  Score: 0": the same in every picture
    return frame


def with_status(frame: np.ndarray, colour) -> np.ndarray:
    out = frame.copy()
    for letter in range(8):  # a short word: eight letter-sized blocks of ink
        out[17:25, 10 + letter * 7:14 + letter * 7] = colour
    return out


def examples(seeds) -> list:
    rows = []
    for seed in seeds:
        play = [with_status(board(seed * 10 + i), GREY_TEXT) for i in range(6)]
        rows += [(f, "gameplay", p) for p, f in zip(play, play[1:])]
        end_board = board(seed * 10 + 9)
        rows.append((with_status(end_board, GREEN_TEXT if seed % 2 else RED_TEXT), "victory" if seed % 2 else "dead", None))
    return rows


def test_region_features_measure_the_colour_of_the_ink_in_a_region():
    hud = (0.0, 30 / 240, 0.0, 0.5)
    green = region_features(with_status(board(1), GREEN_TEXT), [hud])
    red = region_features(with_status(board(1), RED_TEXT), [hud])
    grey = region_features(with_status(board(1), GREY_TEXT), [hud])
    assert green.shape == (len(INKS),) and len(INKS) == 5
    share = dict(zip(INKS, green))
    assert share["green"] > 0.3 and share["red"] == 0.0
    assert dict(zip(INKS, red))["red"] > 0.3 and dict(zip(INKS, grey))["light"] > 0.9
    assert region_features(np.zeros((40, 40, 3), np.uint8), [hud]).tolist() == [0.0] * 5  # no ink: all zero, never a division by zero
    assert features(board(1)).shape == (10,)  # the whole-picture measurements are unchanged


def test_whole_picture_measurements_cannot_tell_these_ends_from_play_but_a_learned_region_can():
    train, held = examples(range(0, 12)), examples(range(100, 108))
    plain = StateClassifier().fit(train)
    plain_ends = [plain.classify(f, p)[0] == label for f, label, p in held if label != "gameplay"]
    assert sum(plain_ends) < len(plain_ends)  # the reason regions exist: a few letters do not move the whole-picture numbers

    model = StateClassifier().fit(train, regions=2)
    assert model.fitted and len(model.regions) == 2
    y0, y1, x0, x1 = model.regions[0]
    assert y0 < 25 / 240 and y1 > 17 / 240 and x0 < 0.25  # the best region covers the status line
    assert set(model.centres) == {"gameplay", "dead", "victory"}  # only the screens it was shown; loading stays with the strict rule
    for frame, label, previous in held:
        assert model.classify(frame, previous)[0] == label


def test_regions_round_trip_through_json_and_old_files_still_load():
    model = StateClassifier().fit(examples(range(6)), regions=1)
    again = StateClassifier.from_json(json.loads(json.dumps(model.to_json())))
    assert again.regions == model.regions and again.fitted
    frame = with_status(board(5), GREEN_TEXT)
    (state, confidence), (state_before, confidence_before) = again.classify(frame), model.classify(frame)
    assert state == state_before == "victory" and confidence == pytest.approx(confidence_before, abs=1e-3)  # the file keeps five decimals
    old = StateClassifier().fit(examples(range(6))).to_json()  # a file written before regions existed
    assert "regions" not in old
    assert StateClassifier.from_json(old).regions == []


def test_learning_regions_needs_two_kinds_of_screen():
    only_play = [(board(i), "gameplay", None) for i in range(4)]
    with pytest.raises(ValueError):
        StateClassifier().fit(only_play, regions=1)


def test_the_loader_picks_the_file_for_the_look_in_use(tmp_path, monkeypatch):
    classic = StateClassifier().fit(examples(range(6)), regions=1)
    glass = StateClassifier().fit(examples(range(6, 12)), regions=2)
    state_fit.save(tmp_path / "snake.json", classic)
    state_fit.save(tmp_path / "glass" / "snake.json", glass)
    assert len(state_fit.load_state_classifier("snake", tmp_path, look="classic").regions) == 1
    assert len(state_fit.load_state_classifier("snake", tmp_path, look="glass").regions) == 2
    assert state_fit.load_state_classifier("box_push", tmp_path, look="glass") is None
    monkeypatch.setattr(state_fit, "engine_look", lambda: "glass")
    assert len(state_fit.load_state_classifier("snake", tmp_path).regions) == 2  # no look given: the running engine's look
    assert state_fit.folder_for("classic") == state_fit.FOLDER and state_fit.folder_for("glass") == state_fit.FOLDER / "glass"


def test_engine_look_reads_the_engine_on_the_path():
    import importlib.util
    expected = "glass" if importlib.util.find_spec("arena_pack") and importlib.util.find_spec("arena_pack.skins") else "classic"
    assert state_fit.engine_look() == expected


def test_collect_keeps_a_bounded_sample_of_play_and_the_frozen_end_screen():
    class Game:
        keys = ("left", "right")

        def __init__(self, seed):
            self.t, self.done, self.seed = 0, False, seed

        def render(self):
            from PIL import Image
            return Image.fromarray(np.full((20, 20, 3), self.t % 250, np.uint8))

        def step(self, key):
            self.t += 1
            self.done = self.t >= 50

        def is_won(self):
            return self.seed == 1

    seen_frames = []

    def policy(seed):
        def play(game, rng, frame):
            seen_frames.append(frame.shape)
            return "left"
        return play

    rows = state_fit.collect(Game, range(2), steps=500, policy=policy, keep=10, frozen_ends=2)
    plays = [r for r in rows if r[1] == "gameplay"]
    ends = [r for r in rows if r[1] != "gameplay"]
    assert len(plays) == 20  # at most `keep` per episode, spread over the whole episode
    assert [r[1] for r in ends] == ["dead"] * 3 + ["victory"] * 3
    assert ends[1][2] is ends[1][0]  # the frozen copies: the end picture seen after itself, as the watch sees it once the round is over
    assert seen_frames and seen_frames[0] == (20, 20, 3)  # the policy is handed the picture it plays from
