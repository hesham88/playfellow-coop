"""When to use the power the kart is holding. Rules follow the game's own data and its AI (src/karts/controller/skidding_ai.cpp):
each power has its moment, and a weapon is never thrown just to empty the hand.

`decide` is pure: what is held, what is seen, and the road ahead go in; whether to fire now (and whether to fire backwards) comes
out, with a reason in words. Holding too long wastes the next gift box, so after HOLD_LIMIT a power is used anyway.

  zipper       straight road only: it adds up to 15 m/s for 3.5 s and a tight turn throws that away
  bowling      rolls straight: an opponent lined up ahead and close; never in a bend
  cake         homes in: any opponent ahead in view
  plunger      an opponent close ahead
  swatter      works by itself on karts within 9 m: an opponent very close ahead
  bubblegum    a shield for 10 s: with an opponent close, or to get rid of a bad attachment
  parachute    slows every kart ahead: at once, unless leading
  anchor       hits the leader: at once, unless leading
  rubber_ball   homes on the leader: at once, unless leading
  switch       turns bananas into gift boxes for 5 s: when a banana is in the path
"""
from __future__ import annotations

from dataclasses import dataclass

from playfellow_coop.games.stk.items import Seen

HOLD_LIMIT = 12.0  # seconds before a power is used anyway
MIN_GAP = 1.5  # seconds between shots


@dataclass
class Moment:
    power: str | None
    charges: int
    karts_ahead: list  # Seen entries of kind "kart"; the kart's own look is filtered by items.aim's band
    place: int | None = None  # 1 = leading, None = not read
    bend: float = 0.0  # how much the road turns ahead (radians)
    banana_in_path: bool = False
    attachment: bool = False  # a bomb, anvil or parachute on the kart
    held_for: float = 0.0
    since_last: float = 99.0


def _nearest(karts: list) -> Seen | None:
    return max(karts, key=lambda s: s.y) if karts else None


def decide(m: Moment) -> tuple[bool, bool, str]:
    """(fire now, fire backwards, reason)."""
    if m.power is None or m.since_last < MIN_GAP:
        return False, False, ""
    near = _nearest(m.karts_ahead)
    leading = m.place == 1
    lined_up = near is not None and abs(near.x - 0.5) < 0.08
    close = near is not None and near.y > 0.42
    very_close = near is not None and near.y > 0.55
    p = m.power
    if p == "zipper":
        if m.bend < 0.25:
            return True, False, "straight road: zipper"
        return False, False, ""
    if p == "bowling":
        if lined_up and close and m.bend < 0.5:
            return True, False, "opponent lined up close: bowling ball"
    elif p == "cake":
        if near is not None:
            return True, False, "opponent ahead: cake"
    elif p == "plunger":
        if close and abs(near.x - 0.5) < 0.2:
            return True, False, "opponent close: plunger"
    elif p == "swatter":
        if very_close or m.attachment:
            return True, False, "swatter on the kart beside me" if very_close else "swatter clears the attachment"
    elif p == "bubblegum":
        if very_close or m.attachment:
            return True, False, "bubblegum shield"
    elif p in ("parachute", "anchor", "rubber_ball"):
        if not leading:
            return True, False, f"{p} on the karts ahead"
        return False, False, ""
    elif p == "switch":
        if m.banana_in_path:
            return True, False, "banana ahead: switch turns it into a gift"
    if m.held_for >= HOLD_LIMIT and m.bend < 0.6:
        return True, leading, f"held {p} too long: using it" + (" backwards" if leading else "")
    return False, False, ""
