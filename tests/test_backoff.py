"""The error policy from the docs: what to retry, how long to wait, when to slow down; and the brain using it."""
from __future__ import annotations

import json

import httpx
import pytest
from PIL import Image

from brain import BrainError
from playfellow_coop import _http, backoff
from playfellow_coop.muse_brain import MuseBrain, reasoning_tokens


def test_status_classes_follow_the_docs():
    assert backoff.classify(400).kind == "permanent" and backoff.classify(402).kind == "billing" and backoff.classify(401).kind == "bad_key"
    for status in (403, 413):
        assert backoff.classify(status).kind == "permanent"
    assert backoff.classify(404, {"error": {"code": "model_not_found"}}).kind == "model_not_found"
    assert backoff.classify(404).kind == "permanent"
    for status in (429, 500, 503):
        assert backoff.classify(status).kind == "retry"
    assert backoff.classify(504).kind == "reduce" and backoff.classify(200).kind == "ok"
    assert backoff.classify(503, {"error": {"code": "service_overloaded", "type": "server_error", "message": "busy"}}, {"Retry-After": "60"}).retry_after == 60.0


def test_the_error_envelope_is_read_and_cut_short():
    assert backoff.parse_error({"error": {"type": "invalid_request_error", "code": None, "message": "x" * 500}}) == ("invalid_request_error", "", "x" * 200)
    assert backoff.parse_error("not json") == ("", "", "")


def test_the_delay_doubles_adds_jitter_and_never_undercuts_retry_after():
    nothing = lambda: 0.0  # noqa: E731
    assert [backoff.delay(n, rng=nothing) for n in (1, 2, 3, 4)] == [0.5, 1.0, 2.0, 4.0]
    assert backoff.delay(1, rng=lambda: 1.0) == 1.5
    assert backoff.delay(1, retry_after=60.0, rng=nothing) == 60.0
    assert backoff.delay(20, rng=nothing) == 60.0  # capped


def test_the_rate_guard_slows_down_only_when_a_budget_is_nearly_gone():
    guard = backoff.RateGuard(low_requests=10, low_tokens=1000, pause=2.0)
    assert guard.wait_seconds() == 0.0
    guard.note({"x-ratelimit-remaining-requests": "2999", "x-ratelimit-remaining-tokens": "3999000"})
    assert guard.wait_seconds() == 0.0
    guard.note({"x-ratelimit-remaining-requests": "5"})
    assert guard.wait_seconds() == 2.0
    guard.note({"x-ratelimit-remaining-requests": "500", "x-ratelimit-remaining-tokens": "100"})
    assert guard.wait_seconds() == 2.0
    guard.note({"x-ratelimit-remaining-tokens": "bad"})  # an unreadable header changes nothing


def test_402_and_504_become_plain_friendly_errors():
    with pytest.raises(BrainError) as billing:
        _http.check_status(402)
    assert "billing" in str(billing.value.detail)
    with pytest.raises(BrainError) as slow:
        _http.check_status(504)
    assert "lower reasoning effort" in str(slow.value.detail)


def make(handler, **kw):
    sleeps = []
    brain = MuseBrain("muse-spark-1.3", "k", client=httpx.Client(transport=httpx.MockTransport(handler)), sleeper=sleeps.append, **kw)
    return brain, sleeps


OK = {"choices": [{"message": {"content": '{"thought":"","say":"","actions":[]}'}, "finish_reason": "stop"}],
      "usage": {"prompt_tokens": 100, "completion_tokens": 40, "prompt_tokens_details": {"cached_tokens": 64}, "completion_tokens_details": {"reasoning_tokens": 25}}}


def test_a_429_is_retried_with_backoff_honouring_retry_after_and_a_400_never_is():
    seen = []

    def handler(request):
        seen.append(1)
        if len(seen) < 3:
            return httpx.Response(429, json={"error": {"type": "rate_limit_error", "code": "rate_limit_exceeded"}}, headers={"Retry-After": "3"})
        return httpx.Response(200, json=OK)

    brain, sleeps = make(handler, retries=3)
    assert brain.ask("sys", "hi", [Image.new("RGB", (8, 8))])
    assert len(seen) == 3 and len(sleeps) == 2 and all(s >= 3.0 for s in sleeps)

    calls = []
    bad, sleeps = make(lambda r: calls.append(1) or httpx.Response(400, json={"error": {"type": "invalid_request_error"}}), retries=3)
    with pytest.raises(BrainError):
        bad.ask("sys", "hi", [Image.new("RGB", (8, 8))])
    assert len(calls) == 1 and sleeps == []  # a bad request is never sent again unchanged


def test_without_retries_one_failure_is_one_attempt_and_the_retry_count_is_bounded():
    calls = []
    brain, _ = make(lambda r: calls.append(1) or httpx.Response(503, json={}))
    with pytest.raises(BrainError):
        brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert len(calls) == 1
    assert MuseBrain("muse-spark-1.3", "k", retries=99).retries == 5


def test_the_guard_pauses_before_a_request_when_the_last_answer_said_the_budget_is_low():
    brain, sleeps = make(lambda r: httpx.Response(200, json=OK, headers={"x-ratelimit-remaining-requests": "3"}))
    brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert sleeps == []
    brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert sleeps == [1.0]


def test_reasoning_tokens_and_cached_tokens_are_recorded_and_the_safety_id_is_sent_when_set():
    sent = []

    def handler(request):
        sent.append(json.loads(request.content))
        return httpx.Response(200, json=OK)

    brain, _ = make(handler, safety_id="h" * 100)
    brain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert brain.last_request["reasoning_tokens"] == 25 and brain.last_request["tokens_cached"] == 64
    assert sent[0]["safety_identifier"] == "h" * 64
    plain, _ = make(handler)
    plain.ask("s", "t", [Image.new("RGB", (8, 8))])
    assert "safety_identifier" not in sent[1]
    assert reasoning_tokens({"completion_tokens_details": {"reasoning_tokens": True}}) is None and reasoning_tokens(None) is None


def test_the_input_token_count_asks_the_documented_endpoint_for_this_model():
    sent = []

    def handler(request):
        sent.append((request.url.path, json.loads(request.content)))
        return httpx.Response(200, json={"object": "response.input_tokens", "input_tokens": 1234})

    brain, _ = make(handler)
    assert brain.count_input_tokens("system words", "user words", [Image.new("RGB", (16, 16))]) == 1234
    path, body = sent[0]
    assert path.endswith("/responses/input_tokens") and body["model"] == "muse-spark-1.3"
    assert [m["role"] for m in body["input"]] == ["system", "user"] and body["input"][1]["content"][1]["type"] == "input_image"
    odd, _ = make(lambda r: httpx.Response(200, json={"input_tokens": "many"}))
    assert odd.count_input_tokens("s", "t", []) is None
