"""A genre skill for platformers: run, jump when stuck, jump again when still stuck, attack now and then.

It needs no skill or reader written for one game: the keys come from the game's controls card (a platformer card names a run key, a
jump key and usually an attack key), and the only thing it reads from the picture is whether the picture is still moving. A side-scroller
scrolls while the player runs; a fixed-screen game changes as the player moves. When the picture stops moving while it holds run, the
player is blocked (a wall, a step, an enemy in the way): it jumps; still blocked, it jumps again (many platformers jump higher or double-jump on a
second press); still blocked after that, it backs off a step and tries again. It attacks every few steps, which in many platformers
breaks cages and clears enemies on the way. The model chooses the skill and its direction; the skill plays at local speed.

Not handled: a gap or a hazard the player can walk into keeps the picture moving, so "blocked" never fires there; looking ahead for
gaps is the next step, and the model should stop the skill before one."""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Frame

JUMP_KEYS = ("space", "up", "w", "z", "x")
ATTACK_KEYS = ("s", "x", "c", "j", "ctrl", "z")


def keys_from_card(card, direction: str = "right") -> dict | None:
    """The run, jump and attack keys a platformer card allows. None when the card is not a platformer or has no key for running that way."""
    if str(getattr(card, "genre", "")).lower() != "platformer":
        return None
    keys = {k for a in card.actions.values() for k in getattr(a, "keys", ())}
    if direction not in keys:
        return None
    jump = next((k for k in JUMP_KEYS if k in keys and k != direction), None)
    attack = next((k for k in ATTACK_KEYS if k in keys and k not in (jump, direction)), None)
    return {"run": direction, "jump": jump, "attack": attack, "back": "left" if direction == "right" else "right"}


def _changed(a: np.ndarray, b: np.ndarray) -> float:
    if a.shape != b.shape:
        return 1.0
    small_a, small_b = a[::4, ::4].astype(np.int16), b[::4, ::4].astype(np.int16)
    return float((np.abs(small_a - small_b).max(axis=-1) > 18).mean())


class RunAndJump:
    name = "run_and_jump"
    about = ("Runs in one direction on its own, jumps when blocked, jumps again if still blocked, and attacks every few steps; "
             "use it to cross a stretch of level fast. It stops after a few seconds so you can look again.")
    realtime = True

    def __init__(self, keys: dict, attack_every: int = 6, still: float = 0.004):
        self.keys, self.attack_every, self.still = keys, attack_every, still
        self.reset()

    def reset(self) -> None:
        self.last: np.ndarray | None = None
        self.step = 0
        self.stuck = 0
        self.plan: list[str | None] = []  # keys already decided (a double jump, a back-off), played one per step

    def next_key(self, frame: Frame) -> str | None:
        self.step += 1
        moving = True if self.last is None else _changed(self.last, frame) > self.still
        self.last = frame
        if self.plan:
            return self.plan.pop(0)
        if not moving and self.keys.get("jump"):
            self.stuck += 1
            if self.stuck == 1:
                return self.keys["jump"]
            if self.stuck == 2:  # still blocked: jump again at once (a higher or double jump), then run on
                self.plan = [self.keys["jump"], self.keys["run"]]
                return self.keys["run"]
            self.stuck = 0  # blocked through two jumps: back off and try again
            back = self.keys.get("back")
            self.plan = [back, back, self.keys["run"], self.keys["jump"]] if back else [self.keys["jump"]]
            return self.plan.pop(0)
        self.stuck = 0
        if self.keys.get("attack") and self.attack_every and self.step % self.attack_every == 0:
            return self.keys["attack"]
        return self.keys["run"]
