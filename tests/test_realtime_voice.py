"""Realtime push-to-talk against a FAKE WebSocket server on 127.0.0.1 and a pretend microphone: the handshake, live partials, the
key only in the handshake frame, no proxy, no redirect, the budget, the hold-to-talk flow, and the key-release-to-first-key stopwatch.
The frame format is the architect's notes, not a recording; the first real call must save real frames as a fixture."""
from __future__ import annotations

import json
import threading
import time

import pytest
from websockets.sync.server import serve

from brain import BrainError
from playfellow_coop import realtime_voice, session
from playfellow_coop.budget import DailyBudget
from playfellow_coop.push_to_talk import PushToTalk, VoiceLatency
from playfellow_coop.realtime_voice import RealtimeTranscriber, keywords_for
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue
from tests.test_session_and_handover import CARD, MOVE, make

KEY = "rt-test-key-S3cr3tValue"
FRAME = b"\x01\x00" * 2400  # 100 ms of 24 kHz 16-bit audio


class FakeRealtime:
    """Reads the handshake, counts audio bytes, and after endStream answers with partials and a final."""

    def __init__(self, partials=("grab", "grab the", "grab the coins"), final="grab the coins on the left", audio_ms=None,
                 error=None):
        self.partials, self.final, self.audio_ms, self.error = list(partials), final, audio_ms, error
        self.handshakes, self.audio_bytes, self.texts, self.paths, self.connections = [], 0, [], [], 0
        self.headers: list[dict] = []
        self.server = serve(self._handle, "127.0.0.1", 0, process_request=self._peek)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)

    def _peek(self, connection, request):
        self.paths.append(request.path)
        self.headers.append({k.lower(): v for k, v in request.headers.items()})
        return None

    def _handle(self, connection):
        self.connections += 1
        self.handshakes.append(json.loads(connection.recv(timeout=5)))
        for message in connection:
            if isinstance(message, bytes):
                self.audio_bytes += len(message)
                continue
            self.texts.append(message)
            if json.loads(message).get("type") == "endStream":
                if self.error is not None:
                    connection.send(json.dumps({"type": "error", "message": self.error}))
                    return
                for text in self.partials:
                    connection.send(json.dumps({"transcript": text, "final": False}))
                done = {"transcript": self.final, "final": True}
                if self.audio_ms is not None:
                    done["audioDurationMs"] = self.audio_ms
                connection.send(json.dumps(done))
                return

    @property
    def url(self) -> str:
        return f"ws://127.0.0.1:{self.server.socket.getsockname()[1]}/v1/asr/realtime"

    def __enter__(self):
        self.thread.start()
        return self

    def __exit__(self, *exc):
        self.server.shutdown()
        self.thread.join(timeout=5)


@pytest.fixture
def fake(monkeypatch):
    with FakeRealtime() as server:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", server.url)
        yield server


def transcriber(tmp_path, **kw):
    kw.setdefault("budget", DailyBudget(tmp_path / "rt.json", cap_usd=5, max_calls=100))
    return RealtimeTranscriber(KEY, **kw)


def test_the_handshake_has_the_architects_fields_and_audio_follows(fake, tmp_path):
    result = transcriber(tmp_path).transcribe([FRAME] * 5, language="arabic", keywords=["coins", "باب"])
    (hello,) = fake.handshakes
    assert hello == {"authorization": {"accessToken": f"Bearer {KEY}"}, "audioEncoding": "PCM_24KHZ",
                     "model": "muse-voice-transcribe-1.0", "mode": "PUSH_TO_TALK", "languageBias": ["Arabic"],
                     "keywords": ["coins", "باب"]}
    assert fake.audio_bytes == 5 * len(FRAME) and json.loads(fake.texts[-1]) == {"type": "endStream"}
    assert result.text == "grab the coins on the left"


