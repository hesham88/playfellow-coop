"""pf-trace/1: one JSON line per request (stage, model, prefix hash, tokens in / cached / out, latency, finish reason, cost, parse validity)
and one per turn. Off unless --trace is given. It never holds a picture, a word the player said, a key, a header, a path or a user name:
the writer takes only named, typed fields, so nothing else can reach the file (tested from every side)."""
from __future__ import annotations

import hashlib
import http.server
import json
import threading
from pathlib import Path

import pytest
from PIL import Image

from playfellow_coop import __main__ as entry
from playfellow_coop import muse_brain, realtime_voice, sam_marks, session, trace, voice
from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN, DailyBudget
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.realtime_voice import RealtimeTranscriber
from playfellow_coop.sam_marks import USD_PER_IMAGE, SamMarker
from playfellow_coop.stage_timer import StageTimer
from playfellow_coop.voice import CommandQueue, MuseVoiceTranscriber
from tests.test_realtime_voice import FakeRealtime
from tests.test_session_and_handover import MOVE, Brain, make
from tests.test_smoke import CHAT, SAM, VOICE, server, wav_bytes  # noqa: F401  (server is a fixture)
from tests.test_main import Parts

SYSTEM = "You are a buddy. Controls: UP DOWN LEFT RIGHT."
GOOD = json.dumps({"thought": "t", "say": "On my way.", "actions": [MOVE]})


def lines(path) -> list[dict]:
    return [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines()]


def new(tmp_path, trial="t1", name="run.trace.jsonl") -> trace.Trace:
    return trace.Trace(tmp_path / name, trial)


# ---- the writer ------------------------------------------------------------------------------------------------------------------
def test_the_file_opens_with_a_header_and_never_overwrites(tmp_path):
    log = new(tmp_path)
    log.close()
    head = lines(tmp_path / "run.trace.jsonl")[0]
    assert head["type"] == "header" and head["schema"] == "pf-trace/1" and head["trial"] == "t1" and head["started"]
    with pytest.raises(FileExistsError):
        trace.Trace(tmp_path / "run.trace.jsonl", "t1")


@pytest.mark.parametrize("bad", ["", "a b", "x" * 41, "../up", "C:" + "\\Users\\q", "a/b", "tab\there"])
def test_a_trial_id_must_be_a_short_plain_word(tmp_path, bad):
    with pytest.raises(ValueError):
        trace.Trace(tmp_path / "x.jsonl", bad)
    assert not (tmp_path / "x.jsonl").exists()


def test_a_request_line_holds_exactly_the_named_fields(tmp_path):
    log = new(tmp_path)
    log.request("plan", model="muse-spark", prefix=SYSTEM, images=2, image_bytes=12345, captured_px=(1920, 1080), sent_px=(640, 360),
                tokens_in=1000, tokens_cached=800, tokens_out=50, encode_ms=3.2, request_ms=410.5, parse_ms=0.4, finish_reason="stop",
                cost_usd=0.00146, parse={"valid": True, "dropped": 1, "actions": 2})
    log.close()
    got = lines(tmp_path / "run.trace.jsonl")[1]
    assert got == {"type": "request", "trial": "t1", "n": 1, "stage": "plan", "model": "muse-spark",
                   "prefix_hash": hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest(), "images": 2, "image_bytes": 12345,
                   "captured_px": [1920, 1080], "sent_px": [640, 360], "tokens": {"in": 1000, "cached": 800, "out": 50},
                   "latency_ms": {"encode": 3.2, "request": 410.5, "parse": 0.4}, "finish_reason": "stop", "cost_usd": 0.00146,
                   "parse": {"valid": True, "dropped": 1, "actions": 2}}
    assert SYSTEM not in json.dumps(got)  # only the hash of the prompt is kept, never its words


