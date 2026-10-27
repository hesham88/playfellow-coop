"""MuseBrain against a real fake server on 127.0.0.1: request shape, reply, error mapping, pinned URL, no proxy, no env CA,
the key never shown, and a daily budget that stops calls before they are sent. No real Meta call is ever made."""
from __future__ import annotations

import http.server
import json
import socket
import ssl
import threading

import pytest
from PIL import Image

from brain import BrainError
from playfellow_coop import muse_brain
from playfellow_coop.budget import DailyBudget
from playfellow_coop.muse_brain import MuseBrain

SECRET = "muse-test-key-S3cr3tValue"
IMAGE = Image.new("RGB", (16, 12), (10, 20, 30))


class _Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        length = int(self.headers.get("Content-Length") or 0)
        body = self.rfile.read(length)
        self.server.hits.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": json.loads(body or b"{}")})
        status, payload = self.server.script.pop(0) if self.server.script else (200, self.server.default)
        data = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


def _answer(text, prompt_tokens=100, completion_tokens=20):
    return {"choices": [{"message": {"role": "assistant", "content": text}}],
            "usage": {"prompt_tokens": prompt_tokens, "completion_tokens": completion_tokens}}


REPLY = json.dumps({"thought": "go", "say": "", "actions": ["UP"]})


def _serve(handler=_Handler, wrap=None):
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    srv.hits, srv.script, srv.default = [], [], _answer(REPLY)
    if wrap is not None:
        srv.socket = wrap.wrap_socket(srv.socket, server_side=True)
    srv.thread = threading.Thread(target=srv.serve_forever, daemon=True)
    srv.thread.start()
    return srv


def _stop(srv):
    srv.shutdown()
    srv.server_close()
    srv.thread.join(timeout=5)


@pytest.fixture
def server():
    srv = _serve()
    yield srv
    _stop(srv)


@pytest.fixture
def brain(server, monkeypatch, tmp_path):
    monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", f"http://127.0.0.1:{server.server_address[1]}/v1")
    made = []

    def make(**kw):
        kw.setdefault("budget", DailyBudget(tmp_path / "budget.json", cap_usd=5.0, max_calls=100))
        b = MuseBrain("muse-spark", SECRET, **kw)
        made.append(b)
        return b

    yield make
    for b in made:
        b.close()


def test_a_question_is_sent_in_the_openai_shape_and_the_answer_comes_back(brain, server):
    answer = brain().ask("SYSTEM TEXT", "what now?", [IMAGE, IMAGE])
    assert answer == REPLY
    (hit,) = server.hits
    assert hit["path"] == "/v1/chat/completions" and hit["auth"] == f"Bearer {SECRET}"
    body = hit["body"]
    assert body["model"] == "muse-spark" and body["messages"][0] == {"role": "system", "content": "SYSTEM TEXT"}
    parts = body["messages"][1]["content"]
    assert parts[0] == {"type": "text", "text": "what now?"}
    urls = [p["image_url"]["url"] for p in parts[1:]]
    assert len(urls) == 2 and all(u.startswith("data:image/jpeg;base64,") for u in urls)


def test_the_price_of_each_call_is_counted_from_the_providers_own_token_counts(brain, server, tmp_path):
    brain().ask("s", "t", [IMAGE])
    saved = json.loads((tmp_path / "budget.json").read_text(encoding="utf-8"))
    assert saved["calls"] == 1 and saved["spent_usd"] == pytest.approx(100 * 1.25e-6 + 20 * 4.25e-6)


@pytest.mark.parametrize("status,key,retry", [(401, "bad_key", False), (403, "bad_key", False), (429, "busy", True),
                                              (500, "busy", True), (503, "busy", True), (400, "brain_trouble", False)])
def test_each_error_code_becomes_the_right_friendly_error(brain, server, status, key, retry):
    server.script.append((status, {"error": {"message": f"nope {SECRET}"}}))
    with pytest.raises(BrainError) as caught:
        brain().ask("s", "t", [IMAGE])
    assert caught.value.key == key and caught.value.retry is retry
    assert SECRET not in str(caught.value) and SECRET not in repr(caught.value) and SECRET not in caught.value.detail


def test_an_empty_answer_is_a_failure_not_a_blank_move(brain, server):
    server.script.append((200, _answer("")))
    with pytest.raises(BrainError) as caught:
        brain().ask("s", "t", [IMAGE])
    assert caught.value.key == "empty_answer"


def test_a_garbled_answer_body_is_a_brain_error(brain, server):
    server.script.append((200, {"unexpected": True}))
    with pytest.raises(BrainError):
        brain().ask("s", "t", [IMAGE])


