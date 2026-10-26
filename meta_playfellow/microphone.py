"""Microphone capture behind a small interface, so everything above it is tested with a pretend microphone.

The real one (sounddevice) is imported only when a Microphone is built, never at import time, and nothing in the tests builds it.
Audio is 24 kHz, 16-bit, mono: what the realtime transcriber expects. Nothing is kept: frames go to the transcriber and are dropped."""
from __future__ import annotations

import queue
from typing import Iterator, Protocol

RATE = 24000
FRAME_SECONDS = 0.1  # 100 ms per frame: short enough to show text while the player is still speaking


class Source(Protocol):
    def start(self) -> None: ...
    def chunks(self) -> Iterator[bytes]: ...  # yields frames until stop() has been called and the buffer is empty
    def stop(self) -> None: ...


class Microphone:
    """The real microphone. Raises a plain error if this PC has no input device."""

    def __init__(self, sounddevice_module=None):
        if sounddevice_module is None:
            import sounddevice as sounddevice_module  # imported here, on purpose
        self._sd = sounddevice_module
        self._frames: queue.Queue[bytes | None] = queue.Queue()
        self._stream = None

    def start(self) -> None:
        def on_audio(data, frames, time_info, status):  # runs on the audio thread: copy and return at once
            self._frames.put(bytes(data))

        self._stream = self._sd.RawInputStream(samplerate=RATE, channels=1, dtype="int16",
                                               blocksize=int(RATE * FRAME_SECONDS), callback=on_audio)
        self._stream.start()

    def stop(self) -> None:
        if self._stream is not None:
            self._stream.stop()
            self._stream.close()
            self._stream = None
        self._frames.put(None)  # the end marker: chunks() finishes after the frames already captured

    def chunks(self) -> Iterator[bytes]:
        while True:
            frame = self._frames.get()
            if frame is None:
                return
            yield frame
