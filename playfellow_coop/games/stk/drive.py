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

from playfellow_coop.games.stk.track import Track, TrackItem


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


SKID_BONUS_TIME = 1.05  # kart_characteristics.xml: time-till-bonus 1.0 (yellow, +4.5 m/s for 3 s)
SKID_RED_TIME = 3.1  # time-till-bonus 3.0 (red, +6.5 m/s for 4 s); a yellow released while a red runs is thrown away
SKID_MAX_TIME = 7.0  # the longest skid held through one bend
SKID_MIN_SPEED = 10.5  # skid min-speed 10
SKID_BOOST_LENGTH = 3.0  # bonus-time (yellow)
NITRO_OVERLAP = 0.4  # a tap just before a boost fades carries the speed on
MAX_SPEED = 45.0  # m/s: faster than any kart with nitro and a zipper; anything quicker is a misread
PICKUP_RADIUS = 1.1  # item.cpp: an item is taken when the kart's centre passes within sqrt(1.2) m
BANANA_MARGIN = 2.2  # metres kept from a banana's centre (pick-up radius + a metre of minimap error)
LINE_LIMIT = 2.4  # near or in a bend the item line never leaves the centre by more (simulator, 4 Nov)
STRAIGHT_LIMIT = 4.0  # on a straight: reaches a box 4.6 m out (pick-up 1.1 m) on a 10 m road
# kart_characteristics.xml <turn radius>: the kart's tightest circle at a speed, per kart class (metres at m/s)
TURN_RADIUS = {"light": ((0, 2.0), (10, 7.5), (25, 15.0), (45, 30.0)),
               "medium": ((0, 2.3), (10, 8.625), (25, 17.25), (45, 34.5)),
               "heavy": ((0, 2.6), (10, 9.75), (25, 19.5), (45, 39.0))}


def turn_radius(speed: float, kart_class: str = "medium") -> float:
    """The kart's tightest turn at this speed, from the game's data (linear between the table's points)."""
    pts = TURN_RADIUS.get(kart_class, TURN_RADIUS["medium"])
    return float(np.interp(speed, [p[0] for p in pts], [p[1] for p in pts]))


