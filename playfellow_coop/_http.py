"""The one way this package talks to the Meta Model API: a plain httpx client that ignores proxy and CA environment variables
and refuses redirects, and one table that turns a status code into the engine's friendly BrainError.

Every request goes through one circuit breaker per host (backoff.CircuitBreaker): after repeated failures it stops sending and
says how long to wait, instead of hammering a service that is struggling."""
from __future__ import annotations

import ssl
from urllib.parse import urlsplit

import certifi
import httpx

from brain import BrainError
from playfellow_coop import backoff

REQUEST_TIMEOUT = 25.0
BREAKER = backoff.CircuitBreaker()


def new_client() -> httpx.Client:
    # trust_env=False: no HTTP_PROXY and friends; verify with certifi only, never SSL_CERT_FILE; no redirects.
    return httpx.Client(trust_env=False, follow_redirects=False, timeout=REQUEST_TIMEOUT,
                        verify=ssl.create_default_context(cafile=certifi.where()))


def _send(call, url: str) -> httpx.Response:
    """Run one request through the circuit breaker. A network failure becomes a BrainError that never quotes the request."""
    host = urlsplit(url).hostname or url
    wait = BREAKER.before(host)
    if wait > 0:  # open circuit: fail fast, do not touch the network
        raise BrainError("busy", retry=True, wait_seconds=min(60, max(1, round(wait))))
    try:
        response = call()
    except httpx.TimeoutException:
        BREAKER.failure(host)
        raise BrainError("busy", retry=True, wait_seconds=5) from None
    except httpx.HTTPError:
        BREAKER.failure(host)
        raise BrainError("offline", retry=True, wait_seconds=5) from None
    except Exception:
        BREAKER.neutral(host)
        raise
    status = getattr(response, "status_code", None)
    if not isinstance(status, int) or status == 504:  # a 504 says the request ran long, not that the service is down
        BREAKER.neutral(host)
    elif status == 429 or status >= 500:
        BREAKER.failure(host)
    else:
        BREAKER.success(host)  # any other answer, even a 400 or a 401, proves the service is up
    return response


def post(client: httpx.Client, url: str, key: str, body: dict, scheme: str = "Bearer") -> httpx.Response:
    """POST JSON with the key as a header. A network failure becomes a BrainError that never quotes the request."""
    return _send(lambda: client.post(url, json=body, headers={"Authorization": f"{scheme} {key}"}), url)


def post_files(client: httpx.Client, url: str, key: str, files: dict) -> httpx.Response:
    """POST multipart parts (for audio). The same error handling as post(): nothing from the request is ever quoted."""
    return _send(lambda: client.post(url, files=files, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"}), url)


def check_status(status: int) -> None:
    """Raise the friendly error for a bad status; return for a good one."""
    if 300 <= status < 400:
        raise BrainError("brain_trouble", detail="the service tried to send the request somewhere else")
    if status == 402:
        raise BrainError("brain_trouble", detail="the account has a billing problem: check the balance on the Model API account page")
    if status == 504:
        raise BrainError("brain_trouble", detail="the request ran too long: try a lower reasoning effort or a shorter input")
    if status in (401, 403):
        raise BrainError("bad_key")
    if status == 429:
        raise BrainError("busy", retry=True, wait_seconds=10)
    if status >= 500:
        raise BrainError("busy", retry=True, wait_seconds=5)
    if status >= 400:
        raise BrainError("brain_trouble", detail=f"the service answered {status}")