def test_requests_are_numbered_and_unknown_things_cannot_be_written(tmp_path):
    log = new(tmp_path)
    log.request("plan")
    log.request("marks")
    for extra in ("text", "image", "key", "headers", "path", "user", "prompt", "words"):
        with pytest.raises(TypeError):
            log.request("plan", **{extra: "anything"})
    with pytest.raises(ValueError):
        log.request("chat")  # not one of plan, marks, voice
    log.close()
    assert [r["n"] for r in lines(tmp_path / "run.trace.jsonl")[1:]] == [1, 2]


def test_odd_values_are_dropped_not_written(tmp_path):
    log = new(tmp_path)
    log.request("plan", model="C:" + "\\models\\m.gguf", tokens_in=-5, tokens_out="many", tokens_cached=True, request_ms=float("nan"),
                finish_reason="a free text reason with words", cost_usd="cheap", images=-1, parse={"valid": "yes", "dropped": "two", "extra": 1})
    log.close()
    got = lines(tmp_path / "run.trace.jsonl")[1]
    assert "model" not in got and "tokens" not in got and "latency_ms" not in got and "cost_usd" not in got and "images" not in got
    assert got["finish_reason"] == "other" and got["parse"] == {}


def test_finish_reasons_come_from_a_short_list(tmp_path):
    log = new(tmp_path)
    for reason in ("stop", "length", "content_filter", "tool_calls", "weird"):
        log.request("plan", finish_reason=reason)
    log.close()
    assert [r["finish_reason"] for r in lines(tmp_path / "run.trace.jsonl")[1:]] == ["stop", "length", "content_filter", "tool_calls", "other"]


def test_a_turn_line_keeps_only_plain_action_names_and_an_optional_outcome(tmp_path):
    log = new(tmp_path)
    log.turn(actions=["UP", "right", "say hello to bob@example.com", "C:" + "\\x"], won=None)
    log.turn(actions=[], won=True, progress=0.5, bumps=2)
    log.close()
    turn_a, turn_b = lines(tmp_path / "run.trace.jsonl")[1:]
    assert turn_a == {"type": "turn", "trial": "t1", "n": 1, "actions": ["UP", "right"]}
    assert turn_b == {"type": "turn", "trial": "t1", "n": 2, "actions": [], "won": True, "progress": 0.5, "bumps": 2}


def test_the_prefix_hash_is_the_sha256_of_the_system_text():
    assert trace.prefix_hash(SYSTEM) == hashlib.sha256(SYSTEM.encode("utf-8")).hexdigest() and len(trace.prefix_hash("")) == 64


# ---- what the Muse brain reports about its last request -----------------------------------------------------------------------
def test_the_muse_brain_reports_tokens_cached_tokens_finish_reason_cost_and_sizes(server, tmp_path):  # noqa: F811
    server.answers["/chat/completions"] = {"choices": [{"message": {"content": GOOD}, "finish_reason": "stop"}],
                                           "usage": {"prompt_tokens": 1000, "completion_tokens": 50, "prompt_tokens_details": {"cached_tokens": 800}}}
    brain = MuseBrain("muse-spark", "k", budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=50))
    try:
        brain.ask(SYSTEM, "where?", [Image.new("RGB", (64, 64)), Image.new("RGB", (32, 32))])
    finally:
        brain.close()
    got = brain.last_request
    assert got["model"] == "muse-spark" and (got["tokens_in"], got["tokens_cached"], got["tokens_out"]) == (1000, 800, 50)
    assert got["finish_reason"] == "stop" and got["images"] == 2 and got["image_bytes"] > 0
    assert got["cost_usd"] == pytest.approx(1000 * INPUT_USD_PER_TOKEN + 50 * OUTPUT_USD_PER_TOKEN)  # the budget's own prices
    assert got["encode_ms"] >= 0 and got["request_ms"] >= 0


