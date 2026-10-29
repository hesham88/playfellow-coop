"""The live loop's three cost levers, in one place the session can switch on (research R1 sections 2.3 and 3.4, R4 section 8).

  tier router      from cheap signals each turn (how much the picture changed, whether the last action did anything, how often the same action repeated), which loop should decide now
  state-action     in a stable, repeated situation (reflex tier) the action that worked here before is reused with NO model call; a miss or a failure lowers its trust
  chunk executor   a model answer in the `<|action_start|>dx dy dz; K1; K2<|action_end|>` form is played as timed key holds on the active card's keys only, and every key comes back up

All three are off unless the session's `parts` carry them (`parts.live = LiveLoop(...)`, `--live on`), so a plain run behaves exactly as before. numpy only.
"""
from __future__ import annotations

from dataclasses import dataclass, field

import numpy as np

from playfellow_coop.universal.cache import StateActionMemory
from playfellow_coop.universal.chunks import Executor, parse, plan
from playfellow_coop.universal.hold import SocdCleaner
from playfellow_coop.universal.motion import motion_level
from playfellow_coop.universal.tiers import REFLEX, Router, Signals


@dataclass
class LiveLoop:
    router: Router = field(default_factory=lambda: Router(stall_ticks=6, repeat_limit=5, calm_ticks=4, tactical_cooldown=1, strategic_cooldown=8))
    memory: StateActionMemory = field(default_factory=StateActionMemory)
    served: int = 0
    asked: int = 0
    tier: str = REFLEX
    _last_frame: np.ndarray | None = None
    _last_pending: tuple[np.ndarray, list[str]] | None = None
    _repeat: int = 0
    _last_names: list[str] = field(default_factory=list)
    _asked_last: bool = False

    def look(self, frame: np.ndarray, ended: bool = False, skill_fault: bool = False) -> str:
        """Called once per turn with the new picture, before anything is asked. Settles whether the previous action worked (it changed the picture) and returns the tier that should decide now."""
        moved = motion_level(self._last_frame, frame) if self._last_frame is not None and self._last_frame.shape == frame.shape else 0.0
        if self._last_pending is not None:
            before, names = self._last_pending
            self.memory.record(before, None, tuple(names), worked=moved > 0.002)
            self._last_pending = None
        failed = self._asked_last and moved <= 0.002  # the last answer came from the model and the picture did not answer
        signals = Signals(novelty=min(1.0, moved * 4.0), progress_delta=moved, repeat_count=self._repeat, skill_fault=skill_fault, tactical_failed=failed, ended=ended)
        self.tier = self.router.observe(signals).tier
        self._last_frame = frame
        return self.tier

    def cached(self, frame: np.ndarray) -> list[str] | None:
        """In the reflex tier only: the action names that worked in a near-identical picture before, or None (ask the model)."""
        if self.tier != REFLEX:
            return None
        hit = self.memory.lookup(frame, None)
        if hit is not None:
            self.served += 1
            return list(hit)
        return None

    def acted(self, frame: np.ndarray, names: list[str], from_cache: bool = False) -> None:
        if not from_cache:
            self.asked += 1
        self._asked_last = not from_cache
        self._repeat = self._repeat + 1 if names and names == self._last_names else 0
        self._last_names = list(names)
        self._last_pending = (frame, list(names))

    def summary(self) -> dict:
        return {"tier_shares": self.router.share(), "model_calls": self.asked, "served_from_memory": self.served, "memory_hit_rate": round(self.memory.hit_rate, 3)}


class ChunkBackend:
    """Adapts a pydirectinput-style backend (keyDown, keyUp, moveRel) to the chunk executor's key_down, key_up, mouse_move."""

    def __init__(self, backend):
        self.backend = backend

    def key_down(self, key: str) -> None:
        self.backend.keyDown(key)

    def key_up(self, key: str) -> None:
        self.backend.keyUp(key)

    def mouse_move(self, dx: int, dy: int) -> None:
        self.backend.moveRel(dx, dy)


def run_chunks(raw: str, allowed: set[str], backend, should_stop=lambda: False, sleep=None, allow_mouse: bool = False) -> int:
    """Play the chunks in a model answer with the card's keys only (anything else is dropped before it is pressed). Returns how many events were performed; 0 when the answer has no chunks."""
    chunks = [c for c in parse(raw)]
    if not chunks:
        return 0
    allowed = {k.lower() for k in allowed}
    socd = SocdCleaner("neutral")  # left and right (or up and down) together press nothing, as on the ordinary key path
    cleaned = []
    for c in chunks:
        keys = frozenset(socd.clean({k for k in c.keys if k.lower() in allowed}))
        dx, dy, dz = (c.dx, c.dy, c.dz) if allow_mouse else (0, 0, 0)  # mouse motion is only played when the card is a mouse card
        cleaned.append(type(c)(dx, dy, dz, keys))
    events = plan(cleaned)
    executor = Executor(ChunkBackend(backend)) if sleep is None else Executor(ChunkBackend(backend), sleep=sleep)
    return executor.run(events, should_stop)
