"""Hold a key, speak, release: the spoken words become a command for the buddy.

While the key is held the microphone feeds the realtime transcriber and the partial text is shown live. On release the audio ends,
the final text goes into the command queue (the typed fallback keeps working beside it), and the time from key release to the
first game key the buddy presses afterwards is measured. That number comes only from this tool's own clock."""
from __future__ import annotations

import math
import threading
import time
from typing import Callable

from brain import BrainError
from playfellow_coop.microphone import Source
from playfellow_coop.realtime_voice import RealtimeTranscriber, keywords_for
from playfellow_coop.voice import CommandQueue


class VoiceLatency:
    """Seconds from "the player let go of the talk key" to "the buddy pressed its first game key because of it"."""

    def __init__(self, clock: Callable[[], float] = time.perf_counter):
        self._clock = clock
        self._lock = threading.Lock()
        self._released: list[float] = []  # releases whose words have not yet led to a key
        self.samples: list[float] = []

    def released(self) -> None:
        with self._lock:
            self._released.append(self._clock())

    def discard(self) -> None:
        """A spoken control phrase ("you take it") was used up without the AI: forget its release, so the next real command is not
        paired with it."""
        with self._lock:
            if self._released:
                self._released.pop(0)

    def key_pressed(self) -> None:
        """Called by the loop right after the buddy presses a key in a turn that acted on a spoken command."""
        with self._lock:
            if not self._released:
                return
            self.samples.append(self._clock() - self._released.pop(0))

    def summary(self) -> dict:
        if not self.samples:
            return {"n": 0, "p50": "not measured", "p95": "not measured"}
        ordered = sorted(self.samples)

        def rank(f: float) -> float:
            return ordered[max(0, math.ceil(f * len(ordered)) - 1)]

        return {"n": len(ordered), "p50": rank(0.5), "p95": rank(0.95)}


class PushToTalk:
    def __init__(self, mic: Source, transcriber: RealtimeTranscriber, commands: CommandQueue, say: Callable[[str], None],
                 card=None, language: str = "english", latency: VoiceLatency | None = None, spawn: Callable = threading.Thread):
        self._mic, self._transcriber, self._commands, self._say = mic, transcriber, commands, say
        self._card, self._language, self.latency, self._spawn = card, language, latency, spawn
        self._lock = threading.Lock()
        self._worker = None
        self.talking = False

    def key_down(self) -> None:
        with self._lock:
            if self.talking:
                return  # auto-repeat of a held key is not a second press
            self.talking = True
        self._mic.start()
        self._worker = self._spawn(target=self._stream, daemon=True)
        self._worker.start()

    def key_up(self) -> None:
        with self._lock:
            if not self.talking:
                return
            self.talking = False
        self._mic.stop()  # ends the audio; the worker then asks for the final text

    def wait(self, timeout: float = 30.0) -> None:
        if self._worker is not None:
            self._worker.join(timeout)

    def _stream(self) -> None:
        keywords = keywords_for(self._card) if self._card is not None else None
        try:
            result = self._transcriber.transcribe(self._mic.chunks(), on_partial=lambda text: self._say(f"… {text}"),
                                                  language=self._language, keywords=keywords)
        except BrainError as error:
            self._say(error.friendly())  # a voice failure never stops play: the player can type instead
            return
        if self._commands.put(result.text):
            if self.latency is not None:
                self.latency.released()
            self._say(f"» {result.text}")


def listen_hold(key_name: str, on_down: Callable[[], None], on_up: Callable[[], None]):
    """Watch the keyboard for ONE key being held and released. Every other key is ignored on the spot and never kept."""
    from pynput import keyboard

    target = getattr(keyboard.Key, key_name.lower())

    def press(key):
        if key == target:
            on_down()

    def release(key):
        if key == target:
            on_up()

    listener = keyboard.Listener(on_press=press, on_release=release)
    listener.daemon = True
    listener.start()
    return listener