def test_the_request_body_never_appears_in_an_error(brain, server):
    server.script.append((400, {"error": {"message": "bad request"}}))
    with pytest.raises(BrainError) as caught:
        brain().ask("PRIVATE-PROMPT-TEXT", "player said hello", [IMAGE])
    assert "PRIVATE-PROMPT-TEXT" not in repr(caught.value) and "player said hello" not in repr(caught.value)


def test_the_key_is_not_in_the_brains_repr_or_in_its_logs(brain, server, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        b = brain()
        b.ask("s", "t", [IMAGE])
    assert SECRET not in repr(b) and SECRET not in caplog.text


def test_a_proxy_variable_is_never_used(brain, server, monkeypatch):
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(0.3)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{listener.getsockname()[1]}")
    try:
        brain().ask("s", "t", [IMAGE])
        assert len(server.hits) == 1
        with pytest.raises(socket.timeout):
            listener.accept()
    finally:
        listener.close()


def _self_signed(host):
    """A throw-away self-signed certificate for a test server (this test's own helper; the engine's is not public)."""
    import datetime

    from cryptography import x509
    from cryptography.hazmat.primitives import hashes, serialization
    from cryptography.hazmat.primitives.asymmetric import rsa
    from cryptography.x509.oid import NameOID

    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, host)])
    now = datetime.datetime.now(datetime.timezone.utc)
    cert = (x509.CertificateBuilder().subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number()).not_valid_before(now - datetime.timedelta(minutes=5))
            .not_valid_after(now + datetime.timedelta(days=1))
            .add_extension(x509.SubjectAlternativeName([x509.IPAddress(__import__("ipaddress").ip_address(host))]), critical=False)
            .sign(key, hashes.SHA256()))
    return (cert.public_bytes(serialization.Encoding.PEM).decode("ascii"),
            key.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.TraditionalOpenSSL,
                              serialization.NoEncryption()).decode("ascii"))


def test_a_certificate_the_environment_vouches_for_is_not_trusted(monkeypatch, tmp_path):
    cert_pem, key_pem = _self_signed("127.0.0.1")
    (tmp_path / "c.pem").write_text(cert_pem, encoding="ascii")
    (tmp_path / "k.pem").write_text(key_pem, encoding="ascii")
    context = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
    context.load_cert_chain(tmp_path / "c.pem", tmp_path / "k.pem")
    srv = _serve(wrap=context)
    try:
        monkeypatch.setenv("SSL_CERT_FILE", str(tmp_path / "c.pem"))
        monkeypatch.setenv("REQUESTS_CA_BUNDLE", str(tmp_path / "c.pem"))
        monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", f"https://127.0.0.1:{srv.server_address[1]}/v1")
        b = MuseBrain("muse-spark", SECRET, budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=10))
        with pytest.raises(BrainError):
            b.ask("s", "t", [IMAGE])
        b.close()
        assert srv.hits == []
    finally:
        _stop(srv)


def test_a_redirect_is_refused_and_the_second_host_gets_nothing(server, monkeypatch, tmp_path):
    other = _serve()
    try:
        server.script.append((307, {}))
        original = _Handler.send_response

        def with_location(self, code, message=None):
            original(self, code, message)
            if code == 307:
                self.send_header("Location", f"http://127.0.0.1:{other.server_address[1]}/stolen")

        monkeypatch.setattr(_Handler, "send_response", with_location)
        monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", f"http://127.0.0.1:{server.server_address[1]}/v1")
        b = MuseBrain("muse-spark", SECRET, budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=10))
        with pytest.raises(BrainError):
            b.ask("s", "t", [IMAGE])
        b.close()
        assert other.hits == []
    finally:
        _stop(other)


def test_the_environment_cannot_move_the_endpoint(monkeypatch):
    for name in ("MUSE_BASE_URL", "OPENAI_BASE_URL", "MODEL_API_BASE", "META_API_BASE_URL"):
        monkeypatch.setenv(name, "http://203.0.113.9:9999")
    assert muse_brain.ENDPOINTS["muse"] == "https://api.meta.ai/v1"
    assert MuseBrain.endpoint() == "https://api.meta.ai/v1"


def test_the_daily_budget_stops_a_call_before_it_is_sent(brain, server, tmp_path):
    b = brain(budget=DailyBudget(tmp_path / "cap.json", cap_usd=0.0001, max_calls=100))
    b.ask("s", "t", [IMAGE])  # the first call is allowed and spends more than the cap
    sent = len(server.hits)
    with pytest.raises(BrainError) as caught:
        b.ask("s", "t", [IMAGE])
    assert caught.value.key == "token_cap_day" and len(server.hits) == sent  # nothing was sent


