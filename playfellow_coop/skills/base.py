"""The skill contract and the loop that runs one."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Protocol

import numpy as np

Frame = np.ndarray  # height x width x 3, uint8


class Skill(Protocol):
    name: str
    about: str  # one plain sentence the model reads when it chooses
    max_steps: int

    def reset(self) -> None: ...

    def next_key(self, frame: Frame) -> str | None:
        """The key to press now, None to wait one tick, or raise Done when the skill has finished."""


class Done(Exception):
    """A skill has nothing more to do (goal reached, or it cannot continue); the message says why."""


@dataclass
class SkillResult:
    skill: str
    steps: int = 0
    stopped: str = ""  # "done:<why>", "game_over", "step_limit", "key_not_allowed:<key>"
    keys: list[str] = field(default_factory=list)


def as_frame(picture) -> Frame:
    return picture if isinstance(picture, np.ndarray) else np.asarray(picture.convert("RGB"))


def run_skill(skill: Skill, grab: Callable[[], object], press: Callable[[str | None], None], finished: Callable[[], bool],
              allowed: set[str], max_steps: int | None = None, keep_keys: int = 0) -> SkillResult:
    """Run `skill` until it is done: grab a picture, ask the skill for a key, press it. `finished` says the game is over.

    A key the controls card does not allow stops the skill at once (nothing is pressed); the step limit is hard.
    """
    limit = min(max_steps or skill.max_steps, skill.max_steps)
    result = SkillResult(skill.name)
    skill.reset()
    while result.steps < limit:
        if finished():
            result.stopped = "game_over"
            return result
        try:
            key = skill.next_key(as_frame(grab()))
        except Done as why:
            result.stopped = f"done:{why}"
            return result
        if key is not None and key not in allowed:
            result.stopped = f"key_not_allowed:{key}"
            return result
        press(key)
        result.steps += 1
        if keep_keys and len(result.keys) < keep_keys:
            result.keys.append(key or "wait")
    result.stopped = "game_over" if finished() else "step_limit"
    return result
