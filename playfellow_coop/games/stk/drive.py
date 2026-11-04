"""The racing pre-skill: drive a SuperTuxKart track from the minimap, 20+ looks a second, no model in the loop.

Each look: where am I (the icon on the minimap, in world metres), which way am I going (my last few positions), where is the
road a little ahead of me (the game's own driveline, `track.py`), and how far must I turn to point there (pure pursuit).
Keys follow from that: accelerate unless the turn is very sharp, steer with a pulse width proportional to the angle (a held
key turns as hard as the kart can, so small corrections are short taps), nitro on straights, fire an item now and then, and
Rescue when the kart has made no progress for a while (the game then sets it back on the road, facing the right way).

`Driver.step` is pure (positions and times in, keys out) and tested offline; `live.py` feeds it real frames.
"""
from __future__ import annotations

import math
from collections import deque
from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.games.stk.track import Track


@dataclass
class Keys:
    accel: str = "up"
    brake: str = "down"
    left: str = "left"
    right: str = "right"
    nitro: str = "n"
    fire: str = "space"
    rescue: str = "backspace"
    drift: str = "v"
    look_back: str = "b"

    def all(self) -> frozenset[str]:
        return frozenset({self.accel, self.brake, self.left, self.right, self.nitro, self.fire, self.rescue, self.drift, self.look_back})


SKID_BONUS_TIME = 1.05  # kart_characteristics.xml: time-till-bonus 1.0
SKID_MAX_TIME = 3.2  # past the top tier (3.0 s) there is nothing more to earn
SKID_BOOST_LENGTH = 3.0  # bonus-time
NITRO_OVERLAP = 0.4  # a tap just before a boost fades carries the speed on
MAX_SPEED = 45.0  # m/s: faster than any kart with nitro and a zipper; anything quicker is a misread


def wrap(angle: float) -> float:
    return (angle + math.pi) % (2 * math.pi) - math.pi


