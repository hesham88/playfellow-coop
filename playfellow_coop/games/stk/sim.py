"""A small kart simulator to prove driving skills OFFLINE before a live race (skillsmith-style: build, verify, then use).

It reproduces what made the kart swing on 3 Nov: the driver sees its position only through the minimap (about a metre of
noise per look, 20 looks a second) and judges its heading from the last half second of positions, so it sees each turn
late; a held steering key turns the kart at a fixed rate. Too much steering for the delay at speed = growing swings.

`run(driver, track, speed)` drives laps and returns swing (steering flips per minute), the worst distance from the road
centre (an edge is ~4-6 m away: further is a fall), and the share of looks with a large heading error.
"""
from __future__ import annotations

import math
from dataclasses import dataclass

import numpy as np

YAW_RATE = 1.6  # rad/s with a steering key held (a medium kart, roughly)


@dataclass
class SimResult:
    flips_per_min: float
    worst_off_road_m: float
    mean_off_road_m: float
    big_err_share: float
    laps: float


def run(driver, track, speed: float = 20.0, seconds: float = 60.0, hz: float = 20.0, noise_m: float = 0.8, seed: int = 1,
        throttle_follows_keys: bool = True) -> SimResult:
    rng = np.random.default_rng(seed)
    pos = track.centre[0].astype(float).copy()
    d = track.centre[2] - track.centre[0]
    heading = math.atan2(d[1], d[0])
    v = speed
    dt = 1.0 / hz
    flips, last_side, worst, big, total = 0, None, 0.0, 0, 0.0
    steps = int(seconds * hz)
    for k in range(steps):
        now = k * dt
        seen = pos + rng.normal(0.0, noise_m, 2)
        keys = driver.step(now, seen, racing=True)
        side = "L" if "left" in keys else "R" if "right" in keys else None
        if side and last_side and side != last_side:
            flips += 1
        if side:
            last_side = side
        steer = (1 if "left" in keys else -1 if "right" in keys else 0) * driver.steer_sign
        heading += steer * YAW_RATE * dt
        if throttle_follows_keys:
            target_v = speed if "up" in keys else max(v - 6.0 * dt * 4, 4.0)
            if "down" in keys:
                target_v = max(v - 12.0 * dt * 4, 4.0)
            v += (target_v - v) * 0.15
        pos = pos + v * dt * np.array([math.cos(heading), math.sin(heading)])
        dist = float(np.min(np.linalg.norm(track.centre - pos, axis=1)))
        worst = max(worst, dist)
        total += dist
        if driver.log and len(driver.log[-1]) == 8 and abs(driver.log[-1][4]) > 0.5:
            big += 1
    return SimResult(flips / (seconds / 60.0), worst, total / steps, big / steps, driver.progress / driver.lap_length)
