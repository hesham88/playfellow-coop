"""Hold timing and opposite-direction cleaning: the physics of getting an input into a game (research R1 section 3.6 and section 2.4, R4 section 7.4).

A game polls the keyboard once per rendered frame. A press that starts and ends between two polls is never seen, and many games need an input held across two polls before they treat it as an
intentional action. If an input lasts `hold` ms and the game polls every `frame` ms at a random phase:

    P(seen by at least one poll)       = min(1, hold / frame)
    P(held across two consecutive polls) = max(0, min(1, hold / frame - 1))

so a 5 ms tap at 60 fps (16.7 ms per frame) is dropped two times in three, and 35 to 50 ms registers every time. `ENVELOPES` are the standard holds per kind of action. `SocdCleaner` removes
Simultaneous Opposite Cardinal Directions (left and right together) in one of the three ways game communities use.
"""
from __future__ import annotations

from dataclasses import dataclass

POLL_FPS_DEFAULT = 60.0


def frame_ms(fps: float) -> float:
    if fps <= 0:
        raise ValueError("fps must be positive")
    return 1000.0 / fps


def seen_probability(hold_ms: float, fps: float = POLL_FPS_DEFAULT) -> float:
    """The chance that an input held for `hold_ms` is seen by at least one poll of a game running at `fps`."""
    return max(0.0, min(1.0, hold_ms / frame_ms(fps)))


def latch_probability(hold_ms: float, fps: float = POLL_FPS_DEFAULT) -> float:
    """The chance that it is held across at least two consecutive polls (what many state machines need to start a movement or an attack)."""
    return max(0.0, min(1.0, hold_ms / frame_ms(fps) - 1.0))


def minimum_hold_ms(fps: float = POLL_FPS_DEFAULT, polls: int = 2, margin_ms: float = 1.0) -> float:
    """The shortest hold that is certain to span `polls` polls: polls * frame period (plus a small margin for timer error)."""
    return polls * frame_ms(fps) + margin_ms


@dataclass(frozen=True)
class Envelope:
    hold_min_ms: float
    hold_max_ms: float
    release_gap_ms: float
    why: str


ENVELOPES = {
    "tap": Envelope(35, 50, 25, "a discrete press (fire, confirm, menu click, interact): 2 to 3 frames at 60 fps, a gap so rapid fire has an unpressed frame between taps"),
    "short_hop": Envelope(45, 45, 35, "a short jump or dodge: the jump impulse is applied for the frames the key stays down"),
    "full_jump": Envelope(120, 180, 35, "a full-height jump: held to the apex"),
    "move_chunk": Envelope(200, 200, 0, "continuous movement for one model step; the key stays down across chunks (no release between them) so the character does not stutter"),
    "drag": Envelope(33, 200, 16.7, "a mouse drag or camera move, sub-stepped every 8.33 ms; a settle delay after the button goes up"),
}


def hold_for(kind: str, fps: float = POLL_FPS_DEFAULT, long: bool = False) -> float:
    """The hold to use for an action kind: its envelope's minimum (or maximum with `long`), and for a tap never below the two-poll minimum at this frame rate (a 30 fps game needs a
    longer tap than a 120 fps one)."""
    env = ENVELOPES[kind]
    hold = env.hold_max_ms if long else env.hold_min_ms
    if kind == "tap":
        hold = max(hold, minimum_hold_ms(fps))
    return hold


# ---- opposite directions ------------------------------------------------------------------------------------------------------------
PAIRS = (("left", "right"), ("up", "down"), ("a", "d"), ("w", "s"))
SOCD_MODES = ("neutral", "hitbox", "last_input")


class SocdCleaner:
    """neutral: left+right = nothing, up+down = nothing (the safe default for navigation). hitbox: left+right = nothing, up+down = up (platformers, fighters). last_input: the most recently
    pressed of the two wins (counter-strafing in shooters)."""

    def __init__(self, mode: str = "neutral"):
        if mode not in SOCD_MODES:
            raise ValueError(f"mode is one of {SOCD_MODES}")
        self.mode = mode
        self._order: list[str] = []  # keys in the order they went down

    def clean(self, held: set[str]) -> set[str]:
        """The keys to actually hold, given the keys the model wants held now. Call once per update; it remembers press order for the last-input mode."""
        held = {k.lower() for k in held}
        self._order = [k for k in self._order if k in held] + [k for k in sorted(held) if k not in self._order]
        out = set(held)
        for low, high in PAIRS:
            if low in held and high in held:
                if self.mode == "neutral":
                    out -= {low, high}
                elif self.mode == "hitbox":
                    if (low, high) in (("left", "right"), ("a", "d")):
                        out -= {low, high}
                    else:
                        out -= {"down" if low == "up" else "s"}  # up + down -> up (w + s -> w)
                else:
                    later = low if self._order.index(low) > self._order.index(high) else high
                    out -= {low if later == high else high}
        return out
