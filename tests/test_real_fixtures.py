"""The parsers against the REAL Meta answers saved on credit day (tests/fixtures/real/*.json, written by demo/first_real_calls.py).

Until those files exist each test below is an expected failure ("needs the credit-day fixture"); the moment a file is there the mark
switches itself off and the test is a real test, so a parser fix takes minutes. The same checks are also run NOW, unmarked, against
fixtures made by the fake servers (the "self-check" tests), so a bug in a check cannot hide behind the expected failure.

Each file holds one record {path, status, content_type, body}:
  muse_chat.json       POST /chat/completions   body.choices[0].message.content (the JSON reply as text), body.usage.{prompt,completion}_tokens
  sam_responses.json   POST /responses          body.output_text, or body.output[*].content[*].text holding <|box;x1=..;y1=..;x2=..;y2=..;w=..;h=..|>
  voice_transcribe.json POST /asr/transcribe    body.transcript (text), body.audioDurationMs (number)
  sam_no_match.json    POST /responses          the same call with a phrase that matches nothing: no box token may be read from it
  realtime_voice.json  the realtime socket      body.sent / body.received: every text frame in order (key replaced by ***), audio only counted;
                                                received frames are JSON events: partials {"transcript", "final": false}, then ONE {"final": true}
Not captured by first_real_calls.py (so nothing here): error answers (401/429/5xx)."""
from __future__ import annotations

import json
import re
from pathlib import Path

import pytest
from PIL import Image

from playfellow_coop import realtime_voice, smoke, voice
from playfellow_coop.budget import DailyBudget
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.realtime_voice import RealtimeTranscriber
from playfellow_coop.sam_marks import SamMarker, answer_text, big_enough, parse_boxes
from playfellow_coop.voice import MuseVoiceTranscriber
from reply import parse_reply
from tests.test_session_and_handover import CARD
from tests.test_realtime_voice import FakeRealtime
from tests.test_smoke import go, server, wav_bytes  # noqa: F401  (server is a fixture)

REAL = smoke.FIXTURES
SAM_BODY = {"output": [{"content": [{"type": "output_text", "text": "<1f>1<|box;x1=10;y1=20;x2=58;y2=68;w=480;h=432|>"}]}]}


def needs(name: str):
    return pytest.mark.xfail(not (REAL / name).is_file(), reason="needs the credit-day fixture", raises=FileNotFoundError, strict=False)


def load(root: Path, name: str) -> dict:
    return json.loads((root / name).read_text(encoding="utf-8"))  # FileNotFoundError until the credit-day file exists


def budget(tmp_path) -> DailyBudget:
    return DailyBudget(tmp_path / "budget.json", cap_usd=5, max_calls=100)


def spent(tmp_path) -> float:
    return float(json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))["spent_usd"])


# ---- the checks (each takes a folder of fixtures, so they run on real files and on fake-server files alike) -------------------
def check_envelope(root: Path, name: str, suffix: str) -> dict:
    record = load(root, name)
    assert set(record) == {"path", "status", "content_type", "body"}
    assert record["status"] == 200 and record["path"].endswith(suffix) and "json" in record["content_type"]
    text = (root / name).read_text(encoding="utf-8")
    assert not re.search(r"sk-[A-Za-z0-9_\-]{20,}|Bearer\s+\S{10,}|AIza[0-9A-Za-z_\-]{20,}", text), "a key-like string is in the fixture"
    assert "base64," not in text and not re.search(r"[A-Za-z0-9+/]{300,}", text), "picture or audio bytes are in the fixture"
    return record


def check_muse(root: Path, server, tmp_path) -> None:  # noqa: F811
    record = check_envelope(root, "muse_chat.json", "/chat/completions")
    content = record["body"]["choices"][0]["message"]["content"]
    server.answers["/chat/completions"] = record["body"]
    brain = MuseBrain("muse-spark", "k", budget=budget(tmp_path))
    try:
        assert brain.ask("system", "where is the coin?", [Image.new("RGB", (32, 32))]) == content
    finally:
        brain.close()
    assert all(isinstance(brain.last_usage[k], int) and brain.last_usage[k] > 0 for k in ("prompt_tokens", "completion_tokens"))
    assert spent(tmp_path) > 0  # the cost came from the real token counts
    reply = parse_reply(content, CARD, 3)  # the engine's own reply reader, on the real wording (fences, extra text, key names)
    assert isinstance(reply.thought, str) and isinstance(reply.say, str)


def check_sam(root: Path, server, tmp_path) -> None:  # noqa: F811
    record = check_envelope(root, "sam_responses.json", "/responses")
    body = record["body"]
    assert isinstance(body.get("output_text"), str) or isinstance(body.get("output"), list)
    boxes = parse_boxes(answer_text(body))
    assert boxes, "the real answer holds no box token this parser can read"
    for (x1, y1, x2, y2), (w, h) in boxes:
        assert w > 0 and h > 0 and 0 <= x1 <= x2 <= w and 0 <= y1 <= y2 <= h  # pixels of the picture that was sent
    server.answers["/responses"] = body
    marker = SamMarker("k", prompts={"reward": smoke.SAM_PHRASE}, budget=budget(tmp_path))
    try:
        marks = marker(Image.new("RGB", (int(boxes[0][1][0]), int(boxes[0][1][1])), (10, 90, 40)))
    finally:
        marker.close()
    assert marker.last_error is None and len(marks) == len(big_enough(boxes))  # specks (the door knob) are dropped
    assert all(m.kind == "reward" and 0 <= m.x <= 1000 and 0 <= m.y <= 1000 for m in marks)


