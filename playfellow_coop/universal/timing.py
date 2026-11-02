"""Pillar 3, the ticking clock and the running game.

* `AdaptiveSkip`: how many game frames to let pass before the next model action. While the model thinks, frames go by that nobody can act on; in a calm moment more may be skipped,
  in a frantic one none. The answer comes from the real picture rate, the model's real delay and how much is moving.
* `ClockSync`: where the game allows it (a pause hook, a slow-down hook), the game's own clock waits for the model; where it does not, the delay is simply measured and reported.
* `Supervisor`: launches a game process, watches it, restarts it after a crash (with a budget, so a game that dies at once is not restarted forever), resets it, and keeps a log.
Everything that touches the world (the clock, sleeping, starting a process) is passed in, so all of it is tested without a real game.
"""
from __future__ import annotations

import math
import time
from contextlib import contextmanager
from dataclasses import dataclass, field
from typing import Any, Callable, Iterator, Protocol

import numpy as np


class AdaptiveSkip:
    def __init__(self, max_skip: int = 12, calm: float = 0.02, frantic: float = 0.35):
        self.max_skip, self.calm, self.frantic = max_skip, calm, frantic

    def frames_to_skip(self, latency_ms: float, frame_ms: float, motion: float = 0.1, urgent: bool = False) -> int:
        """Frames to let pass before acting again. `latency_ms`: how long the model took; `frame_ms`: time per game frame (1000 / fps); `motion`: 0..1 share of the picture moving;
        `urgent`: something needs an answer now (low health, a hazard next to the player)."""
        if frame_ms <= 0:
            return 0
        passed = math.ceil(max(latency_ms, 0.0) / frame_ms)  # these went by while the model thought: acting on them would be acting on a stale picture
        if urgent or motion >= self.frantic:
            return 0  # frantic: look again at once, the picture is already late
        if motion <= self.calm:
            return min(self.max_skip, max(passed, 1) * 2)  # nothing happens: more waiting costs nothing and saves calls
        return min(self.max_skip, passed)

    def sample(self, frames: list, count: int) -> list:
        """At most `count` pictures from a buffer, evenly spaced and always including the newest: what the model is shown instead of every one of 120 per second."""
        if count <= 0 or not frames:
            return []
        if len(frames) <= count:
            return list(frames)
        if count == 1:
            return [frames[-1]]
        indexes = np.linspace(0, len(frames) - 1, count).round().astype(int)
        return [frames[i] for i in indexes]


class GameClock(Protocol):
    def pause(self) -> None: ...
    def resume(self) -> None: ...


@dataclass
class ClockSync:
    """Pauses the game while the model thinks, when the game offers a hook. `clock` is any object with pause() and resume(); None = no hook (the delay is only measured)."""
    clock: GameClock | None = None
    now: Callable[[], float] = time.monotonic
    thinking_ms: list[float] = field(default_factory=list)

    @property
    def can_pause(self) -> bool:
        return self.clock is not None

    @contextmanager
    def thinking(self) -> Iterator[None]:
        start = self.now()
        if self.clock is not None:
            self.clock.pause()
        try:
            yield
        finally:
            if self.clock is not None:
                self.clock.resume()  # always resumes, even when the model call fails: a game left paused would look like a hang
            self.thinking_ms.append((self.now() - start) * 1000.0)

    @property
    def average_ms(self) -> float:
        return sum(self.thinking_ms) / len(self.thinking_ms) if self.thinking_ms else 0.0


@dataclass
class StepClock:
    """S3: a real GameClock for our own step-driven games (the arena pack, the gyms): the game moves only when a key steps it.

    `step(key)` advances the game one tick. While paused, `advance` refuses and the game cannot move, however long the model thinks;
    that is the honest pause a third-party game does not offer (there the delay is only measured, see ClockSync)."""
    step: Callable[[Any], None]
    paused: bool = False
    ticks: int = 0

    def pause(self) -> None:
        self.paused = True

    def resume(self) -> None:
        self.paused = False

    def advance(self, key=None) -> bool:
        """One game tick with `key` (None = a wait). False when paused: nothing was pressed and the game did not move."""
        if self.paused:
            return False
        self.step(key)
        self.ticks += 1
        return True


