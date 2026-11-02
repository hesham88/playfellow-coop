"""The platformer genre skill: one model decision, then many fast moves read from the picture alone (run, jump when stuck, jump again when
still stuck, attack now and then). It is built from any controls card whose genre is platformer, so no game needs a skill of its own."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

import controls
from bench import arena_run as ar
from playfellow_coop.skills.platform_runner import RunAndJump, keys_from_card

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


def test_keys_come_from_the_card_and_a_card_without_run_or_jump_gets_no_runner():
    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    keys = keys_from_card(card, direction="right")
    assert keys["run"] == "right" and keys["jump"] == "space" and keys["attack"] in {k for a in card.actions.values() for k in a.keys}
    snake = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")
    assert keys_from_card(snake, direction="right") is None  # not a platformer: never offered


def test_it_runs_while_the_picture_moves_and_jumps_when_it_stops_moving():
    skill = RunAndJump({"run": "right", "jump": "space", "attack": "s"}, attack_every=99)
    skill.reset()
    moving = [np.random.default_rng(i).integers(0, 255, (60, 80, 3), dtype=np.uint8) for i in range(6)]
    assert [skill.next_key(f) for f in moving] == ["right"] * 6
    still = np.zeros((60, 80, 3), dtype=np.uint8)
    pressed = [skill.next_key(still) for _ in range(8)]
    assert "space" in pressed  # stuck: it jumps
    assert pressed.count("space") >= 2  # still stuck after a jump: it jumps again (a double jump)


def test_it_attacks_now_and_then():
    skill = RunAndJump({"run": "right", "jump": "space", "attack": "s"}, attack_every=4)
    skill.reset()
    frames = [np.random.default_rng(i).integers(0, 255, (60, 80, 3), dtype=np.uint8) for i in range(12)]
    assert "s" in [skill.next_key(f) for f in frames]


class Wall:
    """A tiny side view: the player runs right one cell a step and a wall two cells high stands at x=12; a jump lifts the player for 3
    steps. Holding right alone stays stuck at the wall forever."""

    def __init__(self):
        self.x, self.air = 2, 0

    def frame(self):
        f = np.zeros((40, 200, 3), dtype=np.uint8)
        f[30:40, 120:130] = 200  # the wall
        f[30 - (8 if self.air else 0):38 - (8 if self.air else 0), self.x * 10:self.x * 10 + 8] = 90  # the player
        return f

    def step(self, key):
        if key == "space" and self.air == 0:
            self.air = 3
        blocked = self.x + 1 == 12 and self.air == 0
        if key == "right" and not blocked:
            self.x += 1
        self.air = max(0, self.air - 1) if key != "space" else self.air


def test_it_gets_over_a_wall_that_holding_right_never_passes():
    def play(skill):
        game = Wall()
        for _ in range(60):
            key = skill.next_key(game.frame()) if skill else "right"
            game.step(key)
        return game.x

    runner = RunAndJump({"run": "right", "jump": "space", "attack": None}, attack_every=99)
    runner.reset()
    assert play(None) == 11 and play(runner) > 12


def test_a_platformer_card_without_its_own_skill_gets_the_genre_skill_offered_to_the_model():
    import settings
    from types import SimpleNamespace

    from playfellow_coop import __main__ as entry

    class Brain:
        skills = None

        def set_skills(self, names):
            self.skills = tuple(names)

    card = controls.load_card(ENGINE / "controls" / "rayman_legends.yaml")
    parts = SimpleNamespace(brain=Brain(), card=card)
    cfg = settings.Settings(controls_card="rayman_legends")
    entry.attach_skills(parts, cfg, "on")
    assert parts.brain.skills == ("run_and_jump", "none") and parts.skills.readable(np.zeros((20, 20, 3), dtype=np.uint8))
    assert "run_and_jump" in parts.skills.system_text()


def _level(gap_from: float | None, shift: int, h: int = 90, w: int = 160) -> np.ndarray:
    """Sky above, textured ground in the bottom third; a pit from gap_from (a share of the width) shows sky down to the bottom edge.
    shift scrolls the ground texture so the picture keeps moving, as a side-scroller does while the player runs."""
    frame = np.full((h, w, 3), (90, 150, 220), dtype=np.uint8)
    top = int(h * 0.7)
    frame[top:, :] = np.random.default_rng(shift).integers(40, 130, (h - top, w, 3), dtype=np.uint8)  # new texture every frame
    frame[top, :] = (230, 230, 230)  # the ground's top edge
    if gap_from is not None:
        frame[top:, int(w * gap_from):int(w * (gap_from + 0.12))] = (90, 150, 220)
    return frame


def test_it_jumps_before_a_pit_ahead_while_the_picture_still_moves():
    skill = RunAndJump({"run": "right", "jump": "space", "attack": None}, attack_every=0)
    skill.reset()
    keys = [skill.next_key(_level(None, s)) for s in range(4)]
    assert keys == ["right"] * 4  # flat ground: it only runs
    keys = [skill.next_key(_level(0.6, 4 + s)) for s in range(3)]
    assert keys[0] == "space"  # a pit ahead: jump before reaching it, though the picture never stopped moving
    assert keys[1:] == ["right", "right"]  # holds run through the jump, and does not jump again at once


def test_a_pit_far_off_or_under_the_player_does_not_make_it_jump():
    skill = RunAndJump({"run": "right", "jump": "space", "attack": None}, attack_every=0)
    skill.reset()
    assert [skill.next_key(_level(0.9, s)) for s in range(3)] == ["right"] * 3  # too far ahead yet
    skill.reset()
    assert [skill.next_key(_level(0.38, s)) for s in range(3)] == ["right"] * 3  # under the player: no ground to judge by
