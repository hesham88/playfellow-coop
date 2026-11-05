"""Hunting items and avoiding obstacles on the road ahead, with SAM as the eye that names things.

SAM 3.1 (Meta's segmentation model) is asked, on a worker thread, where the gift boxes, nitro bottles, bananas and crates are
in the forward view. A keyframe takes 2-3 s (measured 3 Nov: 1.0-2.9 s a phrase, the phrases in parallel), far too slow to
steer by, so between keyframes the app's own tracker follows each box SAM found by its look, frame to frame, locally; SAM is
asked again when the tracker loses something or every few frames. The driver reads the freshest list each tick.

The hunt (`plan`): obstacles first, then items. A banana or a crate in the kart's path pushes the aim away from it; with no
obstacle in the way, the nearest reachable gift box or nitro bottle (low in the picture = close, near the middle = reachable
without leaving the road) pulls the aim toward it; once it is taken or passed, the next one. The pull and the push are small
angles added to the driveline's steering, capped, so the road line still leads and the kart never leaves the road for a box.
"""
from __future__ import annotations

import threading
import time
from dataclasses import dataclass, field

import numpy as np

# 5 Nov: no "wooden crate": SuperTuxKart has no crate obstacles, and SAM named the gift boxes "crate", so the kart steered
# away from the very boxes it should take (owner: "scared from gift crates")
PROMPTS = {"gift": "gift box", "nitro": "nitro bottle", "banana": "banana", "kart": "go-kart"}
ITEMS, OBSTACLES = ("gift", "nitro"), ("banana",)
VIEW = (0.08, 0.62)  # the band of the race view SAM looks at: the road ahead, above the buddy's own kart
FOV = 1.25  # radians across the view (the chase camera's field of view, roughly)


@dataclass
class Seen:
    kind: str
    x: float  # 0-1 across the looked-at band
    y: float  # 0-1 down the band (1 = nearest)
    at: float


def plan(seen: list[Seen], now: float, max_age: float = 1.2, pull_cap: float = 0.22, push: float = 0.28) -> tuple[float, str, Seen | None]:
    """(steering bias in radians, + = to the left; why; the chosen thing). Obstacles in the path win over items."""
    fresh = [s for s in seen if now - s.at <= max_age]
    in_path = [s for s in fresh if s.kind in OBSTACLES and abs(s.x - 0.5) < 0.16 and s.y > 0.45]
    if in_path:
        nearest = max(in_path, key=lambda s: s.y)
        away = push if nearest.x >= 0.5 else -push  # it is right of centre: go left (+), and the other way round
        return away, f"{nearest.kind} ahead, steering around it", nearest
    reachable = [s for s in fresh if s.kind in ITEMS and abs(s.x - 0.5) < 0.30 and 0.30 < s.y < 0.85]
    if not reachable:
        return 0.0, "", None
    # mid-band first: far enough that the bearing still holds while the kart closes in, near enough to be reached
    target = min(reachable, key=lambda s: abs(s.y - 0.55) + 0.5 * abs(s.x - 0.5))
    bearing = -(target.x - 0.5) * FOV  # right of centre = turn right = negative
    return float(np.clip(bearing, -pull_cap, pull_cap)), f"going for the {target.kind} {'left' if bearing > 0 else 'right' if bearing < 0 else 'ahead'}", target


def aim(seen: list[Seen], now: float, max_age: float = 0.8, line_up: float = 0.06, pull_cap: float = 0.06) -> tuple[float, bool, Seen | None]:
    """(steering bias to line up on the nearest opponent ahead, fire now?, that kart). A weapon is for hitting someone: it is
    fired only when an opponent kart is in front, near the middle of the view and close enough, never just to empty the hand."""
    # the buddy's own kart reaches into the bottom middle of the looked-at band (from about 0.74 down): a "kart" there is me,
    # not an opponent (3 Nov: it fired at itself every 5 s)
    karts = [s for s in seen if s.kind == "kart" and now - s.at <= max_age and abs(s.x - 0.5) < 0.22 and 0.20 < s.y < 0.66]
    if not karts:
        return 0.0, False, None
    target = max(karts, key=lambda s: s.y - abs(s.x - 0.5))
    bearing = -(target.x - 0.5) * FOV
    return float(np.clip(bearing, -pull_cap, pull_cap)), abs(target.x - 0.5) < line_up, target


@dataclass
class ItemEye:
    """The worker: grabs the forward band, asks the marker (SAM + tracker), keeps the latest sightings."""

    grab: object  # () -> BGR band of the forward view
    marker: object  # SamMarker(prompts=PROMPTS, tracker=Tracker())
    every: float = 0.15
    seen: list = field(default_factory=list)
    keyframes: int = 0
    errors: int = 0
    _stop: threading.Event = field(default_factory=threading.Event)

    def start(self) -> "ItemEye":
        threading.Thread(target=self._run, name="item-eye", daemon=True).start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        from PIL import Image

        while not self._stop.is_set():
            started = time.monotonic()
            try:
                grabbed_at = time.monotonic()  # a sighting is as old as the PICTURE, not the answer (a keyframe takes 2-3 s)
                band = self.grab()
                if band is not None:
                    calls_before = self.marker.calls
                    marks = self.marker(Image.fromarray(np.ascontiguousarray(band[:, :, ::-1])))
                    keyframe = self.marker.calls > calls_before
                    self.keyframes += keyframe
                    # near-field things (low in the band) are passed within a second: trusted only when the tracker followed
                    # them on THIS picture (no SAM wait), never from a keyframe that came back seconds later
                    self.seen = [Seen(m.kind, m.x / 1000.0, m.y / 1000.0, grabbed_at) for m in marks
                                 if not (keyframe and m.y / 1000.0 > 0.70)]
            except Exception:  # noqa: BLE001 - a failed look never stops the driving
                self.errors += 1
            self._stop.wait(max(0.0, self.every - (time.monotonic() - started)))