def test_a_provider_that_reports_no_cache_figure_leaves_it_empty_and_other_spellings_are_read(server, tmp_path):  # noqa: F811
    for usage, expected in (({"prompt_tokens": 10, "completion_tokens": 2}, None), ({"prompt_tokens": 10, "completion_tokens": 2, "cached_tokens": 7}, 7),
                            ({"prompt_tokens": 10, "completion_tokens": 2, "prompt_cache_hit_tokens": 6}, 6)):
        server.answers["/chat/completions"] = {"choices": [{"message": {"content": GOOD}}], "usage": usage}
        brain = MuseBrain("muse-spark", "k")
        try:
            brain.ask(SYSTEM, "t", [])
        finally:
            brain.close()
        assert brain.last_request["tokens_cached"] == expected and brain.last_request["finish_reason"] is None
        assert brain.last_request["cost_usd"] == pytest.approx(10 * INPUT_USD_PER_TOKEN + 2 * OUTPUT_USD_PER_TOKEN)  # no budget: same prices


# ---- the turn loop writes the plan request -----------------------------------------------------------------------------------------
class Talker(Brain):
    def __init__(self, answer=GOOD, **report):
        super().__init__()
        self.answer, self.last_request = answer, report

    def ask(self, system, text, images):
        self.calls += 1
        return self.answer


def one_turn(parts, cfg):
    parts.safety.start()
    timer = StageTimer()
    timer.begin_turn()
    session.take_turn(parts, cfg, "SYSTEM-TEXT", timer)
    timer.end_turn()


def test_a_plan_request_gets_the_brains_figures_the_prefix_hash_and_the_parse_result(tmp_path):
    parts, cfg = make(Talker(model="muse-spark", tokens_in=900, tokens_cached=0, tokens_out=40, finish_reason="stop", cost_usd=0.001, request_ms=300.0))
    parts.tracer = new(tmp_path)
    one_turn(parts, cfg)
    parts.tracer.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "plan" and request["model"] == "muse-spark" and request["tokens"] == {"in": 900, "cached": 0, "out": 40}
    assert request["prefix_hash"] == trace.prefix_hash("SYSTEM-TEXT") and request["finish_reason"] == "stop"
    assert request["parse"] == {"valid": True, "dropped": 0, "actions": 1} and request["latency_ms"]["parse"] >= 0
    assert request["captured_px"] and request["sent_px"]  # the picture's size before and after the shrink, never the picture
    turn = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "turn"][0]
    assert turn["actions"] == [MOVE]


def test_an_unreadable_answer_and_an_off_card_action_are_counted_in_the_parse_result(tmp_path):
    parts, cfg = make(Talker(answer="not json at all"))
    parts.tracer = new(tmp_path, name="a.jsonl")
    one_turn(parts, cfg)
    parts.tracer.close()
    assert [r["parse"] for r in lines(tmp_path / "a.jsonl") if r["type"] == "request"] == [{"valid": False, "dropped": 0, "actions": 0}]
    parts, cfg = make(Talker(answer=json.dumps({"thought": "", "say": "", "actions": [MOVE, "TELEPORT"]})))
    parts.tracer = new(tmp_path, name="b.jsonl")
    one_turn(parts, cfg)
    parts.tracer.close()
    assert [r["parse"] for r in lines(tmp_path / "b.jsonl") if r["type"] == "request"] == [{"valid": True, "dropped": 1, "actions": 1}]


def test_a_brain_that_reports_nothing_still_gets_a_line(tmp_path):
    parts, cfg = make(Talker())
    parts.brain.last_request = {}
    parts.tracer = new(tmp_path)
    one_turn(parts, cfg)
    parts.tracer.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "plan" and "tokens" not in request and request["parse"]["valid"] is True


def test_without_a_tracer_nothing_changes_and_nothing_is_written(tmp_path, monkeypatch):
    monkeypatch.chdir(tmp_path)
    parts, cfg = make(Talker())
    one_turn(parts, cfg)
    assert parts.hands.pressed == [MOVE] and list(tmp_path.iterdir()) == []