def test_partial_text_is_shown_live_in_order_before_the_final(fake, tmp_path):
    shown = []
    result = transcriber(tmp_path).transcribe([FRAME], on_partial=shown.append)
    assert shown == ["grab", "grab the", "grab the coins"] == result.partials
    assert result.first_partial_s is not None and result.first_partial_s >= 0


def test_the_key_is_only_in_the_handshake_frame_never_in_the_address_headers_or_logs(fake, tmp_path, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        t = transcriber(tmp_path)
        t.transcribe([FRAME])
    assert KEY not in "".join(fake.paths) and all(KEY not in json.dumps(h) for h in fake.headers)
    assert "authorization" not in fake.headers[0]  # no Authorization header either: the handshake frame carries it
    assert KEY not in caplog.text and KEY not in repr(t) and KEY not in "".join(fake.texts)


def test_the_connection_ignores_proxies_trusts_only_certifi_and_names_nothing_extra(tmp_path):
    seen = {}

    def connect(url, **kw):
        seen.update(url=url, **kw)
        raise OSError("stop here")

    with pytest.raises(BrainError):
        transcriber(tmp_path, connect=connect).transcribe([FRAME])
    assert seen["url"] == "wss://api.meta.ai/v1/asr/realtime" and seen["proxy"] is None
    assert seen["ssl"].verify_mode.name == "CERT_REQUIRED" and seen["ssl"].check_hostname
    assert "additional_headers" not in seen and seen["user_agent_header"] is None


def test_the_address_cannot_be_moved_by_the_environment(monkeypatch):
    for name in ("MUSE_REALTIME_URL", "MODEL_API_BASE", "ASR_URL"):
        monkeypatch.setenv(name, "ws://203.0.113.9:9")
    assert realtime_voice.ENDPOINTS["realtime"] == "wss://api.meta.ai/v1/asr/realtime"


def test_a_redirecting_server_is_refused_and_nothing_follows(monkeypatch, tmp_path):
    with FakeRealtime() as target:
        def redirect(connection, request):
            from websockets.http11 import Response
            from websockets.datastructures import Headers

            return Response(307, "Temporary Redirect", Headers({"Location": target.url}), b"")

        redirecting = serve(lambda c: None, "127.0.0.1", 0, process_request=redirect)
        thread = threading.Thread(target=redirecting.serve_forever, daemon=True)
        thread.start()
        try:
            monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", f"ws://127.0.0.1:{redirecting.socket.getsockname()[1]}/v1/asr/realtime")
            with pytest.raises(BrainError):
                transcriber(tmp_path).transcribe([FRAME])
            assert target.connections == 0
        finally:
            redirecting.shutdown()
            thread.join(timeout=5)


@pytest.mark.parametrize("status,key", [(401, "bad_key"), (403, "bad_key"), (429, "busy"), (503, "busy")])
def test_a_refusal_at_connect_becomes_the_friendly_error(monkeypatch, tmp_path, status, key):
    from websockets.datastructures import Headers
    from websockets.http11 import Response

    refusing = serve(lambda c: None, "127.0.0.1", 0, process_request=lambda c, r: Response(status, "no", Headers(), b""))
    thread = threading.Thread(target=refusing.serve_forever, daemon=True)
    thread.start()
    try:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", f"ws://127.0.0.1:{refusing.socket.getsockname()[1]}/x")
        with pytest.raises(BrainError) as caught:
            transcriber(tmp_path).transcribe([FRAME])
        assert caught.value.key == key and KEY not in repr(caught.value)
    finally:
        refusing.shutdown()
        thread.join(timeout=5)


def test_the_budget_stops_a_stream_before_it_is_opened(fake, tmp_path):
    with pytest.raises(BrainError) as caught:
        transcriber(tmp_path, budget=DailyBudget(tmp_path / "x.json", cap_usd=0.0, max_calls=5)).transcribe([FRAME])
    assert caught.value.key == "token_cap_day" and fake.connections == 0


def test_the_cost_uses_the_providers_audio_length_else_our_own_byte_count(monkeypatch, tmp_path):
    with FakeRealtime(audio_ms=2500) as server:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", server.url)
        transcriber(tmp_path).transcribe([FRAME])
    assert json.loads((tmp_path / "rt.json").read_text(encoding="utf-8"))["spent_usd"] == pytest.approx(2.5 / 3600 * 0.18)
    with FakeRealtime() as server:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", server.url)
        t = transcriber(tmp_path, budget=DailyBudget(tmp_path / "own.json", cap_usd=5, max_calls=9))
        t.transcribe([FRAME] * 10)  # 10 x 100 ms = 1 s of audio, counted from the bytes we sent
    assert json.loads((tmp_path / "own.json").read_text(encoding="utf-8"))["spent_usd"] == pytest.approx(1.0 / 3600 * 0.18)


def test_an_empty_final_is_a_failure_and_an_error_frame_is_a_friendly_error(monkeypatch, tmp_path):
    with FakeRealtime(partials=(), final="   ") as server:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", server.url)
        with pytest.raises(BrainError) as caught:
            transcriber(tmp_path).transcribe([FRAME])
    assert caught.value.key == "empty_answer"
    with FakeRealtime(error=f"boom {KEY}") as server:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", server.url)
        with pytest.raises(BrainError) as caught:
            transcriber(tmp_path).transcribe([FRAME])
        assert caught.value.key == "brain_trouble" and KEY not in repr(caught.value) and KEY not in caught.value.detail


def test_the_keywords_come_from_the_active_card_and_the_usual_game_words_in_both_languages():
    words = keywords_for(CARD)
    assert MOVE.lower() in words and "coins" in words and "باب" in words and len(words) == len(set(words)) <= 40


# ---- hold to talk -----------------------------------------------------------------------------------------------
class FakeMic:
    def __init__(self, frames=3):
        self.frames, self.started, self.stopped = frames, 0, 0
        self._done = threading.Event()

    def start(self):
        self.started += 1
        self._done.clear()

    def stop(self):
        self.stopped += 1
        self._done.set()

    def chunks(self):
        for _ in range(self.frames):
            yield FRAME
        self._done.wait(5)  # the audio ends when the key is released


def talk(fake, tmp_path, clock=None, mic=None, **kw):
    said, queue = [], CommandQueue()
    latency = VoiceLatency(clock) if clock else VoiceLatency()
    ptt = PushToTalk(mic or FakeMic(), transcriber(tmp_path), queue, said.append, card=CARD, latency=latency, **kw)
    return ptt, queue, said, latency


def test_hold_speak_release_puts_the_words_in_the_queue_and_shows_the_partials(fake, tmp_path):
    ptt, queue, said, latency = talk(fake, tmp_path)
    ptt.key_down()
    ptt.key_down()  # key auto-repeat: not a second press
    assert ptt._mic.started == 1
    ptt.key_up()
    ptt.wait()
    assert queue.drain() == ["grab the coins on the left"] and fake.connections == 1
    assert said[:3] == ["… grab", "… grab the", "… grab the coins"] and said[-1] == "» grab the coins on the left"
    assert fake.handshakes[0]["keywords"] and "coins" in fake.handshakes[0]["keywords"]


def test_a_release_without_a_press_does_nothing(fake, tmp_path):
    ptt, queue, said, _ = talk(fake, tmp_path)
    ptt.key_up()
    assert ptt._mic.stopped == 0 and fake.connections == 0 and queue.drain() == []


def test_a_voice_failure_says_so_and_never_stops_play_the_player_can_type(monkeypatch, tmp_path):
    monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", "ws://127.0.0.1:9/none")
    said, queue = [], CommandQueue()
    ptt = PushToTalk(FakeMic(frames=1), transcriber(tmp_path), queue, said.append)
    ptt.key_down()
    ptt.key_up()
    ptt.wait()
    assert queue.drain() == [] and said
    queue.put("typed instead")
    assert queue.drain() == ["typed instead"]


def test_the_stopwatch_measures_key_release_to_the_first_game_key(fake, tmp_path):
    now = {"t": 100.0}
    ptt, queue, said, latency = talk(fake, tmp_path, clock=lambda: now["t"])
    ptt.key_down()
    ptt.key_up()
    ptt.wait()  # the words are queued and the stopwatch started (clock still 100.0)
    parts, cfg = make()
    now["t"] = 100.42  # the buddy presses its key 0.42 s later
    session.play_session(parts, cfg, "system", StageTimer(), commands=queue, latency=latency, max_turns=1, wait=lambda s: True)
    assert parts.hands.pressed == [MOVE]
    assert latency.samples == [pytest.approx(0.42)] and latency.summary()["n"] == 1


def test_no_stopwatch_sample_without_a_spoken_command_and_not_twice(fake, tmp_path):
    latency = VoiceLatency()
    parts, cfg = make()
    session.play_session(parts, cfg, "system", StageTimer(), commands=CommandQueue(), latency=latency, max_turns=1, wait=lambda s: True)
    assert latency.samples == [] and latency.summary()["p50"] == "not measured"
    ptt, queue, _, latency = talk(fake, tmp_path)
    ptt.key_down()
    ptt.key_up()
    ptt.wait()
    parts, cfg = make()
    parts.brain.ask = lambda *a: json.dumps({"thought": "", "say": "", "actions": [MOVE, MOVE]})
    session.play_session(parts, cfg, "system", StageTimer(), commands=queue, latency=latency, max_turns=1, wait=lambda s: True)
    assert len(latency.samples) == 1 and time is not None  # two presses in one turn, one measurement


def test_the_entry_point_offers_a_talk_key_and_the_microphone_is_never_built_without_one():
    import inspect

    from playfellow_coop import __main__ as entry

    source = inspect.getsource(entry)
    assert "--talk-key" in source and "from playfellow_coop.microphone import Microphone" in source
    parts, cfg = entry.build(["--typed"], build_parts=lambda c: type("P", (), {"card": CARD})(), key_loader=lambda: None)
    assert parts.talk_key == "" and parts.typed is True  # no talk key: nothing about a microphone is touched


def test_no_test_can_reach_a_real_microphone():
    import playfellow_coop.microphone as mic

    class NoDevice:
        def RawInputStream(self, **kw):  # noqa: N802
            raise OSError("no input device")

    with pytest.raises(OSError):
        mic.Microphone(NoDevice()).start()


def test_the_connection_is_opened_on_a_socket_of_our_own_so_no_library_version_can_follow_a_redirect(monkeypatch):
    """websockets 17 follows redirects inside connect() unless it was given a socket (then it refuses); 16 never follows. Giving it the
    socket makes the refusal hold on both, before any audio or the key is sent."""
    import socket

    import websockets.sync.client as ws_client

    seen = {}

    def fake_connect(url, **kw):
        seen["url"], seen["kw"] = url, kw
        raise OSError("stop here")

    monkeypatch.setattr(ws_client, "connect", fake_connect)
    with socket.create_server(("127.0.0.1", 0)) as listener:  # only has to accept the connection; no websocket server is involved
        with pytest.raises(OSError):
            realtime_voice._default_connect(f"ws://127.0.0.1:{listener.getsockname()[1]}/x", proxy=None, ssl=None, open_timeout=3)
    assert isinstance(seen["kw"]["sock"], socket.socket) and seen["kw"]["proxy"] is None
    assert seen["kw"]["sock"].fileno() == -1  # the socket was closed again when the connection failed: nothing is left open


def test_the_websockets_range_in_pyproject_is_the_tested_one():
    """Tested on 16.1.1 and 17.3 (the refusal of a redirect depends on the library's behaviour, so only tested versions are allowed)."""
    from pathlib import Path

    text = (Path(__file__).resolve().parents[1] / "pyproject.toml").read_text(encoding="utf-8")
    assert '"websockets>=16,<18"' in text