_MISSING = object()


@dataclass
class Supervisor:
    """Starts, watches, restarts and resets a game process. `launch()` returns a handle, `alive(handle)` says it still runs, `stop(handle)` ends it."""
    launch: Callable[[], Any]
    alive: Callable[[Any], bool]
    stop: Callable[[Any], None]
    max_restarts: int = 3
    window_s: float = 60.0  # more than `max_restarts` crashes inside this window = give up
    now: Callable[[], float] = time.monotonic
    frame_probe: Callable[[Any], Any] | None = None  # S4: what the game window shows now (any hashable picture signature); None = no probe
    hang_s: float = 10.0  # the same picture for this long, while the process lives, is a hang
    events: list[tuple[float, str]] = field(default_factory=list)
    handle: Any = None
    started_at: float = 0.0
    state: str = "stopped"  # "running", "stopped", "failed"
    _crashes: list[float] = field(default_factory=list)
    _last_frame: Any = _MISSING
    _frame_since: float = 0.0
    _ready: bool = False

    def _log(self, text: str) -> None:
        self.events.append((self.now(), text))

    def start(self) -> None:
        self.handle = self.launch()
        self.started_at = self.now()
        self.state = "running"
        self._last_frame, self._ready = _MISSING, False
        self._log("started")

    def poll(self) -> str:
        """S4: one watch tick that also looks at the picture. Returns "ready" (first picture), "running", "starting" (no picture yet),
        "restarted" (crash or hang, budget spent), "stopped" or "failed". Without a frame probe it only watches the process."""
        if self.state in ("stopped", "failed"):
            return self.state
        if not self.alive(self.handle):
            return self.check()
        if self.frame_probe is None:
            return "running"
        frame = self.frame_probe(self.handle)
        if frame is None:
            return "starting"
        moment = self.now()
        if self._last_frame is _MISSING or frame != self._last_frame:
            self._last_frame, self._frame_since = frame, moment
            if not self._ready:
                self._ready = True
                self._log("ready: first picture")
                return "ready"
            return "running"
        if moment - self._frame_since >= self.hang_s:
            self._crashes = [t for t in self._crashes if moment - t <= self.window_s] + [moment]
            self._log("hang: the picture is frozen while the process lives")
            if len(self._crashes) > self.max_restarts:
                self.state = "failed"
                self._log("gave up: too many crashes")
                return "failed"
            self.start()
            self._log("restarted after a hang")
            return "restarted"
        return "running"

    def check(self) -> str:
        """Call regularly. Returns "running", "restarted", "stopped" or "failed" (too many crashes: stay down and say so)."""
        if self.state in ("stopped", "failed"):
            return self.state
        if self.alive(self.handle):
            return "running"
        moment = self.now()
        self._crashes = [t for t in self._crashes if moment - t <= self.window_s] + [moment]
        self._log("crashed")
        if len(self._crashes) > self.max_restarts:
            self.state = "failed"
            self._log("gave up: too many crashes")
            return "failed"
        self.start()
        self._log("restarted after a crash")
        return "restarted"

    def reset(self) -> None:
        """A clean new game: stop the process (if it runs) and start it again. A reset is not a crash and does not count against the budget."""
        if self.handle is not None and self.alive(self.handle):
            self.stop(self.handle)
        self._log("reset")
        self.start()

    def shutdown(self) -> None:
        if self.handle is not None and self.alive(self.handle):
            self.stop(self.handle)
        self.state = "stopped"
        self._log("stopped")

    @property
    def uptime(self) -> float:
        return self.now() - self.started_at if self.state == "running" else 0.0


def subprocess_supervisor(command: list[str], cwd: str | None = None, **options) -> Supervisor:
    """A Supervisor over a real child process (works on Windows, macOS and Linux)."""
    import subprocess

    def launch():
        return subprocess.Popen(command, cwd=cwd, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

    def stop(process):
        process.terminate()
        try:
            process.wait(timeout=5)
        except subprocess.TimeoutExpired:
            process.kill()

    return Supervisor(launch=launch, alive=lambda process: process.poll() is None, stop=stop, **options)
