"""How to fail well against the Meta Model API: which errors to retry, how long to wait, and when to slow down before the limit.

From the docs (error handling, pricing and rate limits): never retry 400, 401, 402, 403, 404 or 413, because the request itself must change; retry 429, 500 and 503 with exponential backoff starting
at 0.5 s, doubling, plus jitter of up to 1 s, for at most 3 to 5 attempts; honour a Retry-After header (a 503 for overload says 60 s); a 504 is not retried unchanged (stream, lower the
reasoning effort, shorten the input, or run in the background). Every successful token response also carries `x-ratelimit-remaining-requests` and `x-ratelimit-remaining-tokens`, so a client can
slow down before it is rejected.
"""
from __future__ import annotations

import random
import threading
import time
from dataclasses import dataclass

PERMANENT = {400, 401, 402, 403, 404, 413}
RETRYABLE = {429, 500, 503}
BASE_DELAY = 0.5
JITTER = 1.0
MAX_DELAY = 60.0


@dataclass(frozen=True)
class ApiError:
    status: int
    kind: str  # "ok", "permanent", "retry", "reduce", "billing", "bad_key", "model_not_found", "other"
    error_type: str = ""
    code: str = ""
    message: str = ""
    retry_after: float | None = None


def parse_error(body) -> tuple[str, str, str]:
    """(type, code, message) from the API's error envelope; empty strings when there is none. The message is cut short: it is for a log, not a screen."""
    error = body.get("error") if isinstance(body, dict) else None
    if not isinstance(error, dict):
        return "", "", ""
    return str(error.get("type") or "")[:40], str(error.get("code") or "")[:40], str(error.get("message") or "")[:200]


def classify(status: int, body=None, headers=None) -> ApiError:
    error_type, code, message = parse_error(body)
    retry_after = _retry_after(headers)
    if 200 <= status < 300:
        return ApiError(status, "ok")
    if status == 402:
        kind = "billing"
    elif status == 401 or code == "invalid_api_key":
        kind = "bad_key"
    elif status == 404 and code in ("model_not_found", "file_not_found") or code == "model_not_found":
        kind = "model_not_found"
    elif status == 504 or code == "gateway_timeout":
        kind = "reduce"  # the same request will usually time out again: stream, lower the effort, shorten the input
    elif status in PERMANENT:
        kind = "permanent"
    elif status in RETRYABLE or code in ("service_overloaded", "backend_unavailable", "server_shutting_down"):
        kind = "retry"
    else:
        kind = "other"
    return ApiError(status, kind, error_type, code, message, retry_after)


def _retry_after(headers) -> float | None:
    if not headers:
        return None
    for key in ("retry-after", "Retry-After"):
        try:
            value = headers.get(key)
        except AttributeError:
            return None
        if value is not None:
            try:
                return max(0.0, min(float(value), MAX_DELAY))
            except ValueError:
                return None
    return None


def delay(attempt: int, retry_after: float | None = None, rng=random.random) -> float:
    """Seconds to wait before retry number `attempt` (1 is the first retry): 0.5 s doubling, plus up to 1 s of jitter, never less than a Retry-After the server asked for."""
    wait = min(MAX_DELAY, BASE_DELAY * (2 ** (attempt - 1))) + JITTER * rng()
    return max(wait, retry_after) if retry_after is not None else wait


class RateGuard:
    """Reads the rate-limit headers of each answer and says how long to pause before the next request so the team limit is not hit. Cheap, thread-safe, no network."""

    def __init__(self, low_requests: int = 20, low_tokens: int = 20000, pause: float = 1.0, clock=time.monotonic):
        self.low_requests, self.low_tokens, self.pause, self._clock = low_requests, low_tokens, pause, clock
        self.remaining_requests: int | None = None
        self.remaining_tokens: int | None = None
        self._lock = threading.Lock()

    def note(self, headers) -> None:
        def number(name):
            try:
                return int(float(headers.get(name)))
            except (AttributeError, TypeError, ValueError):
                return None
        with self._lock:
            requests, tokens = number("x-ratelimit-remaining-requests"), number("x-ratelimit-remaining-tokens")
            if requests is not None:
                self.remaining_requests = requests
            if tokens is not None:
                self.remaining_tokens = tokens

    def wait_seconds(self) -> float:
        """0 when there is room; `pause` when either budget is nearly gone."""
        with self._lock:
            low = (self.remaining_requests is not None and self.remaining_requests < self.low_requests) or \
                  (self.remaining_tokens is not None and self.remaining_tokens < self.low_tokens)
        return self.pause if low else 0.0
