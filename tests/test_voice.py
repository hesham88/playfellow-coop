"""Voice commands: Muse Voice Transcribe against a fake server, a typed fallback, and the command reaching the planner (with the
marks) so that only keys on the controls card are pressed. No microphone, no Meta call."""
from __future__ import annotations

import http.server
import io
import json
import threading
import wave

import pytest

from brain import BrainError
from playfellow_coop import session, voice
from playfellow_coop.budget import DailyBudget
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue, MuseVoiceTranscriber, check_wav, for_the_planner, typed_listener
from tests.test_session_and_handover import MOVE, make

SECRET = "voice-test-key-S3cr3t"


def wav(seconds=0.1, rate=24000, channels=1, width=2) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(channels)
        clip.setsampwidth(width)
        clip.setframerate(rate)
        clip.writeframes(b"\x00" * int(seconds * rate) * channels * width)
    return buffer.getvalue()


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.hits.append({"path": self.path, "auth": self.headers.get("Authorization"), "type": self.headers.get("Content-Type"),
                                 "accept": self.headers.get("Accept"), "body": body})
        status, payload = self.server.script.pop(0) if self.server.script else (200, self.server.default)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Handler)
    srv.hits, srv.script = [], []
    srv.default = {"sessionId": "s", "transcript": "  grab the coins on the left ", "audioDurationMs": 1800, "turns": []}
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    monkeypatch.setitem(voice.ENDPOINTS, "voice", f"http://127.0.0.1:{srv.server_address[1]}/v1")
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


@pytest.fixture
def transcriber(server, tmp_path):
    made = []

    def build(**kw):
        kw.setdefault("budget", DailyBudget(tmp_path / "v.json", cap_usd=5, max_calls=100))
        t = MuseVoiceTranscriber(SECRET, **kw)
        made.append(t)
        return t

    yield build
    for t in made:
        t.close()


def test_a_recording_is_sent_as_the_docs_describe_and_the_transcript_comes_back(transcriber, server):
    text = transcriber().transcribe(wav(), language="arabic", keywords=["coins"])
    assert text == "grab the coins on the left"
    (hit,) = server.hits
    assert hit["path"] == "/v1/asr/transcribe" and hit["auth"] == f"Bearer {SECRET}" and hit["accept"] == "application/json"
    assert hit["type"].startswith("multipart/form-data")
    body = hit["body"]
    assert b'name="request"' in body and b'"model": "muse-voice-transcribe-1.0"' in body and b'"audioEncoding": "WAV"' in body
    assert b'"languageBias": ["Arabic"]' in body and b'"keywords": ["coins"]' in body and b'name="audio"' in body and b"RIFF" in body


def test_the_cost_is_the_providers_own_audio_length_at_the_published_hourly_price(transcriber, server, tmp_path):
    transcriber().transcribe(wav())
    saved = json.loads((tmp_path / "v.json").read_text(encoding="utf-8"))
    assert saved["spent_usd"] == pytest.approx(1.8 / 3600 * 0.18) and saved["calls"] == 1


@pytest.mark.parametrize("bad,why", [(b"not a wav", "not a WAV"), (wav(rate=44100), "mono 16-bit"), (wav(channels=2), "mono 16-bit"),
                                     (wav(width=1), "mono 16-bit")],
                         ids=["not-a-wav", "wrong-rate", "stereo", "8-bit"])
def test_a_recording_the_service_cannot_take_is_refused_before_anything_is_sent(transcriber, server, bad, why):
    with pytest.raises(BrainError) as caught:
        transcriber().transcribe(bad)
    assert why in caught.value.detail and server.hits == []


def test_a_recording_over_ten_minutes_or_32_megabytes_is_refused_locally(monkeypatch):
    monkeypatch.setattr(voice, "MAX_SECONDS", 0.05)
    with pytest.raises(BrainError):
        check_wav(wav(seconds=0.1, rate=16000))
    monkeypatch.setattr(voice, "MAX_BYTES", 10)
    with pytest.raises(BrainError):
        check_wav(wav())


