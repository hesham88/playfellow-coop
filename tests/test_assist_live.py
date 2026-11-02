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


# ---- each request's "really done" rule says exactly what the words say -----------------------------------------------------------------
def _task(game, request):
    return next(t for t in al.TASKS if t[0] == game and t[1] == request)


def test_coins_on_the_left_counts_only_coins_from_the_left_half():
    game = al.ar.load_game("maze_chase", 0)
    start = al.snapshot(game)
    _, _, truth = _task("maze_chase", "grab the coins on the left")
    width = len(game.level[0]) if hasattr(game, "level") else max(x for x, _ in start["coins"]) + 1
    right = [c for c in start["coins"] if c[0] >= al.half(game)]
    left = [c for c in start["coins"] if c[0] < al.half(game)]
    assert left and right
    game.coins -= set(right[:3])  # coins from the right half: not what was asked
    assert truth(start, game) is False
    game.coins -= set(left[:2])
    assert truth(start, game) is True


def test_past_this_jump_means_past_the_next_spike_and_alive():
    game = al.ar.load_game("key_caves", 0)
    start = al.snapshot(game)
    _, _, truth = _task("key_caves", "get me past this jump")
    spike = al.next_spike_x(start["x"], start["y"])
    assert spike is not None and spike > start["x"]
    game.x = spike + 1
    assert truth(start, game) is True
    game.dead = True
    assert truth(start, game) is False
    game.dead, game.x = False, spike - 1
    assert truth(start, game) is False


def test_take_me_to_the_door_means_at_or_past_the_door():
    game = al.ar.load_game("key_caves", 0)
    start = al.snapshot(game)
    _, _, truth = _task("key_caves", "take me to the door")
    door = al.door_x()
    game.x = door - 3
    assert truth(start, game) is False
    game.x = door - 1
    assert truth(start, game) is True


def test_every_rule_is_written_out_for_the_evidence_page():
    assert all(len(t) == 3 for t in al.TASKS) and set(al.RULES) == {(g, r) for g, r, _ in al.TASKS}
    assert "left half" in al.RULES[("maze_chase", "grab the coins on the left")]