def check_voice(root: Path, server, tmp_path) -> None:  # noqa: F811
    record = check_envelope(root, "voice_transcribe.json", "/asr/transcribe")
    body = record["body"]
    assert isinstance(body["transcript"], str) and body["transcript"].strip()
    assert isinstance(body["audioDurationMs"], (int, float)) and body["audioDurationMs"] > 0
    server.answers["/asr/transcribe"] = body
    transcriber = MuseVoiceTranscriber("k", budget=budget(tmp_path))
    try:
        assert transcriber.transcribe(wav_bytes(), keywords=["coins"]) == body["transcript"].strip()
    finally:
        transcriber.close()
    assert spent(tmp_path) == pytest.approx(body["audioDurationMs"] / 1000.0 / 3600.0 * voice.USD_PER_HOUR)  # the provider's own length


def check_sam_no_match(root: Path, server, tmp_path) -> None:  # noqa: F811
    record = check_envelope(root, "sam_no_match.json", "/responses")
    body = record["body"]
    assert isinstance(body, dict)
    assert parse_boxes(answer_text(body)) == [], "the service found boxes for a phrase that should match nothing"
    server.answers["/responses"] = [body]
    marker = SamMarker("k", prompts={"reward": smoke.SAM_NO_MATCH_PHRASE}, budget=budget(tmp_path))
    try:
        marks = marker(Image.new("RGB", (64, 64), (10, 90, 40)))
    finally:
        marker.close()
    assert marks == [] and marker.last_error is None  # an empty answer is "nothing found", never an error


class Replay(FakeRealtime):
    """A fake socket that answers an endStream with the RECORDED frames, in order."""

    def __init__(self, frames):
        super().__init__()
        self.frames = frames

    def _handle(self, connection):
        self.connections += 1
        self.handshakes.append(json.loads(connection.recv(timeout=5)))
        for message in connection:
            if isinstance(message, str) and json.loads(message).get("type") == "endStream":
                for frame in self.frames:
                    connection.send(json.dumps(frame["json"]))
                return


def check_realtime(root: Path, tmp_path, monkeypatch) -> None:
    record = load(root, "realtime_voice.json")
    text = (root / "realtime_voice.json").read_text(encoding="utf-8")
    assert set(record) == {"path", "status", "content_type", "body"} and record["path"].endswith("/asr/realtime")
    assert not re.search(r"sk-[A-Za-z0-9_\-]{20,}|AIza[0-9A-Za-z_\-]{20,}", text) and not re.search(r"[A-Za-z0-9+/]{300,}", text)
    sent, received = record["body"]["sent"], record["body"]["received"]
    handshake = sent[0]["json"]
    assert handshake["authorization"] == {"accessToken": "Bearer ***"}  # the key is only ever in this frame, and it is replaced
    assert (handshake["audioEncoding"], handshake["model"], handshake["mode"]) == ("PCM_24KHZ", realtime_voice.MODEL, "PUSH_TO_TALK")
    assert sent[-1].get("json") == {"type": "endStream"}
    audio = [frame for frame in sent if frame["type"] == "binary"]
    assert len(audio) == 1 and 0 < audio[0]["bytes"] <= smoke.REALTIME_MAX_SECONDS * realtime_voice.BYTES_PER_SECOND
    assert received and all(isinstance(frame["json"], dict) for frame in received), "a frame was not a JSON object"
    assert smoke.problems_realtime(record) == []  # one final, last, with a string transcript; no error frame
    final = received[-1]["json"]
    # replay the recorded frames through realtime_voice.py itself
    with Replay(received) as replay:
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", replay.url)
        partials = []
        result = RealtimeTranscriber("k", budget=budget(tmp_path), timeout=5).transcribe([b"\x00\x00" * 2400] * 3, on_partial=partials.append)
    assert result.text == final["transcript"].strip()
    assert result.partials == [f["json"]["transcript"].strip() for f in received[:-1] if f["json"].get("transcript", "").strip()]
    assert partials == result.partials
    if isinstance(final.get("audioDurationMs"), (int, float)):
        assert result.audio_ms == final["audioDurationMs"]


# ---- on the REAL files: expected to fail until credit day, real tests after ----------------------------------------------------
@needs("muse_chat.json")
def test_the_real_muse_answer_is_read_costed_and_parsed_as_a_reply(server, tmp_path):  # noqa: F811
    check_muse(REAL, server, tmp_path)


@needs("sam_responses.json")
def test_the_real_sam_answer_gives_boxes_in_range_and_marks_on_the_grid(server, tmp_path):  # noqa: F811
    check_sam(REAL, server, tmp_path)


