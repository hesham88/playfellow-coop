"""Realtime push-to-talk: hold a key, speak, release; the words become a command for the buddy.

The format below comes from the architect's notes on the Muse Voice Transcribe realtime API, NOT from a recording of the real service.
UNVERIFIED until the first real call, which must save the real frames as a fixture before anything else builds on them.

  endpoint   wss://api.meta.ai/v1/asr/realtime   (pinned; no environment variable moves it)
  handshake  one text frame: {"authorization": {"accessToken": "Bearer <key>"}, "audioEncoding": "PCM_24KHZ",
             "model": "muse-voice-transcribe-1.0", "mode": "PUSH_TO_TALK", "keywords": [...], "languageBias": [...]}
  audio      binary frames of 24 kHz, 16-bit, mono PCM
  finish     one text frame: {"type": "endStream"}
  answer     events with a "transcript" (partial), then one with "final": true

The key travels ONLY in the handshake frame: never in the address, a header, a log or an error. The connection ignores proxy
variables, trusts only our own certificate roots (certifi) and never follows a redirect (the socket is opened here, so no websockets version can follow one)."""
from __future__ import annotations

import inspect
import json
import socket
import ssl
import time
from dataclasses import dataclass, field
from typing import Callable, Iterable
from urllib.parse import urlparse

import certifi

from brain import BrainError
from playfellow_coop.budget import DailyBudget

ENDPOINTS = {"realtime": "wss://api.meta.ai/v1/asr/realtime"}  # pinned on purpose
MODEL = "muse-voice-transcribe-1.0"
USD_PER_HOUR = 0.18
BYTES_PER_SECOND = 24000 * 2  # 24 kHz, 16-bit, mono
LANGUAGES = {"english": "English", "arabic": "Arabic"}
# Words a player says about any game, in English and Arabic; the card's own action names are added to these.
GAME_WORDS = ("coins", "coin", "key", "door", "jump", "left", "right", "up", "down",
              "عملات", "عملة", "مفتاح", "باب", "اقفز", "يسار", "يمين", "فوق", "تحت")


def keywords_for(card, limit: int = 40) -> list[str]:
    """Words that help the transcriber with this game: the card's action names and the usual game words."""
    words = [name.lower() for name in getattr(card, "actions", {})] + list(GAME_WORDS)
    seen, out = set(), []
    for word in words:
        if word not in seen:
            seen.add(word)
            out.append(word)
    return out[:limit]


@dataclass
class Transcript:
    text: str
    audio_ms: float
    first_partial_s: float | None  # seconds from the first audio frame to the first partial text (measured here)
    partials: list[str] = field(default_factory=list)


def _ssl_context() -> ssl.SSLContext:
    return ssl.create_default_context(cafile=certifi.where())  # certifi only, never SSL_CERT_FILE


def _default_connect(url: str, **kw):
    """Open the connection on a socket of OUR OWN. Why: websockets 17 follows a 3xx redirect inside connect(), which would send the key
    to wherever the server points; given a socket, it refuses to follow instead (and 16 never follows). So the refusal holds on both."""
    from websockets.sync.client import connect

    parsed = urlparse(url)
    port = parsed.port or (443 if parsed.scheme == "wss" else 80)
    sock = socket.create_connection((parsed.hostname, port), timeout=kw.get("open_timeout") or 10)  # direct: no proxy is consulted
    if "legacy" in inspect.signature(connect).parameters:  # websockets 17: connect() warns unless used as a context manager or told legacy=True
        kw.setdefault("legacy", True)
    try:
        return connect(url, sock=sock, **kw)
    except BaseException:
        sock.close()
        raise