def test_the_call_count_cap_also_stops_calls(brain, server, tmp_path):
    b = brain(budget=DailyBudget(tmp_path / "n.json", cap_usd=100, max_calls=2))
    b.ask("s", "t", [IMAGE])
    b.ask("s", "t", [IMAGE])
    with pytest.raises(BrainError) as caught:
        b.ask("s", "t", [IMAGE])
    assert caught.value.key == "token_cap_day" and len(server.hits) == 2


def test_the_budget_starts_over_the_next_day_and_survives_a_restart(tmp_path):
    day = {"d": "2026-10-27"}
    first = DailyBudget(tmp_path / "d.json", cap_usd=1.0, max_calls=5, today=lambda: day["d"])
    first.record(prompt_tokens=1_000_000, completion_tokens=0)  # $1.25: over the cap
    assert DailyBudget(tmp_path / "d.json", cap_usd=1.0, max_calls=5, today=lambda: day["d"]).exhausted()
    day["d"] = "2026-10-28"
    assert not DailyBudget(tmp_path / "d.json", cap_usd=1.0, max_calls=5, today=lambda: day["d"]).exhausted()


def test_a_call_without_token_counts_is_charged_the_stated_estimate_and_flagged(brain, server, tmp_path):
    server.script.append((200, {"choices": [{"message": {"content": REPLY}}]}))
    b = brain(budget=DailyBudget(tmp_path / "e.json", cap_usd=5, max_calls=10, estimate_usd=0.02))
    b.ask("s", "t", [IMAGE])
    saved = json.loads((tmp_path / "e.json").read_text(encoding="utf-8"))
    assert saved["spent_usd"] == pytest.approx(0.02) and saved["estimated_calls"] == 1


def test_a_proxy_variable_is_not_even_offered_the_connection_to_a_named_host(monkeypatch, tmp_path):
    """The loopback test above can pass by accident (clients skip proxies for 127.0.0.1). A named host cannot."""
    listener = socket.socket()
    listener.bind(("127.0.0.1", 0))
    listener.listen(2)
    listener.settimeout(1.0)
    for name in ("HTTP_PROXY", "HTTPS_PROXY", "ALL_PROXY", "http_proxy", "https_proxy", "all_proxy"):
        monkeypatch.setenv(name, f"http://127.0.0.1:{listener.getsockname()[1]}")
    monkeypatch.delenv("NO_PROXY", raising=False)
    monkeypatch.delenv("no_proxy", raising=False)
    monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", "https://pinned-ai.example.test/v1")
    b = MuseBrain("muse-spark", SECRET, budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=10))
    try:
        with pytest.raises(BrainError):
            b.ask("s", "t", [IMAGE])
        with pytest.raises(socket.timeout):
            listener.accept()  # the proxy was never offered the connection
    finally:
        b.close()
        listener.close()


def test_the_default_model_is_the_standard_one_the_service_lists_and_a_contributor_model_is_refused():
    """Credit day, 27 Oct: the plain name 'muse-spark' answered 404 model_not_found; the service lists muse-spark-1.3. The '-contributor' models are cheaper
    because Meta trains on what is sent, so they must never carry play data (terms s.6.2)."""
    from playfellow_coop.muse_brain import DEFAULT_MODEL
    assert DEFAULT_MODEL == "muse-spark-1.3"
    for bad in ("muse-spark-1.3-contributor", "Muse-Spark-1.2-Contributor"):
        with pytest.raises(ValueError):
            MuseBrain(bad, "k")


def test_the_request_asks_for_minimal_reasoning_and_a_bad_effort_is_refused():
    """Credit day, 27 Oct: the same small request took 3 to 5 s and 600 to 1000 tokens at the default effort (and sometimes returned nothing at
    max_tokens 1000) against 1.4 s and about 170 tokens at 'minimal'."""
    import httpx
    seen = []

    def handler(request):
        seen.append(json.loads(request.content))
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 1, "completion_tokens": 1}})

    brain = MuseBrain("muse-spark-1.3", "k", client=httpx.Client(transport=httpx.MockTransport(handler)))
    brain.ask("system", "text", [])
    assert seen[0]["reasoning_effort"] == "minimal"
    with pytest.raises(ValueError):
        MuseBrain("muse-spark-1.3", "k", effort="none")
