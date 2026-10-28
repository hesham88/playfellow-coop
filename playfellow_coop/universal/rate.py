"""How fast pictures really arrive: the measured picture rate and the delay of the grabber."""
from __future__ import annotations

import time
from collections import deque
from typing import Callable


class FrameClock:
    """Measures the real picture rate and the delay of the grabber, from the times pictures arrive."""

    def __init__(self, window: int = 30, clock: Callable[[], float] = time.monotonic):
        self._clock = clock
        self._times: deque[float] = deque(maxlen=window)

    def tick(self) -> None:
        self._times.append(self._clock())

    @property
    def fps(self) -> float:
        if len(self._times) < 2:
            return 0.0
        span = self._times[-1] - self._times[0]
        return (len(self._times) - 1) / span if span > 0 else 0.0

    @property
    def frame_ms(self) -> float:
        return 1000.0 / self.fps if self.fps else 0.0
