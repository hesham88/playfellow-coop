"""SAM 3.1 marks with stable IDs across frames (the application: "stable IDs across frames"): the same thing on screen keeps its number
while the player moves. Scored against the Practice Arena's own truth; the fake server here checks the harness only, never SAM."""
from __future__ import annotations

import pytest

from playfellow_coop import sam_marks
from playfellow_coop.budget import DailyBudget
from playfellow_coop.fakes import FakeSam
from playfellow_coop.sam_eval import arena_objects, id_stability
from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker
from playfellow_coop.tracking import Tracker
from practice_arena.game import ArenaGame

KEYS = ["right", "right", "down", "down", "right", "left", "up", "right", "down", "right"]


@pytest.fixture
def game():
    return ArenaGame()


@pytest.fixture
def fake(game, monkeypatch):
    with FakeSam(game, DEFAULT_PROMPTS) as server:
        monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", server.url)
        yield server


def _frames(game, keys):
    out = [(game.render(), arena_objects(game))]
    for key in keys:
        game.press(key)
        out.append((game.render(), arena_objects(game)))
    return out


def test_every_object_has_a_name_that_survives_frames(game):
    names = arena_objects(game)
    assert "me" in names and any(n.startswith("coin@") for n in names) and "door" in names


def test_with_the_tracker_the_same_things_keep_their_numbers_while_the_player_moves(game, fake, tmp_path):
    marker = SamMarker("sam-test-key", budget=DailyBudget(tmp_path / "s.json", cap_usd=5, max_calls=1000), tracker=Tracker(refresh_every=3))
    result = id_stability(marker, _frames(game, KEYS), source="fake server")
    assert result["pairs"] > 10 and result["stable_rate"] == 1.0
    assert "fake" in result["source"] and "says nothing about SAM" in result["note"]


def test_a_marker_that_renumbers_everything_each_frame_scores_low(game, fake, tmp_path):
    class Renumber(Tracker):
        def anchor(self, frame, found):
            super().anchor(frame, found)
            for t in self.tracks:  # a broken tracker: a fresh number for everything, every time SAM answers
                t.id, self._next = self._next, self._next + 1

    marker = SamMarker("sam-test-key", budget=DailyBudget(tmp_path / "s.json", cap_usd=5, max_calls=1000), tracker=Renumber(refresh_every=1))
    result = id_stability(marker, _frames(game, KEYS), source="fake server")
    assert result["stable_rate"] < 0.5
