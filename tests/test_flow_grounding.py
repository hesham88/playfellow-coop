"""Grounding in worlds that move on their own: the avatar is the region whose velocity changes with the keys; obstacles slide the same whatever is pressed."""
from __future__ import annotations

import numpy as np
import pytest

from playfellow_coop.universal.flow_grounding import probe_flow, region_velocity

KEYS = ["up", "down", "left", "right"]
PUSH = {"up": (0, -6), "down": (0, 6), "left": (-5, 0), "right": (5, 0)}


class Runner:
    """The avatar always drifts right (3 px a tick); a key adds a push for that tick. An obstacle slides on its own whatever is pressed."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.sprite = rng.integers(60, 255, (10, 10, 3)).astype(np.uint8)  # a textured sprite: colour is unknown to the harness
        self.rock = rng.integers(60, 255, (8, 8, 3)).astype(np.uint8)
        self.pos = [30.0, 40.0]
        self.rock_pos = [90.0, 20.0]
        self.push = (0, 0)

    def frame(self):
        img = np.full((90, 140, 3), 12, np.uint8)
        x, y = int(self.pos[0]), int(self.pos[1])
        img[y:y + 10, x:x + 10] = self.sprite
        rx, ry = int(self.rock_pos[0]), int(self.rock_pos[1])
        img[ry:ry + 8, rx:rx + 8] = self.rock
        return img

    def press(self, key):
        self.push = PUSH[key]

    def tick(self):
        self.pos[0] = float(np.clip(self.pos[0] + 3 + self.push[0], 12, 118))
        self.pos[1] = float(np.clip(self.pos[1] + self.push[1], 12, 68))
        self.rock_pos[0] = 90.0 + (self.rock_pos[0] - 90.0 - 2) % -30  # slides left
        self.push = (0, 0)


@pytest.mark.parametrize("seed", range(6))
def test_a_self_moving_avatar_is_found_by_how_its_velocity_changes_with_keys_and_the_obstacle_is_left_alone(seed):
    world = Runner(seed)
    start = list(world.pos)
    found = probe_flow(world.press, world.frame, KEYS, neutral=world.tick)
    assert found.avatar_box is not None
    left, top, right, bottom = found.avatar_box
    assert left - 20 <= start[0] + 5 <= right + 20 and top - 20 <= start[1] + 5 <= bottom + 20  # on the sprite's patch (it travels), not on the rock
    assert abs(found.bindings["up"][1] + 6) <= 1.5 and abs(found.bindings["down"][1] - 6) <= 1.5
    assert found.bindings["right"][0] > 2 and found.bindings["left"][0] < -2
    assert abs(found.quiet_velocity[0] - 3) <= 1.5 and len(found.obstacles) >= 1  # the baseline is the tick just before the press


def test_a_world_where_nothing_responds_gives_no_avatar_and_a_still_world_gives_nothing():
    world = Runner(0)
    world.press = lambda key: None  # the keys do nothing
    found = probe_flow(world.press, world.frame, KEYS, neutral=world.tick)
    assert found.avatar_box is None and found.obstacles
    still = probe_flow(lambda k: None, lambda: np.full((40, 40, 3), 9, np.uint8), KEYS)
    assert still.avatar_box is None and still.obstacles == []


def test_region_velocity_measures_a_slide_and_declines_when_it_cannot():
    rng = np.random.default_rng(3)
    big = rng.integers(0, 255, (60, 60, 3)).astype(np.uint8)
    moved = np.roll(big, (0, 4), axis=(0, 1))
    assert region_velocity(big, moved, (10, 10, 50, 50), pad=10) == (4.0, 0.0)
    flat = np.full((60, 60, 3), 5, np.uint8)
    assert region_velocity(flat, flat, (10, 10, 50, 50)) is None


class Hopper:
    """Obstacles slide on their own; the avatar stands in one of three lanes (40 px apart) and a key makes it jump a lane at once: a teleport, not a slide."""

    def __init__(self, seed):
        rng = np.random.default_rng(seed)
        self.sprite = rng.integers(60, 255, (10, 10, 3)).astype(np.uint8)
        self.lane, self.rows = 1, [0.0, 25.0]

    def frame(self):
        img = np.full((90, 140, 3), 12, np.uint8)
        img[70:80, 20 + 40 * self.lane:30 + 40 * self.lane] = self.sprite
        for i, r in enumerate(self.rows):
            img[int(r):int(r) + 6, 10 + 50 * i:40 + 50 * i] = (200, 40, 40)
        return img

    def press(self, key):
        self.lane = int(np.clip(self.lane + (1 if key == "right" else -1), 0, 2))

    def tick(self):
        self.rows = [(r + 4) % 60 for r in self.rows]


def test_a_jump_between_lanes_is_a_binding_too_while_sliding_obstacles_stay_out_of_it():
    world = Hopper(1)
    found = probe_flow(world.press, world.frame, ["left", "right"], neutral=world.tick, restart=lambda: setattr(world, "lane", 1))
    assert found.avatar_box is not None and found.avatar_box[1] >= 60  # at the bottom, where the sprite is, not on the sliding red bars
    assert found.bindings["right"][0] > 20 and found.bindings["left"][0] < -20
