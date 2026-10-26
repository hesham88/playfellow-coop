"""The one way this package talks to the Meta Model API: a plain httpx client that ignores proxy and CA environment variables
and refuses redirects, and one table that turns a status code into the engine's friendly BrainError."""
from __future__ import annotations

import ssl

import certifi
import httpx

from brain import BrainError

REQUEST_TIMEOUT = 25.0


def new_client() -> httpx.Client:
    # trust_env=False: no HTTP_PROXY and friends; verify with certifi only, never SSL_CERT_FILE; no redirects.
    return httpx.Client(trust_env=False, follow_redirects=False, timeout=REQUEST_TIMEOUT,
                        verify=ssl.create_default_context(cafile=certifi.where()))


def post(client: httpx.Client, url: str, key: str, body: dict) -> httpx.Response:
    """POST JSON with the key as a header. A network failure becomes a BrainError that never quotes the request."""
    try:
        return client.post(url, json=body, headers={"Authorization": f"Bearer {key}"})
    except httpx.TimeoutException:
        raise BrainError("busy", retry=True, wait_seconds=5) from None
    except httpx.HTTPError:
        raise BrainError("offline", retry=True, wait_seconds=5) from None


def post_files(client: httpx.Client, url: str, key: str, files: dict) -> httpx.Response:
    """POST multipart parts (for audio). The same error handling as post(): nothing from the request is ever quoted."""
    try:
        return client.post(url, files=files, headers={"Authorization": f"Bearer {key}", "Accept": "application/json"})
    except httpx.TimeoutException:
        raise BrainError("busy", retry=True, wait_seconds=5) from None
    except httpx.HTTPError:
        raise BrainError("offline", retry=True, wait_seconds=5) from None


def check_status(status: int) -> None:
    """Raise the friendly error for a bad status; return for a good one."""
    if 300 <= status < 400:
        raise BrainError("brain_trouble", detail="the service tried to send the request somewhere else")
    if status in (401, 403):
        raise BrainError("bad_key")
    if status == 429:
        raise BrainError("busy", retry=True, wait_seconds=10)
    if status >= 500:
        raise BrainError("busy", retry=True, wait_seconds=5)
    if status >= 400:
        raise BrainError("brain_trouble", detail=f"the service answered {status}")
