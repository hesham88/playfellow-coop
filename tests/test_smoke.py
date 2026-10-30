"""The first-real-calls tool, against fake servers only: refuses without the key or the YES, saves scrubbed fixtures, reports a
shape difference in one line, and never spends past its cap."""
from __future__ import annotations

import http.server
import io
import json
import threading
import wave

import pytest

from playfellow_coop import muse_brain, realtime_voice, sam_marks, smoke, voice
from tests.test_realtime_voice import FakeRealtime

KEY = "smoke-test-key-S3cr3tValue"
CHAT = {"choices": [{"message": {"role": "assistant", "content": '{"thought": "t", "say": "", "actions": []}'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 15}}
SAM = {"output": [{"content": [{"type": "output_text", "text": "<0f>1<|box;x1=10;y1=20;x2=58;y2=68;w=480;h=432|><|mask;x=0;y=0;data=4,8,!!!!!&!!!!!|>"}]}]}
VOICE = {"sessionId": "s", "transcript": "grab the coins", "audioDurationMs": 1500, "turns": []}
SAM_NONE = {"output": [{"content": [{"type": "output_text", "text": "No matching objects."}]}]}


def wav_bytes() -> bytes:
    buffer = io.BytesIO()
    with wave.open(buffer, "wb") as clip:
        clip.setnchannels(1)
        clip.setsampwidth(2)
        clip.setframerate(24000)
        clip.writeframes(b"\x00" * 24000)
    return buffer.getvalue()


class _Fake(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.paths.append(self.path)
        self.server.bodies.append(body)
        payload = self.server.answers.get(self.path.split("/v1")[-1], {})
        if isinstance(payload, list):  # one answer per call; the last one repeats
            payload = payload.pop(0) if len(payload) > 1 else payload[0]
        data = json.dumps(payload).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server(monkeypatch):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), _Fake)
    srv.paths, srv.bodies = [], []
    srv.answers = {"/chat/completions": CHAT, "/responses": [SAM, SAM_NONE], "/asr/transcribe": VOICE}
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    for module, name in ((muse_brain, "muse"), (sam_marks, "sam"), (voice, "voice")):
        monkeypatch.setitem(module.ENDPOINTS, name, base)
    with FakeRealtime() as realtime:  # the realtime socket too: a test must never reach the real service
        monkeypatch.setitem(realtime_voice.ENDPOINTS, "realtime", realtime.url)
        srv.realtime = realtime
        yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def go(tmp_path, **kw):
    said = []
    kw.setdefault("environ", {"MODEL_API_KEY": KEY})
    kw.setdefault("confirm", lambda text: "YES")
    kw.setdefault("wav_source", wav_bytes)
    kw.setdefault("sleep", lambda seconds: None)  # the realtime stream is paced at real time; a test does not wait
    code = smoke.run(say=said.append, out_dir=tmp_path / "real", budget_file=tmp_path / "b.json", **kw)
    return code, said


def test_it_refuses_without_the_key_and_sends_nothing(server, tmp_path):
    code, said = go(tmp_path, environ={})
    assert code == 2 and server.paths == [] and "MODEL_API_KEY" in said[0]
    assert "docs/owner-live-checks.md" in said[0] and "Credit day: the first real calls" in said[0] and "step 1" in said[0]  # says where to look


def test_it_refuses_without_a_typed_yes_and_sends_nothing(server, tmp_path):
    for answer in ("", "yes", "y", "no"):
        code, said = go(tmp_path, confirm=lambda text, a=answer: a)
        assert code == 2 and server.paths == []
    asked = []
    go(tmp_path, confirm=lambda text: asked.append(text) or "no")
    assert "may spend up to $10.00" in asked[0] and "Type YES" in asked[0]  # the question says what it will spend


def test_five_calls_are_made_and_all_match(server, tmp_path):
    code, said = go(tmp_path)
    assert code == 0 and server.paths == ["/v1/chat/completions", "/v1/responses", "/v1/responses", "/v1/asr/transcribe"], said
    assert server.realtime.connections == 1  # the one capped realtime call
    assert [line.split(":")[0] for line in said[:5]] == ["muse", "sam", "sam no-match", "voice", "realtime"]
    assert all(line.split(":")[1].startswith(" OK") for line in said[:5])


def test_the_raw_answers_are_saved_as_fixtures_and_no_key_or_picture_is_in_them(server, tmp_path):
    go(tmp_path)
    saved = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "real").iterdir()}
    assert set(saved) == {"muse_chat.json", "sam_responses.json", "sam_no_match.json", "voice_transcribe.json", "realtime_voice.json"}
    assert saved["muse_chat.json"]["body"] == CHAT and saved["muse_chat.json"]["status"] == 200
    assert saved["sam_responses.json"]["path"].endswith("/responses") and saved["voice_transcribe.json"]["body"]["transcript"]
    for name in saved:
        text = (tmp_path / "real" / name).read_text(encoding="utf-8")
        assert KEY not in text and "base64" not in text


