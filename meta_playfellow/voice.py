"""Voice commands ("grab the coins on the left"): Muse Voice Transcribe turns a short recording into text, and a typed line does the
same job, so the demo never depends on a microphone. Either way the text goes to the planner as a player message, next to the
marks; the engine's reply check then keeps only keys that are on the game's controls card.

Muse Voice Transcribe, file mode (from the docs, read 2026-10-26): POST /v1/asr/transcribe, multipart with a JSON `request` part
and a WAV `audio` part (16-bit mono PCM, 16 or 24 kHz, up to 10 minutes and 32 MB); the answer has a `transcript` field and
`audioDurationMs`. Priced at $0.18 per hour of audio. UNVERIFIED until the first real call: the exact error bodies."""
from __future__ import annotations

import io
import json
import threading
import wave
from collections import deque
from typing import Callable

import httpx

from ai_armor import AIArmor
from brain import BrainError
from meta_playfellow import _http
from meta_playfellow.budget import DailyBudget

ENDPOINTS = {"voice": "https://api.meta.ai/v1"}  # pinned on purpose
MODEL = "muse-voice-transcribe-1.0"
USD_PER_HOUR = 0.18
MAX_SECONDS = 10 * 60
MAX_BYTES = 32 * 1024 * 1024
LANGUAGES = {"english": "English", "arabic": "Arabic"}


def check_wav(data: bytes) -> float:
    """The seconds of audio, or a BrainError saying why this recording cannot be sent (nothing is sent in that case)."""
    if len(data) > MAX_BYTES:
        raise BrainError("brain_trouble", detail="the recording is larger than 32 MB")
    try:
        with wave.open(io.BytesIO(data)) as clip:
            channels, width, rate, frames = clip.getnchannels(), clip.getsampwidth(), clip.getframerate(), clip.getnframes()
    except (wave.Error, EOFError):
        raise BrainError("brain_trouble", detail="the recording is not a WAV file") from None
    if channels != 1 or width != 2 or rate not in (16000, 24000):
        raise BrainError("brain_trouble", detail="the recording must be mono 16-bit WAV at 16 or 24 kHz")
    seconds = frames / rate
    if seconds > MAX_SECONDS:
        raise BrainError("brain_trouble", detail="the recording is longer than 10 minutes")
    return seconds


class MuseVoiceTranscriber:
    def __init__(self, api_key: str, budget: DailyBudget | None = None, client: httpx.Client | None = None):
        self._key = api_key
        self.budget = budget
        self._client = client or _http.new_client()

    def __repr__(self) -> str:
        return "<MuseVoiceTranscriber>"

    def close(self) -> None:
        self._client.close()

    def transcribe(self, wav: bytes, language: str = "english", keywords: list[str] | None = None) -> str:
        seconds = check_wav(wav)  # refused here, before anything is sent
        if self.budget is not None and self.budget.exhausted():
            raise BrainError("token_cap_day")
        request = {"model": MODEL, "audioEncoding": "WAV", "mode": "PUSH_TO_TALK",
                   "languageBias": [LANGUAGES.get(language, "English")], "keywords": keywords or []}
        files = {"request": (None, json.dumps(request), "application/json"), "audio": ("command.wav", wav, "audio/wav")}
        response = _http.post_files(self._client, ENDPOINTS["voice"] + "/asr/transcribe", self._key, files)
        _http.check_status(response.status_code)
        try:
            body = response.json()
            text = body["transcript"]
        except (ValueError, KeyError, TypeError):
            raise BrainError("brain_trouble", detail="the answer was not in the expected shape") from None
        if self.budget is not None:
            duration = body.get("audioDurationMs") if isinstance(body, dict) else None
            measured = (duration / 1000.0) if isinstance(duration, (int, float)) else seconds  # the provider's own length first
            self.budget.record_cost(measured / 3600.0 * USD_PER_HOUR)
        if not isinstance(text, str) or not text.strip():
            raise BrainError("empty_answer")
        return text.strip()


class CommandQueue:
    """Spoken or typed commands waiting for the next turn. Thread-safe: a listener thread puts, the loop drains."""

    def __init__(self, limit: int = 5):
        self._items: deque[str] = deque(maxlen=limit)  # a flood keeps only the newest few
        self._lock = threading.Lock()

    def put(self, text: str) -> bool:
        text = (text or "").strip()
        if not text:
            return False
        with self._lock:
            self._items.append(text[:300])
        return True

    def take_controls(self) -> list[str]:
        """Remove the hand-over control phrases ("stop", "you take it", "I've got it") and return their actions in order.
        Ordinary commands stay in the queue for the planner."""
        from meta_playfellow.control_words import control_action

        with self._lock:
            kept, actions = [], []
            for text in self._items:
                action = control_action(text)
                (actions if action else kept).append(action or text)
            self._items.clear()
            self._items.extend(kept)
        return actions

    def drain(self) -> list[str]:
        with self._lock:
            items, _ = list(self._items), self._items.clear()
        return items


def for_the_planner(commands: list[str]) -> list[str]:
    """What the planner may see of the player's words: e-mail addresses, phone numbers and the like are masked first."""
    armor = AIArmor()
    return [armor.redact_pii(text) for text in commands]


def typed_listener(queue: CommandQueue, read_line: Callable[[], str], stop: threading.Event | None = None) -> threading.Thread:
    """The typed fallback: every line the player types becomes a command. It ends at end-of-input or on 'quit'."""
    stop = stop or threading.Event()

    def run() -> None:
        while not stop.is_set():
            try:
                line = read_line()
            except (EOFError, OSError):
                return
            if line is None or line.strip().lower() in {"quit", "exit"}:
                return
            queue.put(line)

    thread = threading.Thread(target=run, daemon=True)
    thread.start()
    return thread
