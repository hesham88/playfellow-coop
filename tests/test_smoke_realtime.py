"""The one capped REALTIME voice call of the credit-day script, against a fake socket only: at most 5 s of audio, paced at real time, a
wall-clock stop, every frame saved with the key replaced and the audio itself never saved."""
from __future__ import annotations

import io
import json
import wave

from playfellow_coop import realtime_voice, smoke
from tests.test_realtime_voice import FakeRealtime
from tests.test_smoke import KEY, go, server  # noqa: F401  (server is a fixture)


def wav_of(seconds: float) -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(24000)
        clip.writeframes(b"\x01\x00" * int(24000 * seconds))
    return buffer.getvalue()


def saved(tmp_path) -> dict:
    return json.loads((tmp_path / "real" / "realtime_voice.json").read_text(encoding="utf-8"))


def test_at_most_five_seconds_of_audio_are_sent_however_long_the_recording_is(server, tmp_path):  # noqa: F811
    go(tmp_path, wav_source=lambda: wav_of(8))
    assert server.realtime.audio_bytes == 5 * realtime_voice.BYTES_PER_SECOND


def test_a_short_recording_is_sent_whole(server, tmp_path):  # noqa: F811
    go(tmp_path, wav_source=lambda: wav_of(2))
    assert server.realtime.audio_bytes == 2 * realtime_voice.BYTES_PER_SECOND


def test_the_audio_is_paced_at_real_time(server, tmp_path):  # noqa: F811
    sleeps = []
    go(tmp_path, wav_source=lambda: wav_of(3), sleep=sleeps.append)
    assert len(sleeps) == 30 and abs(sum(sleeps) - 3.0) < 0.01 and max(sleeps) <= 0.1 + 1e-9  # 100 ms of audio, then 100 ms of waiting


def test_the_frames_are_saved_with_the_key_replaced_and_no_audio(server, tmp_path):  # noqa: F811
    go(tmp_path, wav_source=lambda: wav_of(1))
    text = (tmp_path / "real" / "realtime_voice.json").read_text(encoding="utf-8")
    record = saved(tmp_path)
    assert KEY not in text and "***" in text
    assert set(record) == {"path", "status", "content_type", "body"} and record["path"].endswith("/asr/realtime")
    sent, received = record["body"]["sent"], record["body"]["received"]
    assert sent[0]["json"]["authorization"] == {"accessToken": "Bearer ***"} and sent[0]["json"]["audioEncoding"] == "PCM_24KHZ"
    assert sent[1] == {"direction": "sent", "type": "binary", "frames": 10, "bytes": realtime_voice.BYTES_PER_SECOND}  # counts only
    assert sent[-1]["json"] == {"type": "endStream"}
    assert [frame["json"]["transcript"] for frame in received] == ["grab", "grab the", "grab the coins", "grab the coins on the left"]
    assert received[-1]["json"]["final"] is True and all(frame["json"].get("final") is False for frame in received[:-1])
    ms = [frame["at_ms"] for frame in received]
    assert ms == sorted(ms) and all(isinstance(m, int) for m in ms)
    assert "\\x01" not in text and "AQAB" not in text  # no audio, raw or base64


def test_a_key_the_service_echoes_in_a_frame_is_replaced(server, tmp_path):  # noqa: F811
    server.realtime.final = f"your key was {KEY}"
    go(tmp_path)
    text = (tmp_path / "real" / "realtime_voice.json").read_text(encoding="utf-8")
    assert KEY not in text and "your key was ***" in text


def test_an_error_frame_is_kept_because_its_shape_is_worth_knowing(server, tmp_path):  # noqa: F811
    server.realtime.error = "boom"
    code, said = go(tmp_path)
    assert code == 1 and said[4].startswith("realtime: DIFFERS: the call failed: brain_trouble")
    assert saved(tmp_path)["body"]["received"][0]["json"] == {"type": "error", "message": "boom"}


class Silent(FakeRealtime):
    """Takes the handshake and the audio and never answers."""

    def _handle(self, connection):
        self.connections += 1
        self.handshakes.append(json.loads(connection.recv(timeout=5)))
        for message in connection:
            if isinstance(message, bytes):
                self.audio_bytes += len(message)


def test_a_service_that_never_answers_is_given_up_on_by_the_wall_clock(server, tmp_path, monkeypatch):  # noqa: F811
    with Silent() as silent:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", silent.url)
        code, said = go(tmp_path, realtime_timeout=0.4)
    assert code == 1 and said[4].startswith("realtime: DIFFERS: the call failed")
    record = saved(tmp_path)
    assert record["body"]["received"] == [] and record["body"]["sent"][0]["json"]["authorization"] == {"accessToken": "Bearer ***"}


def test_the_caps_are_the_documented_ones():
    assert smoke.REALTIME_MAX_SECONDS == 5.0 and smoke.REALTIME_CHUNK_SECONDS == 0.1
    assert smoke.REALTIME_MAX_SECONDS / 3600 * realtime_voice.USD_PER_HOUR < 0.0003  # the most this call can cost


# ---- the wall clock, with a clock the test controls -----------------------------------------------------------------------------
class Clock:
    def __init__(self):
        self.now = 0.0

    def __call__(self):
        return self.now


def test_audio_stops_when_the_deadline_passes():
    clock = Clock()
    sent = []
    for piece in smoke.realtime_chunks(wav_of(3), lambda seconds: setattr(clock, "now", clock.now + seconds), clock, deadline=1.0):
        sent.append(piece)
    assert 10 <= len(sent) <= 11  # 100 ms per piece: stopped a second in, not after the three seconds
    clock.now = 5.0
    assert list(smoke.realtime_chunks(wav_of(3), lambda s: None, clock, deadline=1.0)) == []  # already late: nothing is sent


def test_no_frame_is_waited_for_after_the_deadline():
    class Underlying:
        def __init__(self):
            self.asked = []

        def recv(self, timeout=None):
            self.asked.append(timeout)
            return '{"transcript": "x", "final": true}'

    clock, under = Clock(), Underlying()
    tap = smoke.RealtimeTap("k", clock, deadline=10.0)
    connection = smoke._TapConnection(under, tap)
    clock.now = 7.0
    connection.recv(timeout=15.0)
    assert under.asked == [3.0]  # never longer than what is left of the wall clock
    clock.now = 10.5
    try:
        connection.recv(timeout=15.0)
        raised = False
    except TimeoutError:
        raised = True
    assert raised and under.asked == [3.0]  # the underlying socket was not even asked
    assert len(tap.record["body"]["received"]) == 1


def test_a_clock_that_runs_out_ends_the_call_as_busy_with_no_audio_sent(server, tmp_path):  # noqa: F811
    ticks = iter(range(0, 10_000, 100))
    code, said = go(tmp_path, clock=lambda: next(ticks))
    assert code == 1 and said[4].startswith("realtime: DIFFERS: the call failed: busy") and server.realtime.audio_bytes == 0