class RealtimeTranscriber:
    def __init__(self, api_key: str, budget: DailyBudget | None = None, connect: Callable = _default_connect,
                 clock: Callable[[], float] = time.perf_counter, timeout: float = 15.0, tracer=None):
        self._key = api_key
        self.tracer = tracer  # an optional pf-trace/1 writer
        self.budget = budget
        self._connect = connect
        self._clock = clock
        self._timeout = timeout

    def __repr__(self) -> str:
        return "<RealtimeTranscriber>"

    def transcribe(self, chunks: Iterable[bytes], on_partial: Callable[[str], None] = lambda text: None,
                   language: str = "english", keywords: list[str] | None = None) -> Transcript:
        """Stream the audio, show each partial as it arrives, and return the final text. Nothing is opened over the daily budget."""
        if self.budget is not None and self.budget.exhausted():
            raise BrainError("token_cap_day")
        url = ENDPOINTS["realtime"]
        handshake = {"authorization": {"accessToken": f"Bearer {self._key}"}, "audioEncoding": "PCM_24KHZ", "model": MODEL,
                     "mode": "PUSH_TO_TALK", "languageBias": [LANGUAGES.get(language, "English")]}
        if keywords:
            handshake["keywords"] = keywords
        options = {"proxy": None, "ssl": _ssl_context() if url.startswith("wss://") else None, "open_timeout": self._timeout,
                   "close_timeout": 2, "max_size": 1 << 20, "user_agent_header": None}
        try:
            connection = self._connect(url, **options)
        except Exception as error:  # a refusal at connect time: say what kind, never what was sent
            raise _connect_error(error) from None
        sent_bytes, partials, final, audio_ms, first_partial = 0, [], None, None, None
        started = self._clock()
        try:
            connection.send(json.dumps(handshake))
            for chunk in chunks:
                connection.send(chunk)
                sent_bytes += len(chunk)
            connection.send(json.dumps({"type": "endStream"}))
            while final is None:
                try:
                    raw = connection.recv(timeout=self._timeout)
                except TimeoutError:
                    raise BrainError("busy", retry=True, wait_seconds=3) from None
                event = _event(raw)
                if event.get("type") == "error" or "error" in event:
                    raise BrainError("brain_trouble", detail="the service reported an error")
                text = event.get("transcript")
                if isinstance(event.get("audioDurationMs"), (int, float)):
                    audio_ms = float(event["audioDurationMs"])
                if isinstance(text, str):
                    if first_partial is None and text.strip():
                        first_partial = self._clock() - started
                    if event.get("final") is True:
                        final = text.strip()
                    elif text.strip():
                        partials.append(text.strip())
                        on_partial(text.strip())
        except BrainError as error:
            self._trace(started, sent_bytes / BYTES_PER_SECOND * 1000.0, first_partial, error=error.key)
            raise
        except Exception as error:  # the connection dropped or spoke nonsense
            failure = _connect_error(error)
            self._trace(started, sent_bytes / BYTES_PER_SECOND * 1000.0, first_partial, error=failure.key)
            raise failure from None
        finally:
            try:
                connection.close()
            except Exception:
                pass
        measured_ms = audio_ms if audio_ms is not None else sent_bytes / BYTES_PER_SECOND * 1000.0
        if self.budget is not None:
            self.budget.record_cost(measured_ms / 3_600_000.0 * USD_PER_HOUR)
        self._trace(started, measured_ms, first_partial, cost_usd=measured_ms / 3_600_000.0 * USD_PER_HOUR, parse={"valid": bool(final)})
        if not final:
            raise BrainError("empty_answer")
        return Transcript(final, measured_ms, first_partial, partials)

    def _trace(self, started: float, audio_ms: float, first_partial: float | None, **fields) -> None:
        if self.tracer is not None:
            self.tracer.request("voice", model=MODEL, audio_ms=audio_ms, request_ms=(self._clock() - started) * 1000.0,
                                first_partial_ms=None if first_partial is None else first_partial * 1000.0, **fields)


def _event(raw) -> dict:
    try:
        event = json.loads(raw if isinstance(raw, str) else bytes(raw).decode("utf-8"))
    except (ValueError, UnicodeDecodeError):
        raise BrainError("brain_trouble", detail="a frame was not JSON") from None
    return event if isinstance(event, dict) else {}


def _connect_error(error: Exception) -> BrainError:
    """Turn a websocket failure into a friendly error without quoting anything that was sent."""
    status = getattr(getattr(error, "response", None), "status_code", None)
    if status in (401, 403):
        return BrainError("bad_key")
    if status == 429:
        return BrainError("busy", retry=True, wait_seconds=10)
    if status is not None and status >= 500:
        return BrainError("busy", retry=True, wait_seconds=5)
    if status is not None:
        return BrainError("brain_trouble", detail=f"the service answered {status}")
    return BrainError("offline", retry=True, wait_seconds=5)