@dataclass
class Driver:
    track: Track
    keys: Keys = field(default_factory=Keys)
    steer_sign: float = 1.0  # +1: the left key turns counter-clockwise on the minimap (learned by `learn_steer_sign`)
    full_lock: float = 0.50  # radians of error at which steering is held all the time (tuned in the simulator)
    dead_band: float = 0.07
    stuck_after: float = 2.5  # seconds with no progress along the driveline before Rescue
    nitro_every: float = 2.0
    fire_every: float = 1.5
    history: deque = field(default_factory=lambda: deque(maxlen=40))
    index: int | None = None
    progress: float = 0.0  # metres along the driveline since the start, laps included
    best_progress: float = 0.0
    best_at: float = 0.0
    last_rescue: float = -99.0
    last_nitro: float = -99.0
    last_fire: float = -99.0
    duty: float = 0.0
    log: list = field(default_factory=list)
    # what the on-screen instructions asked for, with their timing (see instructions.py and `apply`)
    skid_until: float = -1.0
    trouble_watch_until: float = -1.0
    nitro_on_straight: bool = False
    slow_since: float | None = None
    blind_limit: float = 0.8  # seconds of dead reckoning when the icon is not seen (longer while the map is up but the icon is hidden)
    _last_s: float | None = None
    reverse_until: float = -1.0
    last_reverse: float = -99.0
    reverse_steer: str | None = None
    auto_fire: bool = True  # fire on a timer when nothing aims for us; the live loop turns it off when SAM sees opponents
    skid_enabled: bool = True  # predictive drift (decided before the bend); every drift is logged for the race notes
    skid_dir: int = 0  # +1 skidding left, -1 right, 0 not skidding
    skid_start: float = -99.0
    skid_exit: float = 0.0
    notes: tuple = ()  # driveline points where earlier races got into trouble (catalogue.note_race)
    kd: float = 0.20  # damping time (s): tuned in the simulator (sim.py) after the 3 Nov swinging
    speed_gain: float = 0.10  # how much gentler per m/s over 14 (tuned in the simulator)
    _err_s: float | None = None
    _err_t: float | None = None
    grace_until: float = -1.0
    _still_since: float | None = None
    _last_kick: float = -99.0
    boost_ends: float = -1.0
    item_cap: float = 0.18  # live tuning (the player's tips): how hard items pull, obstacles push, bends slow
    dodge_cap: float = 0.22
    speed_scale: float = 1.0
    dodging: bool = False  # the item bias is a push away from an obstacle (stronger, allowed in bends)
    forced_bias: float = 0.0  # the player's direct commands (widget nudges): left/right, straight, brake, drift
    forced_until: float = -1.0
    hold_straight_until: float = -1.0
    brake_until: float = -1.0
    force_drift: bool = False
    item_bias: float = 0.0  # radians added to the steering error by the item hunt / obstacle push (items.py), + = left
    taps: set = field(default_factory=set)
    obeyed: list = field(default_factory=list)
    _seg: np.ndarray | None = None
    _cum: np.ndarray | None = None

    def __post_init__(self):
        c = self.track.centre
        self._seg = np.linalg.norm(np.roll(c, -1, axis=0) - c, axis=1)
        self._cum = np.concatenate([[0.0], np.cumsum(self._seg)[:-1]])
        self.lap_length = float(self._seg.sum())

    def apply(self, inst, now: float) -> str:
        """Take on an instruction read from the screen, at the timing it asks for. Returns what the buddy will do, in words."""
        k, a, t = self.keys, inst.action, inst.timing
        if a == "rescue":
            self.trouble_watch_until = now + 8.0  # the game says "when you're in trouble": rescue as soon as the kart is stalled
            plan = "watching for trouble: Rescue the moment I stall"
        elif a == "drift":
            self.skid_until = now + 40.0
            plan = "skidding through the sharp turns from now on"
        elif a == "nitro" and t in ("next_straight", "next_turn", "ongoing", "none"):
            self.nitro_on_straight = True
            plan = "saving nitro for the next straight"
        elif a == "nitro":
            self.taps.add(k.nitro)
            plan = "nitro now"
        elif a == "fire":
            self.taps.add(k.fire)
            plan = "using my item now"
        elif a == "lookBack":
            self.taps.add(k.look_back)
            plan = "looking back"
        else:
            plan = "noted"
        self.obeyed.append((round(now, 2), inst.text, a, t, plan))
        return plan

    def heading(self, now: float) -> tuple[float | None, float]:
        """Heading (radians on the minimap, counter-clockwise from +X) and speed (m/s), from a straight-line fit through the
        positions of the last half second. A fit through ~10 looks is far steadier than two end points: the minimap is small,
        so one look's position jitters by about a metre, which made the kart weave on straights (owner, 3 Nov)."""
        pts = [(t, p) for t, p in self.history if now - t <= 0.50]
        if len(pts) < 3:
            return None, 0.0
        ts = np.array([t for t, _ in pts])
        if ts[-1] - ts[0] <= 0.05:
            return None, 0.0
        ps = np.array([p for _, p in pts])
        tc = ts - ts.mean()
        v = (tc[:, None] * (ps - ps.mean(axis=0))).sum(axis=0) / float((tc ** 2).sum())  # least-squares velocity
        speed = float(np.linalg.norm(v))
        if speed > MAX_SPEED:  # a jump no kart can make: a misread, not motion
            return None, 0.0
        return (math.atan2(v[1], v[0]) if speed > 1.5 else None), speed

    def predict(self, now: float) -> np.ndarray | None:
        """Where the kart should be now, from its last sighting and velocity (None before the first sighting)."""
        if not self.history:
            return None
        t_last, p_last = self.history[-1]
        heading, speed = self.heading(t_last)
        if heading is None:
            return p_last
        return p_last + min(speed, MAX_SPEED) * min(now - t_last, 1.0) * np.array([math.cos(heading), math.sin(heading)])

    def tangent(self, index: int) -> float:
        n = len(self.track.centre)
        d = self.track.centre[(index + 2) % n] - self.track.centre[index]
        return math.atan2(d[1], d[0])

    def curvature_ahead(self, index: int, metres: float = 30.0) -> float:
        """How much the road turns over the next `metres` (radians, absolute)."""
        a = self.tangent(index)
        b = math.atan2(*(lambda d: (d[1], d[0]))(self.track.ahead(index, metres) - self.track.ahead(index, metres - 6.0)))
        return abs(wrap(b - a))

    def along(self, xz: np.ndarray, index: int) -> float:
        """Metres along the driveline from its start to the kart (the kart projected onto the segment it is on), 0..lap length."""
        n = len(self.track.centre)
        a, b = self.track.centre[index], self.track.centre[(index + 1) % n]
        seg = self._seg[index]
        t = float(np.dot(xz - a, (b - a) / seg)) if seg > 0 else 0.0
        return (self._cum[index] + min(max(t, -self._seg[index - 1]), seg)) % self.lap_length

    def _update_progress(self, index: int, now: float, xz: np.ndarray | None = None) -> None:
        """Progress is continuous (metres, laps included): a kart moving along a long straight counts, not only one crossing
        from one driveline point to the next."""
        s = self.along(xz, index) if xz is not None else float(self._cum[index])
        if self.index is not None and self._last_s is not None:
            delta = (s - self._last_s + self.lap_length / 2) % self.lap_length - self.lap_length / 2
            self.progress += delta
        self._last_s = s
        self.index = index
        if now - self.last_rescue < 2.0:  # the kart is landing where Rescue put it: measure progress from there
            self.best_progress, self.best_at = self.progress, now
        if self.progress > self.best_progress + 1.0:
            self.best_progress, self.best_at = self.progress, now

    def step(self, now: float, xz: np.ndarray | None, racing: bool = True) -> set[str]:
        """The keys to hold for the next tick."""
        k = self.keys
        if xz is None:  # icon not seen this look (an item flash, a banner over the map): dead-reckon for up to 0.8 s
            if racing and self.index is not None and now - self.best_at > self.stuck_after + 1.0 and now - self.last_rescue > 4.0:
                return self._rescue(now, "lost and going nowhere")
            if not racing or not self.history or now - self.history[-1][0] > self.blind_limit:
                return {k.accel} if racing else set()
            heading, speed = self.heading(self.history[-1][0])
            if heading is None:
                return {k.accel}
            t_last, p_last = self.history[-1]
            xz = p_last + speed * (now - t_last) * np.array([math.cos(heading), math.sin(heading)])
            return self._steer(now, xz, heading, speed, observed=False)
        xz = np.asarray(xz, dtype=float)
        self.history.append((now, xz))
        index = self.track.nearest(xz, hint=self.index)
        if self.index is None:
            self.best_at = now
        self._update_progress(index, now, xz)
        if not racing:
            return set()
        heading, speed = self.heading(now)
        if now < self.reverse_until:  # backing away from a wall: brake held (reverse), the wheel turned the other way
            return {k.brake, self.reverse_steer} if self.reverse_steer else {k.brake}
        if speed < 2.0:
            self.slow_since = self.slow_since if self.slow_since is not None else now
        else:
            self.slow_since = None
        stuck_after = 1.0 if now < self.trouble_watch_until else self.stuck_after  # an instruction said: in trouble, rescue
        stalled = self.slow_since is not None and now - self.slow_since > min(stuck_after, 1.2)  # stopped against something
        going_nowhere = now - self.best_at > 6.0  # moving, but not along the road (wrong way, circling)
        if now < self.grace_until:  # just got away from the grid: nothing to recover from yet
            stalled = going_nowhere = False
        told_to_rescue = now < self.trouble_watch_until  # the screen said "in trouble, press Rescue": do exactly that
        if stalled and not told_to_rescue and now - self.last_reverse > 6.0 and now - self.last_rescue > 3.0:
            return self._reverse(now, xz, index)  # first try what a driver does: back off the wall, then go again
        if (stalled or going_nowhere) and now - self.last_rescue > 4.0:
            return self._rescue(now, "stalled again after reversing" if stalled else "no progress")
        if heading is None:
            heading = self.tangent(index)
        return self._steer(now, xz, heading, speed)

    def _reverse(self, now: float, xz: np.ndarray, index: int) -> set[str]:
        """Back off for 0.9 s. Reversing with the wheel turned swings the nose the OTHER way, so to point the nose toward the
        road ahead the wheel is turned away from it. If the kart stalls again within 6 s, Rescue follows."""
        k = self.keys
        target = self.track.ahead(index, 12.0)
        facing = self.history[-1][1] - self.history[0][1] if len(self.history) > 1 else None
        heading = math.atan2(facing[1], facing[0]) if facing is not None and np.linalg.norm(facing) > 0.5 else self.tangent(index)
        err = wrap(math.atan2(target[1] - xz[1], target[0] - xz[0]) - heading) * self.steer_sign
        self.reverse_steer = (k.right if err > 0 else k.left) if abs(err) > 0.15 else None
        self.reverse_until, self.last_reverse = now + 0.9, now
        self.slow_since = None
        self.log.append((now, "reverse", round(self.progress, 1), "stalled"))
        return {k.brake, self.reverse_steer} if self.reverse_steer else {k.brake}

    def kick(self, now: float, speed: float, keys: set[str]) -> set[str]:
        """A throttle the game is ignoring gets pressed again. The game zeroes the throttle during a start penalty and a held
        key sends no new event, so on 4 Nov the kart sat 9 s with Up "held". Standing still with the throttle on for 0.8 s:
        let go for one look, so the next look is a fresh key press; repeated every 0.6 s until the kart moves."""
        if self.keys.accel not in keys or speed >= 1.0:
            self._still_since = None
            return keys
        if self._still_since is None:
            self._still_since = now
        elif now - self._still_since >= 0.8 and now - self._last_kick >= 0.6:
            self._last_kick = now
            return set(keys) - {self.keys.accel}
        return keys

    def begin_race(self, now: float, grace: float = 3.0) -> None:
        """Racing starts now: the wait on the grid is not 'no progress', and a kart still getting away is not stuck."""
        self.best_at = now
        self.best_progress = self.progress
        self.slow_since = None
        self.grace_until = now + grace

    def _rescue(self, now: float, why: str) -> set[str]:
        """Let the game put the kart back on the road. Rescue sets it back a little along the road, so the progress mark is
        reset to wherever it lands: otherwise the kart could never beat its old best in time and would be rescued again and again."""
        self.last_rescue = self.best_at = now
        self.best_progress = self.progress
        self.slow_since = None
        self.history.clear()
        self.log.append((now, "rescue", round(self.progress, 1), why))
        return {self.keys.rescue}

    def _steer(self, now: float, xz: np.ndarray, heading: float, speed: float, observed: bool = True) -> set[str]:
        k = self.keys
        index = self.track.nearest(xz, hint=self.index)
        # read the road ahead: how hard is the next bend (25-45 m away, judged from the game's own driveline)
        bend = self.curvature_ahead(index, metres=40.0)
        look = min(max(10.0 + 0.75 * speed, 10.0), 32.0)  # look further at speed: smooth lines, no over-correcting
        if bend > 0.9:
            look = min(look, 14.0 + 0.3 * speed)  # a sharp bend is coming: aim nearer, turn in early
        n_pts = len(self.track.centre)
        noted = bool(self.notes) and any(((s - index) % n_pts) in range(4, 15) for s in self.notes)
        if noted:  # its own notes from earlier races: a trouble spot is coming up - nearer aim, wider line (below), easy on the gas
            look = min(look, 12.0 + 0.3 * speed)
        target = self.track.ahead(index, look)
        if bend > 0.6 or noted:
            # aiming at the centre line cuts the corner: the winning race stalled 5 times on INNER walls (3 Nov). Shift the aim
            # point toward the outside of the bend by a third of the road's half width, so the kart runs wide, not into the wall.
            n = len(self.track.centre)
            j = self.track.nearest(target, hint=index)
            d = self.track.centre[(j + 1) % n] - self.track.centre[j]
            d = d / max(float(np.linalg.norm(d)), 1e-6)
            left_normal = np.array([-d[1], d[0]])  # counter-clockwise from the road direction
            turn = wrap(math.atan2(d[1], d[0]) - self.tangent(index))  # > 0: the road bends anti-clockwise (inside on the left)
            outside = -left_normal if turn > 0 else left_normal
            target = target + outside * self.track.width[j] * (0.15 if noted else 0.10 * min(1.0, bend / 1.2))
        desired = math.atan2(target[1] - xz[1], target[0] - xz[0])
        err = wrap(desired - heading) * self.steer_sign
        if self.item_bias and self.dodging and abs(err) < 0.45 and bend < 1.2:
            err += float(np.clip(self.item_bias, -self.dodge_cap, self.dodge_cap))  # a banana or crate in the path: dodging first
        elif self.item_bias and abs(err) < 0.35 and bend < 0.9:
            # items only on gentle road, and gently (owner 3 Nov: the kart swung and hit the sides)
            err += float(np.clip(self.item_bias, -self.item_cap, self.item_cap))
        # damping (3 Nov: it swung at speed): the heading is seen ~0.25 s late, so steer on where the error is GOING, not only
        # where it is - an error already closing fast needs the key released before it overshoots
        if self.kd > 0.0:
            smooth = err if self._err_s is None else 0.5 * self._err_s + 0.5 * err
            rate = 0.0 if self._err_t is None or now - self._err_t <= 0 else (smooth - self._err_s) / (now - self._err_t)
            self._err_s, self._err_t = smooth, now
            err = err + self.kd * float(np.clip(rate, -4.0, 4.0))
        if now < self.forced_until:
            err = self.forced_bias * 2.0  # the player said left/right: turn that way now
        keys = {k.accel}
        size = abs(err)
        straight_road = bend < 0.30 and not self.item_bias
        if straight_road and size < 0.12:
            self.duty = 0.0  # a straight road and only a little off: hold the wheel still (no weaving)
        elif size > self.dead_band:
            lock = self.full_lock * (1.0 + self.speed_gain * max(0.0, speed - 14.0))  # gentler corrections the faster it goes
            want = min(1.0, (size - self.dead_band) / (lock - self.dead_band))
            self.duty += want
            if self.duty >= 1.0:  # pulse width: a held key every tick at full lock, every other tick at half, ...
                self.duty -= 1.0
                keys.add(k.left if err > 0 else k.right)
        else:
            self.duty = 0.0
        # speed for the bend ahead (owner 3 Nov: it fell off strong curves with no walls): the sharper the bend 40 m ahead,
        # the slower it must arrive; over that speed it lifts, well over it it brakes a moment
        # (owner 3 Nov, later: "it slows down in the curves way too much"): back up a step, brake only when far over
        safe = (26.0 if bend < 0.5 else 22.0 if bend < 0.9 else 17.0 if bend < 1.4 else 13.0) * self.speed_scale
        if speed > safe + 8.0:
            keys.discard(k.accel)
            keys.add(k.brake)
        elif speed > safe or (noted and speed > safe - 2.0) or (size > 1.2 and speed > 8.0):
            keys.discard(k.accel)
        # predictive drift (owner: "it didn't learn how to drift"): the game says you can't stop turning while skidding, so
        # decide BEFORE the bend how far it turns, hold skid + the turn key through it, release when lined up with the exit
        # (the boost fires on release); abort if it runs wide
        if self.force_drift and self.skid_dir == 0 and speed > 8.0:  # the player said drift: into this bend now
            self.force_drift = False
            self.skid_dir = 1 if err >= 0 else -1
            self.skid_start, self.skid_exit = now, heading + 0.9 * self.skid_dir * self.steer_sign
        if self.skid_dir == 0 and self.skid_enabled and now - self.skid_start > 1.5 and speed > 13.0 and abs(err) < 0.6:
            n_pts = len(self.track.centre)
            exit_dir = self.track.ahead(index, 30.0) - self.track.ahead(index, 24.0)
            exit_heading = math.atan2(exit_dir[1], exit_dir[0])
            turn = wrap(exit_heading - heading) * self.steer_sign
            entry = self.curvature_ahead(index, metres=14.0)
            if abs(turn) > 0.9 and entry > 0.45:
                self.skid_dir, self.skid_start, self.skid_exit = (1 if turn > 0 else -1), now, exit_heading
                self.log.append((now, "drift", round(self.progress, 1), f"turn {turn:.2f} rad"))
        if self.skid_dir:
            held_for = now - self.skid_start
            remaining = wrap(self.skid_exit - heading) * self.steer_sign * self.skid_dir
            earned = held_for >= SKID_BONUS_TIME  # game data: 1 s of skid earns +4.5 m/s for 3 s; released earlier it earns nothing
            if (earned and remaining < 0.25) or held_for > SKID_MAX_TIME or abs(err) > 1.0 or speed < 8.0:
                self.skid_dir = 0  # lined up with the exit (or running wide): let go, the boost fires
                if earned:
                    self.boost_ends = now + SKID_BOOST_LENGTH
            else:
                keys.discard(k.left)
                keys.discard(k.right)
                # a skid cannot stop turning, only turn less: the opposite key widens the arc when it is turning too far
                wide = remaining < 0.35
                turn_left = (self.skid_dir > 0) != wide
                keys |= {k.drift, k.accel, k.left if turn_left else k.right}
        if now < self.hold_straight_until:  # the player said straight
            keys.discard(k.left)
            keys.discard(k.right)
        if now < self.brake_until:  # the player said brake
            keys.discard(k.accel)
            keys.add(k.brake)
        straight = size < 0.12 and straight_road
        if straight and self.nitro_on_straight:
            self.nitro_on_straight = False
            self.last_nitro = now
            keys.add(k.nitro)
        elif straight and now - self.last_nitro > self.nitro_every and now > self.boost_ends - NITRO_OVERLAP:
            self.last_nitro = now  # short taps; during a skid boost it waits for the fade, so the boosts chain
            keys.add(k.nitro)
        if self.taps:
            keys |= self.taps
            self.taps = set()
        if self.auto_fire and size < 0.25 and now - self.last_fire > self.fire_every:
            self.last_fire = now
            keys.add(k.fire)
        self.log.append((round(now, 2), round(float(xz[0]), 1), round(float(xz[1]), 1), index, round(err, 2), round(speed, 1), sorted(keys), "seen" if observed else "dead-reckoned"))
        return self.kick(now, speed, keys)


def learn_steer_sign(headings_before: list[float], headings_after: list[float]) -> float:
    """After holding the LEFT key for a moment: +1 if the heading turned counter-clockwise on the minimap, else -1."""
    a = math.atan2(np.mean(np.sin(headings_before)), np.mean(np.cos(headings_before)))
    b = math.atan2(np.mean(np.sin(headings_after)), np.mean(np.cos(headings_after)))
    return 1.0 if wrap(b - a) > 0 else -1.0
