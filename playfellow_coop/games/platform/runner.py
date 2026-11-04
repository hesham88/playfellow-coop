"""The genre skill: moves along a level at full speed from pixels alone, deciding with the camera's motion rather than a clock.

Each look says which keys to hold (`Runner.step`): the key set is the game's controls card, so nothing is assumed about a game.

  sprint          hold the run key; the sprint key too when the card has one
  blocked         the camera stops while running: jump, jump with a long hold, wall-kick away and back, then back off and try again
  gap             no ground ahead: jump and hold (a hold rises higher and hovers where the game allows it)
  attack          a short tap every so often while running (breaks cages, clears enemies), never while a jump is being held
  collectibles    yellow pick-ups above the path: a jump to reach them when nothing blocks
  after a death   a fade: let go of everything, count it, wait for the picture to return, and try the place more carefully
  progress        the furthest point and the map (world.py) are kept for the planner
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.games.platform.sight import camera_shift, collectibles, read_cut, small_grey
from playfellow_coop.games.platform.world import WorldMap
from playfellow_coop.skills.platform_runner import gap_ahead

STILL = 0.003  # share of the view per look under which the camera counts as stopped


@dataclass
class Keys:
    right: str = "right"
    left: str = "left"
    jump: str = "space"
    attack: str = "s"
    sprint: str | None = None


@dataclass
class Runner:
    keys: Keys = field(default_factory=Keys)
    forward: int = 1  # +1 right, -1 left
    world: WorldMap = field(default_factory=WorldMap)
    attack_every: int = 24  # looks
    long_jump: int = 10  # looks a jump key is held at most
    deaths: int = 0
    tick: int = 0
    stuck: int = 0
    jump_left: int = 0
    back_left: int = 0
    wait_left: int = 0
    care: int = 0  # looks of slower going after a death
    log: list = field(default_factory=list)
    _last: np.ndarray | None = None

    @property
    def run_key(self) -> str:
        return self.keys.right if self.forward > 0 else self.keys.left

    @property
    def back_key(self) -> str:
        return self.keys.left if self.forward > 0 else self.keys.right

    def _jump(self, looks: int, why: str) -> None:
        self.jump_left = max(self.jump_left, looks)
        self.log.append((self.tick, "jump", why))

    def step(self, frame: np.ndarray) -> set[str]:
        """The keys to hold until the next look."""
        self.tick += 1
        grey = small_grey(frame)
        shift, cut = 0.0, None
        if self._last is not None:
            dx, dy, tracked = camera_shift(self._last, grey)
            cut = read_cut(self._last, grey, tracked)
            shift = dx * self.forward
            if cut.kind == "none":
                self.world.move(dx, dy)
        self._last = grey
        if cut is not None and cut.kind == "fade":
            if self.wait_left == 0:
                self.deaths += 1
                self.care = 60
                self.log.append((self.tick, "fade", self.deaths))
            self.wait_left = 8
            self.jump_left = self.back_left = self.stuck = 0
            return set()
        if self.wait_left:
            self.wait_left -= 1
            return set()
        if cut is not None and cut.kind == "new_scene":
            self.world.new_room()
            self.stuck = 0
        if self.back_left:
            self.back_left -= 1
            return {self.back_key}
        keys = {self.run_key}
        if self.keys.sprint and not self.care:
            keys.add(self.keys.sprint)
        self.care = max(self.care - 1, 0)
        if self.jump_left:
            self.jump_left -= 1
            keys.add(self.keys.jump)
            return keys
        if self._blocked(shift):
            self._unstick(keys)
        elif gap_ahead(frame):
            self._jump(self.long_jump, "gap")
            keys.add(self.keys.jump)
        else:
            self.stuck = max(self.stuck - 1, 0)
            ahead = (lambda x: 0.5 < x < 0.8) if self.forward > 0 else (lambda x: 0.2 < x < 0.5)
            pickups = [p for p in collectibles(frame) if ahead(p[0]) and p[1] < 0.45]
            if pickups and self.tick % 12 == 0:
                self._jump(5, "pick-up above")
                keys.add(self.keys.jump)
            elif self.keys.attack and self.tick % self.attack_every == 0:
                keys.add(self.keys.attack)
        return keys

    def _blocked(self, shift: float) -> bool:
        return self.tick > 4 and abs(shift) < STILL

    def _unstick(self, keys: set[str]) -> None:
        self.stuck += 1
        if self.stuck == 3:
            self._jump(4, "blocked")
            keys.add(self.keys.jump)
        elif self.stuck == 10:
            self._jump(self.long_jump, "blocked, higher")
            keys.add(self.keys.jump)
        elif self.stuck >= 18:
            self.world.note_blocked("too_high")
            self.stuck = 0
            self.back_left = 8
            self.log.append((self.tick, "back off", ""))
