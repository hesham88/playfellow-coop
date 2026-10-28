"""A state-action memory: do not ask the model again about a screen it has already answered (research R1 section 3.4 tier 3, R2 section 5.1 ActionCache and SPIKE's memory bank).

A cheap fingerprint of the picture (a 64-bit difference hash) plus the quantised HUD numbers is the key. When the same situation comes back (a menu, a corridor, a repeated state) and the
remembered action worked before, it is replayed with no model call. Trust is earned: each entry keeps successes and failures and is only used while the Beta-posterior mean stays high enough;
an action that failed is forgotten fast. The memory is bounded (least-recently-used out), cleared when the game or the skin changes, and never stores pictures, only fingerprints.
"""
from __future__ import annotations

from collections import OrderedDict
from dataclasses import dataclass

import numpy as np

from playfellow_coop.universal.frames import resize
from playfellow_coop.universal.motion import grey


def dhash(frame: np.ndarray) -> int:
    """64-bit difference hash: shrink to 9 x 8 in grey and compare each pixel with its right neighbour."""
    small = grey(resize(frame, 9, 8))
    bits = (small[:, 1:] > small[:, :-1]).ravel()
    value = 0
    for b in bits:
        value = (value << 1) | int(b)
    return value


def hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def hud_key(hud: dict | None, step: float = 0.1) -> tuple:
    """A HUD reading as a coarse tuple: numbers rounded to `step` (so health 0.83 and 0.86 are the same state), everything else as it is."""
    if not hud:
        return ()
    out = []
    for name in sorted(hud):
        v = hud[name]
        out.append((name, round(float(v) / step) if isinstance(v, (int, float)) and not isinstance(v, bool) else v))
    return tuple(out)


@dataclass
class Entry:
    action: object
    hits: int = 1  # times it worked (plus the prior)
    misses: int = 0

    def trust(self) -> float:
        """Posterior mean of a Beta(1 + hits, 1 + misses): 0.5 with no evidence, near 1 after many successes."""
        return (1 + self.hits) / (2 + self.hits + self.misses)


class StateActionMemory:
    def __init__(self, capacity: int = 512, max_distance: int = 4, min_trust: float = 0.7):
        self.capacity, self.max_distance, self.min_trust = capacity, max_distance, min_trust
        self._entries: OrderedDict[tuple[int, tuple], Entry] = OrderedDict()
        self.lookups = 0
        self.served = 0

    def lookup(self, frame: np.ndarray, hud: dict | None = None):
        """The remembered action for this situation, or None (ask the model). The nearest fingerprint within `max_distance` bits and the same HUD key wins if it is trusted."""
        self.lookups += 1
        fingerprint, key = dhash(frame), hud_key(hud)
        best = None
        for (h, k), entry in self._entries.items():
            if k != key:
                continue
            d = hamming(h, fingerprint)
            if d <= self.max_distance and entry.trust() >= self.min_trust and (best is None or d < best[0]):
                best = (d, (h, k), entry)
        if best is None:
            return None
        self._entries.move_to_end(best[1])
        self.served += 1
        return best[2].action

    def record(self, frame: np.ndarray, hud: dict | None, action, worked: bool) -> None:
        """Remember what happened after `action` on this situation: a success strengthens the entry, a failure weakens it (and a new action replaces a distrusted one)."""
        fingerprint, key = dhash(frame), hud_key(hud)
        slot = (fingerprint, key)
        entry = self._entries.get(slot)
        if entry is None or (entry.action != action and entry.trust() < self.min_trust):
            entry = Entry(action, hits=1 if worked else 0, misses=0 if worked else 1)
        elif entry.action == action:
            entry.hits, entry.misses = entry.hits + int(worked), entry.misses + int(not worked)
        else:
            entry.misses += 1  # a different action on a trusted state: note the doubt, keep the trusted one
        self._entries[slot] = entry
        self._entries.move_to_end(slot)
        while len(self._entries) > self.capacity:
            self._entries.popitem(last=False)

    def clear(self) -> None:
        """A new game or a new skin: everything remembered is about another place."""
        self._entries.clear()

    @property
    def hit_rate(self) -> float:
        return 0.0 if self.lookups == 0 else self.served / self.lookups

    def __len__(self) -> int:
        return len(self._entries)
