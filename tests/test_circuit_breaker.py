"""The circuit breaker (K5): after repeated failures stop calling a struggling service, probe once, and close again on success."""
from __future__ import annotations

import httpx
import pytest

from brain import BrainError
from playfellow_coop import _http, backoff


class Clock:
    def __init__(self):
        self.t = 1000.0

    def __call__(self):
        return self.t


def make(threshold=3, cooldown=30.0, max_cooldown=100.0):
    clock = Clock()
    return backoff.CircuitBreaker(threshold=threshold, cooldown=cooldown, max_cooldown=max_cooldown, clock=clock, rng=lambda: 0.0), clock


def test_a_new_circuit_is_closed_and_lets_calls_through():
    cb, _ = make()
    assert cb.before("api.test") == 0.0 and cb.state("api.test") == "closed"


def test_it_opens_after_the_threshold_of_failures_in_a_row():
    cb, _ = make(threshold=3)
    cb.failure("api.test")
    cb.failure("api.test")
    assert cb.state("api.test") == "closed" and cb.before("api.test") == 0.0
    cb.failure("api.test")
    assert cb.state("api.test") == "open"
    assert cb.before("api.test") == pytest.approx(30.0)


def test_a_success_in_between_resets_the_count():
    cb, _ = make(threshold=3)
    for _ in range(2):
        cb.failure("api.test")
    cb.success("api.test")
    for _ in range(2):
        cb.failure("api.test")
    assert cb.state("api.test") == "closed"


def test_the_wait_shrinks_as_the_cooldown_runs_down():
    cb, clock = make(threshold=1, cooldown=30.0)
    cb.failure("api.test")
    clock.t += 12.0
    assert cb.before("api.test") == pytest.approx(18.0)


def test_after_the_cooldown_exactly_one_probe_gets_through():
    cb, clock = make(threshold=1, cooldown=30.0)
    cb.failure("api.test")
    clock.t += 30.5
    assert cb.state("api.test") == "half-open"
    assert cb.before("api.test") == 0.0      # the probe
    assert cb.before("api.test") > 0.0       # everybody else waits while it is in flight


def test_a_successful_probe_closes_the_circuit():
    cb, clock = make(threshold=1)
    cb.failure("api.test")
    clock.t += 31
    assert cb.before("api.test") == 0.0
    cb.success("api.test")
    assert cb.state("api.test") == "closed" and cb.before("api.test") == 0.0


def test_a_failed_probe_reopens_for_twice_as_long_up_to_the_cap():
    cb, clock = make(threshold=1, cooldown=30.0, max_cooldown=100.0)
    cb.failure("api.test")
    waits = []
    for _ in range(4):
        clock.t += 1000
        assert cb.before("api.test") == 0.0   # the probe
        cb.failure("api.test")                # fails again
        waits.append(round(cb.before("api.test")))
    assert waits == [60, 100, 100, 100]


def test_a_probe_with_no_verdict_does_not_leave_the_circuit_stuck():
    cb, clock = make(threshold=1)
    cb.failure("api.test")
    clock.t += 31
    assert cb.before("api.test") == 0.0
    cb.neutral("api.test")                    # the probe ended in a 504 or an unexpected error
    assert cb.before("api.test") == 0.0       # another caller may probe


def test_each_host_has_its_own_circuit():
    cb, _ = make(threshold=1)
    cb.failure("a.test")
    assert cb.state("a.test") == "open" and cb.state("b.test") == "closed" and cb.before("b.test") == 0.0


def test_jitter_spreads_the_reopen_time():
    clock = Clock()
    cb = backoff.CircuitBreaker(threshold=1, cooldown=40.0, clock=clock, rng=lambda: 1.0)
    cb.failure("api.test")
    assert cb.before("api.test") == pytest.approx(50.0)   # 40 s plus up to 25 percent


# ---------------- wired into the one HTTP client ----------------
class FakeClient:
    def __init__(self, *outcomes):
        self.outcomes = list(outcomes)
        self.calls = 0

    def post(self, url, **kwargs):
        self.calls += 1
        out = self.outcomes[min(self.calls - 1, len(self.outcomes) - 1)]
        if isinstance(out, Exception):
            raise out
        return httpx.Response(out, request=httpx.Request("POST", url))


URL = "https://api.example.test/v1/x"


def trip(client, n=5):
    for _ in range(n):
        try:
            _http.post(client, URL, "key", {})
        except BrainError:
            pass


def test_timeouts_open_the_circuit_and_then_the_client_is_not_called():
    client = FakeClient(httpx.ReadTimeout("slow"))
    trip(client, 5)
    assert client.calls == 5
    with pytest.raises(BrainError) as e:
        _http.post(client, URL, "key", {})
    assert client.calls == 5, "an open circuit fails fast without touching the network"
    assert e.value.retry and e.value.wait_seconds >= 1


def test_server_errors_count_but_a_client_error_proves_the_service_is_up():
    down = FakeClient(503)
    trip(down, 5)
    assert _http.BREAKER.state("api.example.test") == "open"
    _http.BREAKER.reset()
    up = FakeClient(503, 503, 400, 503, 503, 400)
    trip(up, 6)
    assert _http.BREAKER.state("api.example.test") == "closed"


def test_a_gateway_timeout_says_nothing_about_the_service():
    client = FakeClient(504)
    trip(client, 10)
    assert _http.BREAKER.state("api.example.test") == "closed"


def test_the_breaker_applies_to_multipart_posts_too():
    client = FakeClient(httpx.ConnectError("down"))
    for _ in range(5):
        with pytest.raises(BrainError):
            _http.post_files(client, URL, "key", {"file": ("a.wav", b"x")})
    with pytest.raises(BrainError):
        _http.post_files(client, URL, "key", {"file": ("a.wav", b"x")})
    assert client.calls == 5


def test_a_normal_answer_leaves_the_circuit_closed():
    client = FakeClient(200)
    for _ in range(10):
        assert _http.post(client, URL, "key", {}).status_code == 200
    assert _http.BREAKER.state("api.example.test") == "closed"