def test_a_failed_request_is_recorded_with_its_error_key_and_no_cost(tmp_path):
    from brain import BrainError

    class Failing(Brain):
        def ask(self, system, text, images):
            raise BrainError("busy", retry=True, wait_seconds=0)

    parts, cfg = make(Failing())
    parts.tracer = new(tmp_path)
    session.play_session(parts, cfg, "SYSTEM-TEXT", StageTimer(), max_turns=1, wait=lambda s: True)
    parts.tracer.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "plan" and request["error"] == "busy" and request["parse"] == {"valid": False} and "cost_usd" not in request


# ---- marks and voice ------------------------------------------------------------------------------------------------------------------
def test_a_marks_request_records_one_image_its_size_the_price_and_whether_boxes_came_back(server, tmp_path):  # noqa: F811
    log = new(tmp_path)
    marker = SamMarker("k", prompts={"reward": "coin"}, budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=50), tracer=log)
    try:
        marks = marker(Image.new("RGB", (480, 432), (10, 90, 40)))
    finally:
        marker.close()
    log.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "marks" and request["model"] == sam_marks.MODEL and request["images"] == 1 and request["image_bytes"] > 0
    assert request["cost_usd"] == pytest.approx(USD_PER_IMAGE) and request["parse"] == {"valid": True, "boxes": len(marks)} and len(marks) == 1
    assert request["status"] == 200 and request["latency_ms"]["request"] >= 0


def test_a_marks_answer_with_no_boxes_is_not_valid_and_a_refused_one_costs_nothing(tmp_path):
    class Refusing(http.server.BaseHTTPRequestHandler):
        def do_POST(self):  # noqa: N802
            self.rfile.read(int(self.headers.get("Content-Length") or 0))
            self.send_response(500)
            self.send_header("Content-Length", "0")
            self.end_headers()

        def log_message(self, *args):
            pass

    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Refusing)
    thread = threading.Thread(target=srv.serve_forever, daemon=True)
    thread.start()
    old = sam_marks.ENDPOINTS["sam"]
    sam_marks.ENDPOINTS["sam"] = f"http://127.0.0.1:{srv.server_address[1]}/v1"
    log = new(tmp_path)
    marker = SamMarker("k", prompts={"reward": "coin"}, tracer=log)
    try:
        marker(Image.new("RGB", (64, 64)))
    finally:
        marker.close()
        sam_marks.ENDPOINTS["sam"] = old
        srv.shutdown()
        srv.server_close()
        thread.join(timeout=5)
    log.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["status"] == 500 and request["parse"] == {"valid": False} and "cost_usd" not in request


def test_a_voice_file_request_records_the_clip_length_and_its_cost(server, tmp_path):  # noqa: F811
    log = new(tmp_path)
    transcriber = MuseVoiceTranscriber("k", budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=50), tracer=log)
    try:
        transcriber.transcribe(wav_bytes(), keywords=["coins"])
    finally:
        transcriber.close()
    log.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "voice" and request["model"] == voice.MODEL and request["audio_ms"] == 1500
    assert request["cost_usd"] == pytest.approx(1.5 / 3600 * voice.USD_PER_HOUR) and request["parse"] == {"valid": True}
    assert "grab the coins" not in json.dumps(request)  # what was said is never kept


def test_a_realtime_request_records_the_time_to_the_first_partial(tmp_path):
    log = new(tmp_path)
    with FakeRealtime() as fake:
        realtime_voice.ENDPOINTS["realtime"], old = fake.url, realtime_voice.ENDPOINTS["realtime"]
        try:
            RealtimeTranscriber("k", tracer=log).transcribe([b"\x01\x00" * 2400] * 3)
        finally:
            realtime_voice.ENDPOINTS["realtime"] = old
    log.close()
    request = [r for r in lines(tmp_path / "run.trace.jsonl") if r["type"] == "request"][0]
    assert request["stage"] == "voice" and request["model"] == realtime_voice.MODEL and request["audio_ms"] == pytest.approx(300.0)
    assert request["latency_ms"]["first_partial"] >= 0 and request["parse"] == {"valid": True}
    assert "grab" not in json.dumps(request)


