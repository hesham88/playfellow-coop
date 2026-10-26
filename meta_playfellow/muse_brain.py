"""The Muse brain: asks a Muse model on the Meta Model API what to do next.

It follows the engine's one brain contract, `ask(system, text, images) -> str`, so the engine's own reply check still drops any
action that is not on the game's controls card. Safety rules for the screenshots it sends:
  - the address is pinned in ENDPOINTS: no environment variable can move it;
  - a plain httpx client with trust_env off and our own certificate roots: no proxy variable, no CA-bundle variable, no redirect;
  - the key is only ever held in memory and sent as a header; it is never in a repr, a log or an error;
  - Standard mode only (no contributor mode), and a daily budget that stops a call before it is sent."""
from __future__ import annotations

import base64
import ssl

import certifi
import httpx

from brain import BrainError, to_jpeg_bytes
from meta_playfellow.budget import DailyBudget

ENDPOINTS = {"muse": "https://api.meta.ai/v1"}  # pinned on purpose, like the engine's own brains
REQUEST_TIMEOUT = 25.0
MAX_TOKENS = 1000


class MuseBrain:
    name = "muse"

    def __init__(self, model: str, api_key: str, budget: DailyBudget | None = None, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key  # never shown: see __repr__
        self.budget = budget
        # trust_env=False: no HTTP_PROXY and friends; verify with certifi only, never SSL_CERT_FILE; no redirects.
        self._client = client or httpx.Client(trust_env=False, follow_redirects=False, timeout=REQUEST_TIMEOUT,
                                              verify=ssl.create_default_context(cafile=certifi.where()))
        self.last_usage: dict | None = None

    def __repr__(self) -> str:
        return f"<MuseBrain model={self.model!r}>"

    @staticmethod
    def endpoint() -> str:
        return ENDPOINTS["muse"]

    def close(self) -> None:
        self._client.close()

    def ask(self, system: str, text: str, images: list) -> str:
        if self.budget is not None and self.budget.exhausted():
            raise BrainError("token_cap_day")  # nothing is sent
        content = [{"type": "text", "text": text}]
        for image in images:
            data = base64.standard_b64encode(to_jpeg_bytes(image)).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
        request = {"model": self.model, "max_tokens": MAX_TOKENS,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        try:
            response = self._client.post(ENDPOINTS["muse"] + "/chat/completions", json=request,
                                         headers={"Authorization": f"Bearer {self._key}"})
        except httpx.TimeoutException:
            raise BrainError("busy", retry=True, wait_seconds=5) from None
        except httpx.HTTPError:
            raise BrainError("offline", retry=True, wait_seconds=5) from None  # no detail: it could quote the request
        status = response.status_code
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
        try:
            body = response.json()
            answer = body["choices"][0]["message"]["content"]
        except (ValueError, KeyError, IndexError, TypeError):
            raise BrainError("brain_trouble", detail="the answer was not in the expected shape") from None
        usage = body.get("usage") if isinstance(body, dict) else None
        prompt = usage.get("prompt_tokens") if isinstance(usage, dict) else None
        completion = usage.get("completion_tokens") if isinstance(usage, dict) else None
        self.last_usage = {"prompt_tokens": prompt, "completion_tokens": completion}
        if self.budget is not None:
            self.budget.record(prompt, completion)
        if not isinstance(answer, str) or not answer.strip():
            raise BrainError("empty_answer")
        return answer
