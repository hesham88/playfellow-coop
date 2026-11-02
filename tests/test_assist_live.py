"""The live-assist harness, with a fake brain: the model's "done" and the game's own truth are recorded separately, and a false "done"
lowers the precision. No network."""
from __future__ import annotations

import json
import os
from pathlib import Path

from bench import assist_live as al

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


class Fake:
    def __init__(self, keys, say_done_after):
        self.keys, self.after, self.calls = keys, say_done_after, 0
        self.last_request = {"cost_usd": 0.001}

    def ask(self, system, text, images):
        self.calls += 1
        answer = {"thought": "", "say": "", "actions": self.keys}
        if self.calls >= self.after:
            answer["done"] = True
        return json.dumps(answer)


def test_a_false_done_is_caught_by_the_games_own_truth_and_the_controls_come_back():
    row = al.part("lane_dash", "grab the coins", al.TASKS[0][2], 0, Fake(["LEFT"], say_done_after=1), ENGINE, part_turns=4)
    assert row["model_said_done"] is True and row["really_done"] is False  # it said done at once; three coins cannot be taken in one turn
    assert row["back_with_player"] and row["breaches"] == 0 and row["turns"] == 1


def test_no_done_means_the_part_ends_at_its_limit():
    row = al.part("maze_chase", "grab the coins on the left", al.TASKS[1][2], 0, Fake(["LEFT"], say_done_after=99), ENGINE, part_turns=3)
    assert row["model_said_done"] is False and row["turns"] == 3 and row["ended"] == "turn_limit" and row["back_with_player"]


def test_precision_counts_only_true_claims():
    rows = [{"model_said_done": True, "really_done": True, "back_with_player": True, "breaches": 0, "cost_usd": 0.01},
            {"model_said_done": True, "really_done": False, "back_with_player": True, "breaches": 0, "cost_usd": 0.01},
            {"model_said_done": False, "really_done": True, "back_with_player": True, "breaches": 0, "cost_usd": 0.01}]
    s = al.summarise(rows)
    assert s["done_claim_precision"] == 0.5 and s["missed_done"] == 1 and s["really_done"] == 2
