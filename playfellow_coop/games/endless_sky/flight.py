"""The flying and fighting decisions: pure logic on what the HUD shows, one tick at a time.

Skills in here (each tested in tests/test_endless_sky.py): focus fire on one target, close to weapon range then hold it, keep the guns on the
lead point with the game's auto steer, hold fire out of range, ease off the guns before overheating or running out of energy, break off and
land to recover when hull gets low, and the rule the owner asked for after the 4 Nov drift: the ship is never left coasting with no plan.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field

from playfellow_coop.games.endless_sky.hud import Hud

BEAM_RANGE = 300.0  # Beam Laser: velocity 300 x lifetime 1 (data/human/weapons.txt)
BLASTER_RANGE = 510.0  # Energy Blaster (outfitter panel, 4 Nov)


@dataclass
class Rules:
    weapon_range: float = BEAM_RANGE
    close_to: float = 0.65  # thrust until inside this share of the range
    retreat_hull: float = 0.62  # break off below this: a Sparrow is disabled at 134 of 300 hull (45%), and a disabled ship cannot land
    heat_limit: float = 0.85
    low_energy: float = 0.08
    acceleration: float = 420.0  # Sparrow: thrust 21.75 / mass 186 per frame squared, at 60 frames a second, in world units a second squared
    brake_share: float = 0.5  # a turn-around comes before braking, so plan on half the distance
    creep: float = 90.0
    top_approach: float = 650.0
    top_drift: float = 420.0
    brake_inside: float = 900.0


@dataclass
class Order:
    keys: set[str] = field(default_factory=set)  # keys held this tick
    taps: list[str] = field(default_factory=list)  # keys tapped once
    say: str = ""
    retreat: bool = False


def approach_limit(distance: float, rules: "Rules") -> float:
    """The closing speed that can still be braked away before the guns' range: v = sqrt(2 a d), never less than a slow creep."""
    margin = max(distance - rules.weapon_range * rules.close_to, 0.0)
    return min(max(math.sqrt(2.0 * rules.acceleration * margin * rules.brake_share), rules.creep), rules.top_approach)


def fight_tick(hud: Hud, card: dict[str, str], rules: Rules = Rules(), closing: float = 0.0, drift: float = 0.0) -> Order:
    """One tick of a dogfight. `closing` is how fast the range is falling (world units a second, negative when it grows), `drift` the ship's own
    speed as seen in the starfield (0 when unknown). Thrust only while the approach can still be braked; too fast near the target: brake."""
    if hud.hull < rules.retreat_hull and hud.shields < 0.05:
        return Order(taps=[card["land"]], say="hull is low: breaking off to land and repair", retreat=True)
    near = hud.nearest_hostile
    order = Order()
    if near is None and not hud.has_target:
        return order
    if not hud.has_target or not hud.of("target"):
        order.taps.append(card["hostile"])
    distance = near.distance if near else rules.weapon_range * 2
    in_range = distance <= rules.weapon_range * 1.15
    if in_range and hud.heat < rules.heat_limit and hud.energy > rules.low_energy:
        order.keys.add(card["fire"])
    limit = approach_limit(distance, rules)
    overspeed = closing > limit * 1.35 or (distance < rules.brake_inside and drift > rules.top_drift)
    if overspeed and not in_range and "reverse" in card:
        order.keys.add(card["reverse"])  # turns the tail to the direction of travel and thrusts: the game's own way to shed speed
        return order
    order.keys.add(card["autosteer"])
    if distance > rules.weapon_range and closing < limit and drift < rules.top_drift * 1.5:  # inside gun range: stop adding speed, let the guns work
        order.keys.add(card["thrust"])
    return order


def idle_plan(has_destination: bool, port_here: bool) -> str:
    """What to do when nothing else is going on in flight. Never 'nothing': drifting is how a ship gets lost."""
    if has_destination:
        return "jump"
    if port_here:
        return "land"
    return "map"


def refit_plan(credits: int, lasers: int = 2, blasters_have: int = 0, sell_each: int = 29000, buy_each: int = 16000, ports: int = 4, weapon_space: int = 25, used_by_others: int = 0) -> int:
    """How many Energy Blasters to fit after selling the lasers: as many as the gun ports, the weapon capacity (5 each) and the money allow."""
    money = credits + lasers * sell_each
    by_space = (weapon_space - used_by_others) // 5
    return max(min(ports, by_space, blasters_have + money // buy_each), blasters_have)


class RangeRate:
    """How fast the range to the target is falling, smoothed over about a second: the radar is coarse (one pixel is 40 world units)."""

    def __init__(self, window: float = 1.0):
        self.window = window
        self.samples: list[tuple[float, float]] = []

    def update(self, now: float, distance: float | None) -> float:
        if distance is None:
            self.samples.clear()
            return 0.0
        self.samples.append((now, distance))
        self.samples = [s for s in self.samples if now - s[0] <= self.window]
        then, old = self.samples[0]
        return (old - distance) / (now - then) if now - then > 0.25 else 0.0


#: what a refitted Sparrow (four Energy Blasters) can beat one on one, from data/human/ships.txt. A stock one (two Beam Lasers, range 300) lost to a Wasp
#: (1500 shields, 500 hull, 2 Energy Blasters, Sidewinder pod) twice on 4 Nov. "Very Tiny" bounties are these three models.
BEATABLE = ("Scrapper", "Sparrow", "Wasp")  # with the refit: 212 shield and 132 hull damage a second at range 510, against a Wasp's two blasters and a missile pod


def job_is_fair(ships: list[str], jumps: int, max_jumps: int = 2) -> str:
    """Why a bounty should be left alone, or '' when it is a fair fight in reach: the tank holds three jumps, and one stays in reserve."""
    if not ships:
        return "the save names no target"
    for ship in ships:
        if not ship.startswith(BEATABLE):
            return f"a {ship} out-guns this ship"
    if jumps > max_jumps:
        return f"{jumps} jumps away, past the fuel reserve"
    return ""


def bounty_paid(text: str, credits_before: int | None, credits_after: int | None) -> bool:
    """Paid means the game's own message that the target is eliminated, or more money in the save. HUD words like 'credits' and 'Bounty' prove nothing:
    on 4 Nov they matched on the screen of a destroyed ship."""
    if credits_before is not None and credits_after is not None and credits_after >= credits_before + 5000:
        return True
    low = text.lower()
    return "has been eliminated" in low and "credits" in low


def destroyed(text: str) -> bool:
    low = text.lower()
    return "has been destroyed" in low and ("your " in low)