@pytest.mark.parametrize("status,key", [(401, "bad_key"), (429, "busy"), (500, "busy"), (400, "brain_trouble")])
def test_error_codes_become_friendly_errors_and_the_key_stays_secret(transcriber, server, status, key):
    server.script.append((status, {"error": f"nope {SECRET}"}))
    with pytest.raises(BrainError) as caught:
        transcriber().transcribe(wav())
    assert caught.value.key == key and SECRET not in repr(caught.value) and SECRET not in caught.value.detail


def test_an_empty_or_odd_answer_is_a_failure(transcriber, server):
    server.script.append((200, {"transcript": "  "}))
    with pytest.raises(BrainError) as caught:
        transcriber().transcribe(wav())
    assert caught.value.key == "empty_answer"
    server.script.append((200, {"unexpected": 1}))
    with pytest.raises(BrainError):
        transcriber().transcribe(wav())


def test_the_budget_stops_a_recording_before_it_is_sent(transcriber, server, tmp_path):
    t = transcriber(budget=DailyBudget(tmp_path / "x.json", cap_usd=0.0, max_calls=10))
    with pytest.raises(BrainError) as caught:
        t.transcribe(wav())
    assert caught.value.key == "token_cap_day" and server.hits == []


def test_the_key_is_never_shown(transcriber, server, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        t = transcriber()
        t.transcribe(wav())
    assert SECRET not in repr(t) and SECRET not in caplog.text


# ---- typed commands and the queue --------------------------------------------------------------------------------
def test_the_queue_keeps_the_newest_few_and_drains_once():
    q = CommandQueue(limit=3)
    for word in ("a", "b", "c", "d"):
        q.put(word)
    assert q.put("   ") is False and q.drain() == ["b", "c", "d"] and q.drain() == []


def test_a_very_long_command_is_cut():
    q = CommandQueue()
    q.put("x" * 1000)
    assert len(q.drain()[0]) == 300


def test_the_typed_listener_turns_lines_into_commands_until_quit():
    lines = iter(["grab the coins on the left", "", "go to the door", "quit", "never read"])
    q = CommandQueue()
    typed_listener(q, lambda: next(lines)).join(timeout=5)
    assert q.drain() == ["grab the coins on the left", "go to the door"]


def test_the_typed_listener_ends_quietly_at_end_of_input():
    q = CommandQueue()

    def eof():
        raise EOFError

    typed_listener(q, eof).join(timeout=5)
    assert q.drain() == []


def test_personal_details_are_masked_before_the_planner_sees_a_command():
    out = for_the_planner(["go left, mail me at someone@example.com", "grab the coins"])
    assert "someone@example.com" not in out[0] and out[1] == "grab the coins"


# ---- the command reaches the planner, and only card keys are pressed ------------------------------------------------
def test_a_command_reaches_the_brain_first_and_only_card_keys_are_pressed():
    parts, cfg = make()
    seen = {}

    def ask(system, text, images):
        seen["text"] = text
        return json.dumps({"thought": "left coins", "say": "", "actions": [MOVE, "FORMAT_DISK"]})

    parts.brain.ask = ask
    q = CommandQueue()
    q.put("grab the coins on the left")
    session.play_session(parts, cfg, "system", StageTimer(), commands=q, max_turns=1, wait=lambda s: True)
    assert "The player says (answer them first):" in seen["text"] and "grab the coins on the left" in seen["text"]
    assert parts.hands.pressed == [MOVE]  # the off-card key was dropped by the engine's own check


def test_a_command_is_kept_when_the_turn_fails_and_when_the_game_is_not_in_front():
    parts, cfg = make()
    q = CommandQueue()
    q.put("grab the coins")
    parts.screen.front = False
    session.play_session(parts, cfg, "system", StageTimer(), commands=q, max_turns=1, wait=lambda s: True)
    assert q.drain() == ["grab the coins"]  # nothing was asked, so nothing was lost

    parts, cfg = make()
    parts.screen.front = True
    parts.brain.ask = lambda *a: (_ for _ in ()).throw(BrainError("busy", retry=True, wait_seconds=0))
    q.put("grab the coins")
    session.play_session(parts, cfg, "system", StageTimer(), commands=q, max_turns=1, wait=lambda s: True)
    assert q.drain() == ["grab the coins"]