# ---- privacy, from every side ----------------------------------------------------------------------------------------------------------
def test_a_whole_session_leaves_no_picture_word_key_path_or_name_in_the_trace(tmp_path, monkeypatch):
    monkeypatch.setattr("playfellow_coop.session_log.getpass.getuser", lambda: "Quentin")
    secret_words = "my mail is q" + "@example.com and my key is sk-" + "z9" * 15
    q = CommandQueue()
    q.put(secret_words)
    answer = json.dumps({"thought": "see " + "C:" + "\\Users\\Quentin\\x.txt", "say": "Quentin, go to the door", "actions": [MOVE]})
    parts, cfg = make(Talker(answer=answer, model="muse-spark", tokens_in=5, tokens_out=5))
    parts.tracer = new(tmp_path, trial="priv1")
    session.play_session(parts, cfg, "SYSTEM-TEXT", StageTimer(), commands=q, max_turns=2, wait=lambda s: False)
    parts.tracer.close()
    text = (tmp_path / "run.trace.jsonl").read_text(encoding="utf-8")
    for needle in ("example", "sk-", "my mail", "Quentin", "Users", "\\\\", "base64", "PNG", "JPEG", "Authorization", "Bearer", "go to the door",
                   str(tmp_path), "SYSTEM-TEXT"):
        assert needle not in text, needle
    assert len(lines(tmp_path / "run.trace.jsonl")) == 1 + 2 + 2  # header, two plan requests, two turns


# ---- --trace on the command line ---------------------------------------------------------------------------------------------------------
def _builder(cfg):
    return Parts()


def test_the_trace_is_off_unless_asked_for():
    parts, _ = entry.build([], build_parts=_builder, key_loader=lambda: None)
    assert getattr(parts, "trace_plan", None) is None


def test_trace_takes_a_bare_name_under_session_logs_and_a_trial_id():
    parts, _ = entry.build(["--trace", "t.jsonl", "--trial", "s1"], build_parts=_builder, key_loader=lambda: None)
    assert parts.trace_plan == {"path": Path("session-logs") / "t.jsonl", "trial": "s1"}
    parts, _ = entry.build(["--trace", "t.jsonl"], build_parts=_builder, key_loader=lambda: None)
    assert parts.trace_plan["trial"] == "trial"  # a plain default


def test_main_opens_the_trace_gives_it_to_the_parts_and_closes_it(tmp_path):
    path = tmp_path / "t.jsonl"
    seen = {}

    def build(argv):
        import settings

        parts = Parts()
        parts.marks_source = "off"
        parts.trace_plan = {"path": path, "trial": "s1"}
        return parts, settings.Settings()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        seen["tracer"] = p.tracer
        p.tracer.request("plan", model="muse-spark")
        return "round_done"

    assert entry.main([], build_fn=build, listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=lambda *a: None) == 0
    got = lines(path)
    assert got[0]["trial"] == "s1" and got[1]["stage"] == "plan" and seen["tracer"]._file.closed


def test_main_refuses_an_existing_trace_file_and_does_not_start(tmp_path):
    path = tmp_path / "t.jsonl"
    path.write_text("mine", encoding="utf-8")
    said = []

    def build(argv):
        import settings

        parts = Parts()
        parts.marks_source = "off"
        parts.trace_plan = {"path": path, "trial": "s1"}
        return parts, settings.Settings()

    def run(*a, **k):
        raise AssertionError("must not start")

    assert entry.main([], build_fn=build, listen_key=lambda *a: None, listen_stop=lambda cb: None, run=run, say=said.append) == 2
    assert path.read_text(encoding="utf-8") == "mine" and any("already exists" in line for line in said)