def test_a_key_the_server_echoes_back_is_scrubbed_from_the_fixture(server, tmp_path):
    server.answers["/chat/completions"] = {**CHAT, "echo": f"your key was {KEY}"}
    go(tmp_path)
    text = (tmp_path / "real" / "muse_chat.json").read_text(encoding="utf-8")
    assert KEY not in text and "***" in text


def test_a_different_shape_is_reported_in_one_line_and_the_exit_code_says_so(server, tmp_path):
    server.answers["/chat/completions"] = {"result": "hello"}
    server.answers["/responses"] = [{"output_text": "no boxes here"}, SAM]  # the first has no boxes; the "no match" call HAS boxes
    server.answers["/asr/transcribe"] = {"text": "grab the coins"}
    code, said = go(tmp_path)
    assert code == 1
    assert said[0].startswith("muse: DIFFERS") and "no choices[0].message.content" in said[0] and "usage.prompt_tokens" in said[0]
    assert said[1].startswith("sam: DIFFERS") and "no box tokens" in said[1]
    assert said[2].startswith("sam no-match: DIFFERS") and "box" in said[2]  # a box for a phrase that should match nothing
    assert said[3].startswith("voice: DIFFERS") and "transcript" in said[3]
    assert (tmp_path / "real" / "muse_chat.json").is_file()  # the surprising answer is kept: that is the point


def test_a_missing_speech_engine_skips_the_voice_call_and_says_so(server, tmp_path):
    code, said = go(tmp_path, wav_source=lambda: None)
    assert "/v1/asr/transcribe" not in server.paths and server.realtime.connections == 0 and code == 1
    assert said[3].startswith("voice: DIFFERS: skipped") and said[4].startswith("realtime: DIFFERS: skipped")


def test_the_total_cap_stops_calls_before_they_are_sent(server, tmp_path):
    code, said = go(tmp_path, total_cap=0.0)
    assert server.paths == [] and server.realtime.connections == 0 and code == 1 and all("token_cap_day" in line for line in said[:5])


def test_the_real_cap_is_ten_dollars():
    assert smoke.TOTAL_CAP_USD == 10.0


def test_the_checks_themselves(server):
    assert smoke.problems_chat(CHAT) == [] and smoke.problems_sam(SAM) == [] and smoke.problems_voice(VOICE) == []
    assert smoke.problems_chat({"choices": [{"message": {"content": " "}}]}) != []
    assert smoke.problems_sam({}) != [] and smoke.problems_voice({"transcript": 5}) != []
    assert smoke.problems_sam_no_match(SAM_NONE) == [] and smoke.problems_sam_no_match({"output": []}) == []  # an empty answer is a fine "no match"
    assert smoke.problems_sam_no_match(SAM) != [] and smoke.problems_sam_no_match("not json") != []


# ---- the second SAM call (a phrase that matches nothing) ---------------------------------------------------------------------
def test_the_no_match_call_is_a_different_phrase_saved_separately_and_does_not_overwrite_the_first(server, tmp_path):
    go(tmp_path)
    phrases = [json.loads(b)["input"][0]["content"][0]["text"] for b, path in zip(server.bodies, server.paths) if path.endswith("/responses")]
    assert phrases == [smoke.SAM_PHRASE, smoke.SAM_NO_MATCH_PHRASE] and smoke.SAM_PHRASE != smoke.SAM_NO_MATCH_PHRASE
    first = json.loads((tmp_path / "real" / "sam_responses.json").read_text(encoding="utf-8"))
    none = json.loads((tmp_path / "real" / "sam_no_match.json").read_text(encoding="utf-8"))
    assert first["body"] == SAM and none["body"] == SAM_NONE


def test_the_no_match_call_is_asked_even_when_the_first_answer_has_the_wrong_shape(server, tmp_path):
    server.answers["/responses"] = {"output_text": "no boxes here"}
    go(tmp_path)
    assert server.paths.count("/v1/responses") == 2


def test_every_call_is_counted_in_the_cap_accounting(server, tmp_path):
    go(tmp_path)
    spent = json.loads((tmp_path / "b.json").read_text(encoding="utf-8"))
    assert spent["calls"] == 5  # muse, sam, sam no-match, voice, realtime
    floor = 120 * 1.25e-6 + 15 * 4.25e-6 + 2 * sam_marks.USD_PER_IMAGE  # the chat answer's tokens and the two images, at least
    assert spent["spent_usd"] >= floor
