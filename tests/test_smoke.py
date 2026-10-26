"""The first-real-calls tool, against fake servers only: refuses without the key or the YES, saves scrubbed fixtures, reports a
shape difference in one line, and never spends past its cap."""
from __future__ import annotations

import http.server
import io
import json
import threading
import wave

import pytest

from playfellow_coop import muse_brain, sam_marks, smoke, voice

KEY = "smoke-test-key-S3cr3tValue"
CHAT = {"choices": [{"message": {"role": "assistant", "content": '{"thought": "t", "say": "", "actions": []}'}}],
        "usage": {"prompt_tokens": 120, "completion_tokens": 15}}
SAM = {"output": [{"content": [{"type": "output_text", "text": "<1f>1<|box;x1=10;y1=20;x2=58;y2=68;w=480;h=432|><|mask;lossless|>"}]}]}
VOICE = {"sessionId": "s", "transcript": "grab the coins", "audioDurationMs": 1500, "turns": []}


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
        self.rfile.read(int(self.headers.get("Content-Length") or 0))
        self.server.paths.append(self.path)
        payload = self.server.answers.get(self.path.split("/v1")[-1], {})
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
    srv.paths = []
    srv.answers = {"/chat/completions": CHAT, "/responses": SAM, "/asr/transcribe": VOICE}
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    base = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    for module, name in ((muse_brain, "muse"), (sam_marks, "sam"), (voice, "voice")):
        monkeypatch.setitem(module.ENDPOINTS, name, base)
    yield srv
    srv.shutdown()
    srv.server_close()
    thread.join(timeout=5)


def go(tmp_path, **kw):
    said = []
    kw.setdefault("environ", {"MODEL_API_KEY": KEY})
    kw.setdefault("confirm", lambda text: "YES")
    kw.setdefault("wav_source", wav_bytes)
    code = smoke.run(say=said.append, out_dir=tmp_path / "real", budget_file=tmp_path / "b.json", **kw)
    return code, said


def test_it_refuses_without_the_key_and_sends_nothing(server, tmp_path):
    code, said = go(tmp_path, environ={})
    assert code == 2 and server.paths == [] and "MODEL_API_KEY" in said[0]


def test_it_refuses_without_a_typed_yes_and_sends_nothing(server, tmp_path):
    for answer in ("", "yes", "y", "no"):
        code, said = go(tmp_path, confirm=lambda text, a=answer: a)
        assert code == 2 and server.paths == []
    asked = []
    go(tmp_path, confirm=lambda text: asked.append(text) or "no")
    assert "may spend up to $10.00" in asked[0] and "Type YES" in asked[0]  # the question says what it will spend


def test_three_calls_are_made_one_each_and_all_match(server, tmp_path):
    code, said = go(tmp_path)
    assert code == 0 and server.paths == ["/v1/chat/completions", "/v1/responses", "/v1/asr/transcribe"]
    assert said[0].startswith("muse: OK") and said[1].startswith("sam: OK") and said[2].startswith("voice: OK")


def test_the_raw_answers_are_saved_as_fixtures_and_no_key_or_picture_is_in_them(server, tmp_path):
    go(tmp_path)
    saved = {p.name: json.loads(p.read_text(encoding="utf-8")) for p in (tmp_path / "real").iterdir()}
    assert set(saved) == {"muse_chat.json", "sam_responses.json", "voice_transcribe.json"}
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
    server.answers["/responses"] = {"output_text": "no boxes here"}
    server.answers["/asr/transcribe"] = {"text": "grab the coins"}
    code, said = go(tmp_path)
    assert code == 1
    assert said[0].startswith("muse: DIFFERS") and "no choices[0].message.content" in said[0] and "usage.prompt_tokens" in said[0]
    assert said[1].startswith("sam: DIFFERS") and "no box tokens" in said[1]
    assert said[2].startswith("voice: DIFFERS") and "transcript" in said[2]
    assert (tmp_path / "real" / "muse_chat.json").is_file()  # the surprising answer is kept: that is the point


def test_a_missing_speech_engine_skips_the_voice_call_and_says_so(server, tmp_path):
    code, said = go(tmp_path, wav_source=lambda: None)
    assert "/v1/asr/transcribe" not in server.paths and said[2].startswith("voice: DIFFERS: skipped") and code == 1


def test_the_total_cap_stops_calls_before_they_are_sent(server, tmp_path):
    code, said = go(tmp_path, total_cap=0.0)
    assert server.paths == [] and code == 1 and all("token_cap_day" in line for line in said[:3])


def test_the_real_cap_is_ten_dollars():
    assert smoke.TOTAL_CAP_USD == 10.0


def test_the_checks_themselves(server):
    assert smoke.problems_chat(CHAT) == [] and smoke.problems_sam(SAM) == [] and smoke.problems_voice(VOICE) == []
    assert smoke.problems_chat({"choices": [{"message": {"content": " "}}]}) != []
    assert smoke.problems_sam({}) != [] and smoke.problems_voice({"transcript": 5}) != []
