"""Zero-shot grounding: the avatar is found from the keys alone, whatever its colour, and a skill's look is re-pointed at it."""
from __future__ import annotations

import numpy as np
import pytest

from playfellow_coop.skills.looks import Look
from playfellow_coop.universal.skin_grounding import Grounding, background_colour, changed_mask, probe, rebind_look

STEP = 8
KEYS = {"right": (STEP, 0), "left": (-STEP, 0), "down": (0, STEP), "up": (0, -STEP)}


class World:
    """A toy game: a coloured floor, an avatar square that moves with keys, and (optionally) a thing that drifts on its own each tick."""

    def __init__(self, avatar_colour, floor, mover=True, seed=0):
        rng = np.random.default_rng(seed)
        self.avatar_colour, self.floor = avatar_colour, floor
        self.pos = [int(rng.integers(30, 70)), int(rng.integers(30, 50))]
        self.mover = [10, 10] if mover else None
        self.has_mover = mover

    def frame(self):
        img = np.zeros((100, 120, 3), np.uint8)
        img[:] = self.floor
        x, y = self.pos
        img[y:y + 10, x:x + 10] = self.avatar_colour
        if self.mover:
            mx, my = self.mover
            img[my:my + 6, mx:mx + 6] = (200, 200, 40)
        return img

    def press(self, key):
        dx, dy = KEYS[key]
        self.pos[0] = int(np.clip(self.pos[0] + dx, 0, 108))
        self.pos[1] = int(np.clip(self.pos[1] + dy, 0, 88))

    def tick(self):
        if self.mover:
            self.mover[0] = (self.mover[0] + 5) % 110
            self.mover[1] = (self.mover[1] + 3) % 90


def run(world, keys=("right", "left", "down", "up"), rounds=1):
    return probe(world.press, world.frame, list(keys), neutral=world.tick, rounds=rounds)


@pytest.mark.parametrize("seed", range(12))
def test_the_avatar_is_found_by_its_response_to_keys_whatever_its_colour_and_a_drifting_thing_is_not_mistaken_for_it(seed):
    rng = np.random.default_rng(100 + seed)
    avatar = tuple(int(v) for v in rng.integers(60, 255, 3))
    floor = tuple(int(v) for v in rng.integers(0, 50, 3))
    world = World(avatar, floor, seed=seed)
    start = list(world.pos)
    found = probe(world.press, world.frame, ["right", "left", "down", "up"], neutral=world.tick)
    assert found.avatar_box is not None
    left, top, right, bottom = found.avatar_box
    cx, cy = (left + right) / 2, (top + bottom) / 2
    assert abs(cx - (start[0] + 5)) <= 2 * STEP and abs(cy - (start[1] + 5)) <= 2 * STEP  # on the avatar's patch, not on the drifting mover
    assert found.avatar_colour is not None and max(abs(a - b) for a, b in zip(found.avatar_colour, avatar)) <= 20
    assert found.contingency > 0.3 and found.confidence > 0.3 and any(abs(m[0]) >= 0 for m in found.movers) and len(found.movers) >= 1
    assert found.bindings["right"][0] > 0 > found.bindings["left"][0] and found.bindings["down"][1] > 0 > found.bindings["up"][1]
    assert abs(found.bindings["right"][0] - STEP) <= 3


def test_a_key_that_does_nothing_has_no_binding_and_a_game_with_no_avatar_gives_no_box():
    world = World((250, 80, 80), (10, 10, 10), mover=False)
    world.press = lambda key: None  # no key does anything
    found = probe(world.press, world.frame, ["right", "left"], neutral=world.tick)
    assert found.avatar_box is None and found.avatar_colour is None and found.confidence == 0.0 and all(v == (0.0, 0.0) for v in found.bindings.values()) or not found.bindings


def test_blocked_keys_still_find_the_avatar_from_the_keys_that_answer():
    world = World((240, 200, 60), (5, 5, 40), mover=False)
    original = world.press
    world.press = lambda key: original(key) if key in ("right", "down") else None  # left and up are walls
    found = probe(world.press, world.frame, ["left", "right", "up", "down"], neutral=world.tick)
    assert found.avatar_box is not None and "right" in found.bindings and found.bindings["right"][0] > 0


def test_the_look_is_re_pointed_at_the_new_skin_and_other_roles_are_kept():
    base = Look("glass", {"head": [(10.0, 200.0, 10.0)], "food": [(250.0, 20.0, 20.0)], "floor": [(0.0, 0.0, 0.0)]}, 30.0)
    found = Grounding(avatar_colour=(200.0, 120.0, 240.0))
    rebound = rebind_look(base, "head", found)
    assert rebound.protos["head"] == [(200.0, 120.0, 240.0)] and rebound.protos["food"] == base.protos["food"] and rebound.classify((205, 118, 238)) == "head"
    assert base.protos["head"] == [(10.0, 200.0, 10.0)]  # the original look is untouched
    assert rebind_look(base, "head", Grounding()) is None and rebound.radius >= 40.0


def test_helpers_background_and_change_mask():
    img = np.zeros((20, 20, 3), np.uint8)
    img[:] = (30, 60, 90)
    img[5:8, 5:8] = (255, 0, 0)
    assert max(abs(a - b) for a, b in zip(background_colour(img), (30, 60, 90))) <= 8
    other = img.copy()
    other[10:12, 10:12] = (0, 255, 0)
    mask = changed_mask(img, other)
    assert int(mask.sum()) == 4 and mask[10, 10] and not mask[5, 5]
