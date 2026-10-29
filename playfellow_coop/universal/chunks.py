"""Action chunks: one model call, many 33 ms actions, keys that stay down (research R1 section 2.1, R3 section 7 phase 1, Lumine's 30 Hz scheme).

The model sees the screen about five times a second but the game wants input thirty or more times a second, so each answer carries six chunks:

    <|action_start|>dx dy dz; K1; K2; K3; K4; K5; K6<|action_end|>

with a mouse movement per chunk and the keys held during it. Between chunks a key that stays held is NOT released and pressed again: that resets a character's speed (stutter-stepping). `plan`
diffs one chunk against the next and emits only the real key-down and key-up events; `mouse_substeps` cuts a big camera move into small steps (an instant large jump is clipped by game
cameras); `Executor` plays a plan on an injected clock with an injected backend.
"""
from __future__ import annotations

import re
import time
from dataclasses import dataclass, field
from typing import Callable, Protocol

CHUNK_MS = 1000.0 / 30.0
START, END = "<|action_start|>", "<|action_end|>"
BLOCK = re.compile(re.escape(START) + r"(.*?)" + re.escape(END), re.S)
MAX_CHUNKS = 16
SLICE_MS = 25.0
MAX_MOUSE = 2000


@dataclass(frozen=True)
class Chunk:
    dx: int = 0
    dy: int = 0
    dz: int = 0
    keys: frozenset[str] = field(default_factory=frozenset)


def parse(text: str) -> list[Chunk]:
    """The chunks in a model answer. The first block counts; a malformed or oversized chunk is dropped, never guessed."""
    match = BLOCK.search(text or "")
    if not match:
        return []
    out: list[Chunk] = []
    parts = [p.strip() for p in match.group(1).split(";")]
    # the first part holds the mouse movement "dx dy dz", every following part is one chunk's keys; Lumine writes the movement once per call
    head = parts[0].split()
    try:
        dx, dy, dz = (int(float(v)) for v in (head + ["0", "0", "0"])[:3])
    except ValueError:
        return []
    if max(abs(dx), abs(dy), abs(dz)) > MAX_MOUSE:
        return []
    rest = parts[1:] or [""]
    for index, keys in enumerate(rest[:MAX_CHUNKS]):
        names = frozenset(k for k in re.split(r"[\s,+]+", keys.lower()) if k and k != "none")
        out.append(Chunk(dx if index == 0 else 0, dy if index == 0 else 0, dz if index == 0 else 0, names))
    return out


@dataclass(frozen=True)
class Event:
    t_ms: float
    kind: str  # "down", "up", "move"
    key: str = ""
    dx: int = 0
    dy: int = 0


def plan(chunks: list[Chunk], chunk_ms: float = CHUNK_MS, substep_ms: float = 8.33) -> list[Event]:
    """The minimal events to perform the chunks: a key goes down when it first appears, up when it first disappears, and stays down while it persists. Everything is released at the end.
    Mouse movement is cut into `substep_ms` steps over the chunk that carries it."""
    events: list[Event] = []
    held: set[str] = set()
    for i, chunk in enumerate(chunks):
        t = i * chunk_ms
        for key in sorted(held - chunk.keys):
            events.append(Event(t, "up", key))
        for key in sorted(chunk.keys - held):
            events.append(Event(t, "down", key))
        held = set(chunk.keys)
        if chunk.dx or chunk.dy:
            for s, (sx, sy) in enumerate(mouse_substeps(chunk.dx, chunk.dy, chunk_ms, substep_ms)):
                events.append(Event(t + s * substep_ms, "move", dx=sx, dy=sy))
    end = len(chunks) * chunk_ms
    for key in sorted(held):
        events.append(Event(end, "up", key))
    return sorted(events, key=lambda e: (e.t_ms, 0 if e.kind == "up" else 1))


def mouse_substeps(dx: int, dy: int, duration_ms: float, substep_ms: float = 8.33) -> list[tuple[int, int]]:
    """A relative mouse move as small steps that add up exactly to (dx, dy), spread over the duration."""
    steps = max(1, int(round(duration_ms / substep_ms)))
    out, done_x, done_y = [], 0, 0
    for i in range(1, steps + 1):
        tx, ty = round(dx * i / steps), round(dy * i / steps)
        out.append((tx - done_x, ty - done_y))
        done_x, done_y = tx, ty
    return out


class Backend(Protocol):
    def key_down(self, key: str) -> None: ...
    def key_up(self, key: str) -> None: ...
    def mouse_move(self, dx: int, dy: int) -> None: ...


class Executor:
    """Plays a plan with a clock. `clock()` returns milliseconds; `sleep(ms)` waits. A real run uses perf_counter and a sleep with a short spin tail; a test passes fakes."""

    def __init__(self, backend: Backend, clock: Callable[[], float] = lambda: time.perf_counter() * 1000.0, sleep: Callable[[float], None] = lambda ms: time.sleep(ms / 1000.0)):
        self.backend, self.clock, self.sleep = backend, clock, sleep
        self.late_ms: list[float] = []

    def run(self, events: list[Event], should_stop: Callable[[], bool] = lambda: False) -> int:
        """Play the events in time. Stops early when `should_stop()` says so, and ALWAYS releases every key that is still down. Returns how many events were performed."""
        start = self.clock()
        down: set[str] = set()
        done = 0
        try:
            for event in events:
                wait = event.t_ms - (self.clock() - start)
                while wait > 0:  # a long hold is waited out in short slices so a stop (F12, the window losing focus) is noticed within a slice
                    self.sleep(min(wait, SLICE_MS))
                    if should_stop():
                        break
                    wait = event.t_ms - (self.clock() - start)
                self.late_ms.append(max(0.0, (self.clock() - start) - event.t_ms))
                if should_stop():
                    break
                if event.kind == "down":
                    down.add(event.key)  # noted BEFORE the call: a driver that fails half way may still have pressed it, and it must be released
                    self.backend.key_down(event.key)
                elif event.kind == "up":
                    self.backend.key_up(event.key)
                    down.discard(event.key)
                else:
                    self.backend.mouse_move(event.dx, event.dy)
                done += 1
        finally:
            failed = None
            for key in sorted(down):  # a stop, an error or the end: nothing stays pressed, even when one release raises
                try:
                    self.backend.key_up(key)
                except Exception as error:  # noqa: BLE001 - keep releasing the rest, then say what failed
                    failed = failed or error
            if failed is not None:
                raise failed
        return done