def skid_level(need: float) -> int:
    """During a skid the game steers 0.2, 0.5 or 0.8 of full lock toward the skid side: outward key, no key, inward key
    (skidding.cpp updateSteering). `need` is the share of full lock this bend wants. Returns -1 outward, 0 none, +1 inward."""
    return 1 if need >= 0.65 else -1 if need < 0.35 else 0


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
    nitro_every: float = 1.25  # a tap burns 0.53 s of nitro at least (kart.cpp updateNitro) and lasts 1 s + 2.4 s fade
    kart_class: str = "medium"  # light / medium / heavy (paths.kart_info): turn radius and how much speed a bend allows
    items: list = field(default_factory=list)  # the track's fixed items (track.load_items): the line takes boxes, misses bananas
    held_power: str | None = None  # the power in hand (held.py): a new gift box would REPLACE it (collect mode "new")
    line_offset: float = 0.0  # metres left (+) or right of the centre line the item line wants now
    skid_target: float = SKID_BONUS_TIME
    skid_corner: object = None
    no_steer_until: float = -1.0  # after a skid the game straightens the kart itself: no counter-steer
    _edge_looks: int = 0
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
        self.bends = self.track.corners()
        self.skidded = set()  # (lap, bend) already skidded this lap

    def _s(self, index: int) -> float:
        return float(self._cum[index])

    def bend_at(self, s: float, ahead: float):
        """The first bend that starts within `ahead` metres of s, or the bend s is already in."""
        for c in self.bends:
            if c.s0 <= s <= c.s1:
                return c
            if 0.0 <= (c.s0 - s) % self.lap_length <= ahead:
                return c
        return None

    def road_radius_ahead(self, s: float, metres: float = 45.0) -> float:
        """The tightest bend radius between here and `metres` ahead (infinite on a straight)."""
        r = math.inf
        for c in self.bends:
            if c.s0 <= s <= c.s1 or 0.0 <= (c.s0 - s) % self.lap_length <= metres:
                r = min(r, c.radius)
        return r

    def item_passes(self) -> dict:
        """From the drive log: how close the kart passed each fixed item (an estimate from the minimap, about a metre of noise).
        Counts boxes and cans passed within the pick-up radius, and bananas passed within it (hits, likely)."""
        if not self.items:
            return {}
        ticks = [e for e in self.log if len(e) == 8]
        counts = {"boxes_in_reach": 0, "cans_in_reach": 0, "bananas_close": 0, "item_passes": 0}
        for it in self.items:
            near = [math.hypot(e[1] - it.xz[0], e[2] - it.xz[1]) for e in ticks]
            # each pass: a run of looks within 8 m; its closest look
            run, best = False, 99.0
            for dist in near + [99.0]:
                if dist < 8.0:
                    run, best = True, min(best, dist)
                elif run:
                    counts["item_passes"] += 1
                    if best <= PICKUP_RADIUS + 0.3:
                        key = "bananas_close" if it.kind == "banana" else "boxes_in_reach" if it.kind == "item" else "cans_in_reach"
                        counts[key] += 1
                    run, best = False, 99.0
        return counts

    def plan_line(self, s: float, half_width: float) -> float:
        """Metres left (+) or right of the centre for the next stretch, from the track's fixed items: through gift boxes (when
        no power is in hand: a box replaces it) and nitro cans, clear of bananas by BANANA_MARGIN, smooth, near the centre.
        The kart must pass within 1.1 m of an item to take it, so the line aims at it, not near it."""
        near = [(it, (it.s - s) % self.lap_length) for it in self.items]
        near = [(it, ds) for it, ds in near if 2.0 < ds < 60.0]
        if not near:
            self.line_offset *= 0.9
            return self.line_offset
        # How far from the centre the line may go: Abyss's side boxes sit 3.4-4.6 m out and most cans 2-4 m, and the kart must
        # pass within 1.1 m, so the full reach is needed. In the simulator (4 Nov) wide lines ran off only when they met a
        # bend: on a straight (no bend within 35 m) the line may reach STRAIGHT_LIMIT; near or in a bend it stays at LINE_LIMIT.
        straight = self.road_radius_ahead(s, metres=35.0) == math.inf
        limit = max(0.5, min(STRAIGHT_LIMIT if straight else LINE_LIMIT, half_width - (0.9 if straight else 1.8)))
        ys = np.arange(-limit, limit + 1e-6, 0.25)
        cost = 0.05 * np.abs(ys) + 0.02 * np.abs(ys - self.line_offset)  # near the centre, and a tie goes to where it is
        for it, ds in near:
            weight = 1.0 - ds / 60.0
            if it.kind == "banana":
                cost += 6.0 * weight * np.clip(1.0 - np.abs(ys - it.offset) / BANANA_MARGIN, 0.0, None)
                continue
            value = {"item": 1.0 if self.held_power is None else 0.0, "small-nitro": 1.2, "big-nitro": 3.0, "zipper": 1.5}.get(it.kind, 0.0)
            # x3 (4 Nov, simulator): weaker, the pull back to the centre won even for cans the line could reach
            cost -= 3.0 * value * weight * np.clip(1.0 - np.abs(ys - it.offset) / (PICKUP_RADIUS + 0.4), 0.0, None)
        best = float(ys[int(np.argmin(cost))])
        # move toward the best line gradually (0.4 m a look, 8 m/s sideways at 20 looks a second): no jerks into a weave
        self.line_offset += float(np.clip(best - self.line_offset, -0.4, 0.4))
        return self.line_offset

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
        s_here = self.along(xz, index)
        if self.items:  # the item line from the track's own data: side boxes, cans, never the banana between them
            n = len(self.track.centre)
            j = self.track.nearest(target, hint=index)
            d = self.track.centre[(j + 1) % n] - self.track.centre[j]
            d = d / max(float(np.linalg.norm(d)), 1e-6)
            target = target + np.array([-d[1], d[0]]) * self.plan_line(s_here, self.track.width[j] / 2.0)
        desired = math.atan2(target[1] - xz[1], target[0] - xz[0])
        err = wrap(desired - heading) * self.steer_sign
        # the item line as a lateral error too (4 Nov, simulator: planned +2.4 m, drove -0.6 m - an offset seen 20-30 m ahead is
        # a smaller angle than the straight-road dead band, so the line was never steered to)
        lat_err = (self.line_offset - self.track.lateral(index, xz)) if self.items else 0.0
        if self.items and bend < 0.6:
            err += 0.05 * float(np.clip(lat_err, -4.0, 4.0)) * self.steer_sign
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
        if straight_road and size < 0.12 and abs(lat_err) < 0.8:
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
        # 4 Nov (research from the game's data): a kart only has to slow for a bend tighter than its own turning circle at that
        # speed. Every bend of Antediluvian Abyss (28 m and up) is wider than any kart's circle at top speed (15-19.5 m), so
        # the old table of "safe" speeds threw time away in every bend. Lift only when the road is tighter than the kart.
        road_r = self.road_radius_ahead(s_here)
        kart_r = turn_radius(speed, self.kart_class)
        if road_r < kart_r - 3.0 and speed > 8.0:
            keys.discard(k.accel)
            keys.add(k.brake)
        elif road_r < kart_r or (noted and speed > 18.0) or (size > 1.2 and speed > 8.0):  # noted: where it fell or was rescued before
            keys.discard(k.accel)
        elif self.speed_scale < 1.0 and speed > 26.0 * self.speed_scale:  # the player asked for care
            keys.discard(k.accel)
        # predictive drift (owner: "it didn't learn how to drift"): the game says you can't stop turning while skidding, so
        # decide BEFORE the bend how far it turns, hold skid + the turn key through it, release when lined up with the exit
        # (the boost fires on release); abort if it runs wide
        if self.force_drift and self.skid_dir == 0 and speed > SKID_MIN_SPEED:  # the player said drift: into this bend now
            self.force_drift = False
            self.skid_dir = 1 if err >= 0 else -1
            self.skid_start, self.skid_exit = now, heading + 0.9 * self.skid_dir * self.steer_sign
            self.skid_corner, self.skid_target = None, SKID_BONUS_TIME
        # skids planned from the bends of the map (4 Nov): a bend driven in >= 1.1 s pays yellow, >= 3.3 s red. Enter just
        # before the bend, steer with the game's three skid levels, let go at the bend's end (the bonus fires on release)
        lap = int(self.progress // self.lap_length) if self.lap_length else 0
        if self.skid_dir == 0 and self.skid_enabled and speed > SKID_MIN_SPEED and abs(err) < 0.6 and now >= self.no_steer_until:
            c = self.bend_at(s_here, ahead=2.0)  # at the bend itself: earlier, the kart still points across the chord and cuts in
            centred = abs(self.track.lateral(index, xz)) < self.track.width[index] / 4.0  # a skid from near an edge has no room
            if c is not None and (lap, c.first) not in self.skidded and centred:
                left_in = (c.s1 - s_here) % self.lap_length if not (c.s0 <= s_here <= c.s1) else c.s1 - s_here
                arc_time = left_in / max(speed, 1.0)
                fit = turn_radius(speed, self.kart_class) / max(c.radius, 1.0)  # the share of full lock this bend wants
                # only bends the game's middle skid level (0.5) can follow: in the simulator, skids through wider bends had to
                # hold the outward level all the way and still came out on the inside, 8 m off the line (4 Nov)
                if arc_time >= SKID_BONUS_TIME + 0.05 and 0.35 <= fit <= 0.75:
                    self.skidded.add((lap, c.first))
                    self.skid_dir = c.side * (1 if self.steer_sign > 0 else -1)
                    self.skid_start, self.skid_corner = now, c
                    self.skid_target = SKID_RED_TIME if arc_time >= SKID_RED_TIME + 0.5 else SKID_BONUS_TIME
                    self.skid_exit = heading + c.angle * c.side
                    self.log.append((now, "drift", round(self.progress, 1), f"bend r{c.radius:.0f} {arc_time:.1f}s target {self.skid_target}"))
        if self.skid_dir:
            held_for = now - self.skid_start
            c = self.skid_corner
            earned = held_for >= self.skid_target
            if c is not None:
                in_bend = c.s0 - 3.0 <= s_here <= c.s1  # bends never wrap past the lap line (Track.corners)
                at_end = not in_bend or c.s1 - s_here < max(speed * 0.3, 2.0)
            else:  # a drift the player asked for: let go when lined up with where the road goes
                at_end = wrap(self.skid_exit - heading) * self.steer_sign * self.skid_dir < 0.25
            # at the bend's end take whatever is earned (yellow if red is not reached): a skid can never steer straight, so
            # holding it into the straight for the red runs the kart off the inside (simulator, 4 Nov: 12 m off)
            if at_end and (earned or held_for >= SKID_BONUS_TIME or c is not None and s_here > c.s1):
                earned = True
            near_edge = c is not None and abs(self.track.lateral(index, xz)) > self.track.width[index] / 2.0 - 1.2
            self._edge_looks = self._edge_looks + 1 if near_edge else 0
            edge = self._edge_looks >= 2  # two looks in a row: one look's minimap noise (~0.8 m) is not the edge
            if edge:  # about to leave the road: let go now (a skid cannot straighten), keep whatever is earned
                at_end, earned = True, held_for >= SKID_BONUS_TIME or earned
            if (earned and at_end) or edge or held_for > SKID_MAX_TIME or abs(err) > 1.0 or speed < SKID_MIN_SPEED - 0.5:
                self.skid_dir = 0  # the bend is done (or it runs wide, or too slow): let go, the boost fires
                if not edge:  # a clean release: the game straightens the kart itself, so no counter-steer for 0.2 s
                    self.no_steer_until = now + 0.2
                if held_for >= SKID_BONUS_TIME:
                    self.boost_ends = now + (4.0 if held_for >= SKID_RED_TIME else SKID_BOOST_LENGTH)
                self.log.append((now, "drift end", round(held_for, 2), "red" if held_for >= SKID_RED_TIME else "yellow" if held_for >= SKID_BONUS_TIME else "none"))
            else:
                keys.discard(k.left)
                keys.discard(k.right)
                # three levels: the share of full lock this bend needs = the kart's circle / the bend's radius, plus the
                # pursuit error toward the skid side (running wide: more; cutting in: less)
                need = turn_radius(speed, self.kart_class) / max(c.radius if c is not None else 30.0, 1.0)
                need += 0.35 * err * self.skid_dir
                if c is not None:  # where it is across the road: cutting in (inside > 0) wants less turn, running wide more
                    inside = self.track.lateral(index, xz) * c.side
                    need -= 0.15 * inside
                level = skid_level(need)
                inward = k.left if self.skid_dir > 0 else k.right
                outward = k.right if self.skid_dir > 0 else k.left
                keys |= {k.drift, k.accel}
                if level > 0 or held_for < 0.1:  # the first look turns into the bend so the skid takes its side
                    keys.add(inward)
                elif level < 0:
                    keys.add(outward)
        if now < self.no_steer_until:
            keys.discard(k.left)
            keys.discard(k.right)
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
            keys |= {k.nitro, k.accel}  # nitro only burns while accelerate is held (1.5 source)
        elif straight and now - self.last_nitro > self.nitro_every and now > self.boost_ends - NITRO_OVERLAP:
            self.last_nitro = now  # short taps; during a skid boost it waits for the fade, so the boosts chain
            keys |= {k.nitro, k.accel}  # nitro only burns while accelerate is held (1.5 source)
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