@needs("voice_transcribe.json")
def test_the_real_voice_answer_gives_the_transcript_and_the_providers_own_length(server, tmp_path):  # noqa: F811
    check_voice(REAL, server, tmp_path)


@needs("sam_no_match.json")
def test_the_real_sam_no_match_answer_reads_as_no_marks_and_no_error(server, tmp_path):  # noqa: F811
    check_sam_no_match(REAL, server, tmp_path)


@needs("realtime_voice.json")
def test_the_real_realtime_frames_match_what_realtime_voice_expects(tmp_path, monkeypatch):
    check_realtime(REAL, tmp_path, monkeypatch)


# ---- the same checks on fake-server fixtures, now: proof that the checks themselves work ------------------------------------------
@pytest.fixture
def fake_made(server, tmp_path):  # noqa: F811
    code, _ = go(tmp_path)
    assert code == 0
    return tmp_path / "real"


def test_self_check_muse(fake_made, server, tmp_path):  # noqa: F811
    check_muse(fake_made, server, tmp_path)


def test_self_check_sam(fake_made, server, tmp_path):  # noqa: F811
    check_sam(fake_made, server, tmp_path)


def test_self_check_voice(fake_made, server, tmp_path):  # noqa: F811
    check_voice(fake_made, server, tmp_path)


def test_self_check_sam_no_match(fake_made, server, tmp_path):  # noqa: F811
    check_sam_no_match(fake_made, server, tmp_path)


def test_self_check_realtime(fake_made, tmp_path, monkeypatch):
    check_realtime(fake_made, tmp_path, monkeypatch)


def test_self_check_the_realtime_check_catches_a_leaked_key_two_finals_and_an_error_frame(fake_made, tmp_path, monkeypatch):
    path = fake_made / "realtime_voice.json"
    good = json.loads(path.read_text(encoding="utf-8"))

    def broken(edit):
        record = json.loads(json.dumps(good))
        edit(record)
        path.write_text(json.dumps(record), encoding="utf-8")
        with pytest.raises(AssertionError):
            check_realtime(fake_made, tmp_path, monkeypatch)

    broken(lambda r: r["body"]["sent"][0]["json"]["authorization"].update(accessToken="Bearer abcdef0123456789abcdef"))
    broken(lambda r: r["body"]["received"].append({**r["body"]["received"][-1]}))  # a second final
    broken(lambda r: r["body"]["received"].insert(0, {"json": {"type": "error", "message": "x"}}))
    broken(lambda r: r["body"]["sent"].pop())  # no endStream
    broken(lambda r: r["body"]["sent"][1].update(bytes=10**7))  # more audio than the cap allows
    path.write_text(json.dumps(good), encoding="utf-8")
    check_realtime(fake_made, tmp_path, monkeypatch)


def test_self_check_the_no_match_check_catches_a_box(fake_made, server, tmp_path):  # noqa: F811
    path = fake_made / "sam_no_match.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["body"] = SAM_BODY
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_sam_no_match(fake_made, server, tmp_path)


def test_self_check_the_checks_catch_a_wrong_shape_a_key_and_a_picture(fake_made, server, tmp_path):  # noqa: F811
    path = fake_made / "sam_responses.json"
    record = json.loads(path.read_text(encoding="utf-8"))
    record["body"] = {"output_text": "no boxes"}
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_sam(fake_made, server, tmp_path)
    record["body"] = {"output_text": "<|box;x1=10;y1=20;x2=999;y2=68;w=480;h=432|>"}  # a box that leaves its own picture
    path.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_sam(fake_made, server, tmp_path)
    leaky = fake_made / "muse_chat.json"
    record = json.loads(leaky.read_text(encoding="utf-8"))
    record["body"]["echo"] = "Bearer " + "abcdef0123456789"
    leaky.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_muse(fake_made, server, tmp_path)
    record["body"]["echo"] = "A" * 400
    leaky.write_text(json.dumps(record), encoding="utf-8")
    with pytest.raises(AssertionError):
        check_muse(fake_made, server, tmp_path)


def test_the_expected_failure_mark_is_on_only_while_the_file_is_missing():
    assert needs("nonexistent.json").args[0] is True
    assert needs("muse_chat.json").args[0] == (not (REAL / "muse_chat.json").is_file())


def test_scrubbing_the_fixtures_does_not_break_a_single_check(fake_made, server, tmp_path, monkeypatch):  # noqa: F811
    import sys

    sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
    import scrub_fixtures

    assert scrub_fixtures.main([str(fake_made)]) in (0, 1)
    assert all(scrub_fixtures.leaks(json.loads(p.read_text(encoding="utf-8"))) == [] for p in fake_made.glob("*.json"))
    check_muse(fake_made, server, tmp_path / "m")
    check_sam(fake_made, server, tmp_path / "s")
    check_sam_no_match(fake_made, server, tmp_path / "n")
    check_voice(fake_made, server, tmp_path / "v")
    check_realtime(fake_made, tmp_path / "r", monkeypatch)
