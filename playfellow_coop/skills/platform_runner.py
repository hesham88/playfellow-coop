"""A genre skill for platformers: run, jump when stuck, jump again when still stuck, attack now and then.

It needs no skill or reader written for one game: the keys come from the game's controls card (a platformer card names a run key, a
jump key and usually an attack key), and the only thing it reads from the picture is whether the picture is still moving. A side-scroller
scrolls while the player runs; a fixed-screen game changes as the player moves. When the picture stops moving while it holds run, the
player is blocked (a wall, a step, an enemy in the way): it jumps; still blocked, it jumps again (many platformers jump higher or double-jump on a
second press); still blocked after that, it backs off a step and tries again. It attacks every few steps, which in many platformers
breaks cages and clears enemies on the way. The model chooses the skill and its direction; the skill plays at local speed.

Gaps: a pit keeps the picture moving, so "blocked" never fires there. The skill therefore also looks ahead, in pixels only. In the
bottom band of the picture, solid ground shows a strong top edge or texture in every column, and a pit shows the same colour down to
the bottom. When the columns under the player (a little left of centre, where side-scrollers keep the player) have ground and the
columns just ahead do not, it jumps once, then keeps running through the jump. Limits: this assumes the camera keeps the player near
the centre and that a pit shows a plain background; a pit over a busy background, or a hazard that looks like ground, is not seen,
and the model should still stop the skill before those."""
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


UNDER, AHEAD = (0.30, 0.48), (0.52, 0.75)  # shares of the width: under the player, and the stretch it reaches in the next moments


def _ground_columns(frame: np.ndarray) -> np.ndarray:
    """True for each column whose bottom band has structure (a ground edge or texture); False where it is one plain colour (a pit)."""
    band = frame[int(frame.shape[0] * 0.6):].astype(np.int16).mean(axis=-1)
    return np.abs(np.diff(band, axis=0)).max(axis=0) > 12 if band.shape[0] > 1 else np.ones(frame.shape[1], dtype=bool)


def gap_ahead(frame: np.ndarray) -> bool:
    """Ground under the player and a pit just ahead (see the module note for the limits)."""
    if frame.ndim != 3 or frame.shape[0] < 8 or frame.shape[1] < 16:
        return False
    ground, w = _ground_columns(frame), frame.shape[1]
    under, ahead = ground[int(w * UNDER[0]):int(w * UNDER[1])], ground[int(w * AHEAD[0]):int(w * AHEAD[1])]
    return bool(under.mean() > 0.8 and (~ahead).mean() > 0.25)


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
        self.gap_cooldown = 0  # steps left before another jump for a gap: one jump per pit, then run through it

    def next_key(self, frame: Frame) -> str | None:
        self.step += 1
        moving = True if self.last is None else _changed(self.last, frame) > self.still
        self.last = frame
        if self.plan:
            return self.plan.pop(0)
        if self.gap_cooldown:
            self.gap_cooldown -= 1
        elif moving and self.keys.get("jump") and gap_ahead(frame):
            self.gap_cooldown = 4
            return self.keys["jump"]
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
