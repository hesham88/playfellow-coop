"""The hand-over: the player takes the controls with one key (F9), plays, and gives them back with the same key.

While the player has the controls the buddy presses nothing and asks no AI: every held key is released the moment F9 is pressed
(the engine's Hands.on_stop), the loop skips its turns, and nothing is spent. The summary after a hand-back is built only from
numbers this module counted (time, skipped turns, AI calls made), never from a model's guess. F12 and the mouse corner still stop
everything: this module never resumes the hands once the engine's Safety has stopped."""
from __future__ import annotations

import threading
import time
from typing import Callable

from messages import tr


class HandOver:
    def __init__(self, hands, safety, clock: Callable[[], float] = time.monotonic):
        self._hands, self._safety, self._clock = hands, safety, clock
        self._lock = threading.Lock()
        self._human = False
        self._since = 0.0
        self._calls_then = 0
        self._skipped_now = 0
        self.times_taken = 0
        self.seconds_with_player = 0.0
        self.turns_skipped = 0
        self.ai_calls_while_player = 0

    @property
    def human_has_controls(self) -> bool:
        return self._human

    def toggle(self) -> str | None:
        """What F9 does: take the controls if the buddy has them, otherwise give them back (returns the summary then)."""
        with self._lock:
            human = self._human
        return self.give_back() if human else (self.take_over() and None)

    def take_over(self) -> bool:
        with self._lock:
            if self._human or self._safety.stopped:
                return False
            self._human = True
            self._since = self._clock()
            self._calls_then = self._safety.calls
            self._skipped_now = 0
            self.times_taken += 1
        self._hands.on_stop()  # every held key goes up at once, and nothing new goes down
        return True

    def note_skipped(self) -> None:
        """The loop calls this each time it skips a turn because the player has the controls."""
        with self._lock:
            if self._human:
                self._skipped_now += 1
                self.turns_skipped += 1

    def give_back(self) -> str | None:
        with self._lock:
            if not self._human:
                return None
            self._human = False
            seconds = self._clock() - self._since
            calls = self._safety.calls - self._calls_then
            skipped = self._skipped_now
            self.seconds_with_player += seconds
            self.ai_calls_while_player += calls
        if not self._safety.stopped:  # a stop (F12, the corner, a limit) stays a stop
            self._hands.resume()
        return summary(seconds, skipped, calls)


def summary(seconds: float, skipped_turns: int, ai_calls: int) -> str:
    """One plain sentence from counted facts."""
    return tr(f"Back with me. You played for {round(seconds)} s; I waited out {skipped_turns} turns and asked the AI {ai_calls} times.",
              f"عدت إليّ. لعبتَ لمدة {round(seconds)} ثانية؛ انتظرت {skipped_turns} دورة وسألت الذكاء الاصطناعي {ai_calls} مرة.")
