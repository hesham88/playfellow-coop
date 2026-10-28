"""Run down lanes, dodge what comes, grab coins (the runner skill).

It reads where the runner is and what is coming in each lane from the picture, then picks the key sequence that survives the next few moves and
collects the most coins. The move rules it plans with are the ones the game's card describes (change lane, jump over low bars, slide under high ones).
"""
from __future__ import annotations

from playfellow_coop.skills.base import Done, Frame
from playfellow_coop.skills.looks import Look, exact_look, patch_mean

LANES, LANE_W, ROW_H, HORIZON, TOP = 3, 120, 40, 12, 64
AIR = SLIDE = 4
COLOURS = {"train": (230, 70, 70), "low": (255, 160, 40), "high": (34, 228, 255), "coin": (255, 214, 60)}
PLAYER = (124, 92, 255)
ARENA_LOOK = exact_look("arena", {"train": COLOURS["train"], "low": COLOURS["low"], "high": COLOURS["high"], "coin": COLOURS["coin"], "player": PLAYER, "road": (40, 40, 64)}, radius=30.0)
# where to sample inside a row (offsets from the lane's left edge and the row's top) for each kind
PROBES = {"coin": (60, 21), "train": (60, 20), "low": (60, 31), "high": (60, 8)}
KEYS = (None, "left", "right", "up", "down")
DEPTH = 9


def read(frame: Frame, look: Look = ARENA_LOOK):
    """(lane, jumping, sliding, items) where an item is (lane, rows ahead, kind). Each thing is read from a small patch where it sits in its row."""
    bottom = TOP + HORIZON * ROW_H
    items = []
    for lane in range(LANES):
        left = lane * LANE_W
        for ahead in range(0, HORIZON + 1):
            upper = bottom - ahead * ROW_H
            for kind, (dx, dy) in PROBES.items():
                if look.classify(patch_mean(frame, left + dx - 5, upper + dy - 3, 10, 6)) == kind:
                    items.append((lane, ahead, kind))
                    break
    lane, top_y, bottom_y = 1, None, None
    for candidate in range(LANES):
        rows = [y for y in range(bottom - 20, bottom + ROW_H + 4, 2) if look.classify(patch_mean(frame, candidate * LANE_W + 55, y, 10, 2)) == "player"]
        if rows:
            lane, top_y, bottom_y = candidate, rows[0], rows[-1] + 1
    if bottom_y is None:
        raise Done("no runner in the picture")  # a look the skill cannot read shows it nothing to stand on: say so, do not run blind
    jumping = bottom_y is not None and bottom_y < bottom + ROW_H - 10
    sliding = bottom_y is not None and top_y is not None and (bottom_y - top_y) < 24 and not jumping
    return lane, jumping, sliding, items


def step(state, key):
    """One tick of the runner's rules. state = (lane, air, slide, items-as-tuple); returns (state, coins, crashed)."""
    lane, air, slide, items = state
    if key == "left":
        lane = max(0, lane - 1)
    elif key == "right":
        lane = min(LANES - 1, lane + 1)
    elif key == "up" and air == 0 and slide == 0:
        air = AIR
    elif key == "down" and air == 0:
        slide = SLIDE
    coins, crashed, kept = 0, False, []
    for it_lane, ahead, kind in items:
        ahead -= 1
        if ahead == 0 and it_lane == lane:
            if kind == "coin":
                coins += 1
                continue
            if kind == "train" or (kind == "low" and air == 0) or (kind == "high" and slide == 0):
                crashed = True
        if ahead >= 0:
            kept.append((it_lane, ahead, kind))
    return (lane, max(0, air - 1), max(0, slide - 1), tuple(kept)), coins, crashed


def plan(state, depth: int):
    """Best (coins, first key) over `depth` ticks, never crashing; (-1, None) when every way crashes."""
    seen = {}

    def go(s, d):
        if d == 0:
            return 0
        k = (s[0], s[1], s[2], d)
        if k in seen:
            return seen[k]
        top = -1
        for key in KEYS:
            nxt, coins, crashed = step(s, key)
            if crashed:
                continue
            top = max(top, coins + go(nxt, d - 1))
        seen[k] = top
        return top

    best_key, best_value, best_rank = None, -1, None
    for key in KEYS:
        nxt, coins, crashed = step(state, key)
        if crashed:
            continue
        value = coins + go(nxt, depth - 1)
        rank = (value, 0 if key is None else -1)  # the same coins: prefer pressing nothing
        if best_rank is None or rank > best_rank:
            best_key, best_value, best_rank = key, value, rank
    return best_value, best_key


class RunLanes:
    name = "run_lanes"
    about = "Run a three-lane track: change lane around trains, jump low bars, slide under high bars, and pick up coins; use it for the whole run."
    max_steps = 700
    realtime = True

    def __init__(self, look: Look | None = None):
        self.look = look or ARENA_LOOK

    def reset(self) -> None:
        pass

    def next_key(self, frame: Frame) -> str | None:
        lane, jumping, sliding, items = read(frame, self.look)
        state = (lane, AIR if jumping else 0, SLIDE if sliding else 0, tuple(items))
        value, key = plan(state, DEPTH)
        if value < 0:
            return None  # every way crashes within the horizon: nothing better to do
        return key
