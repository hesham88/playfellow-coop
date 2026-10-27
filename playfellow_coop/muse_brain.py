"""The Muse brain: asks a Muse model on the Meta Model API what to do next.

It follows the engine's one brain contract, `ask(system, text, images) -> str`, so the engine's own reply check still drops any
action that is not on the game's controls card. Safety rules for the screenshots it sends:
  - the address is pinned in ENDPOINTS: no environment variable can move it;
  - a plain httpx client with trust_env off and our own certificate roots: no proxy variable, no CA-bundle variable, no redirect;
  - the key is only ever held in memory and sent as a header; it is never in a repr, a log or an error;
  - Standard mode only (no contributor mode), and a daily budget that stops a call before it is sent."""
from __future__ import annotations

import base64
import time

import httpx

from brain import BrainError, to_jpeg_bytes
from playfellow_coop import _http
from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN, DailyBudget

ENDPOINTS = {"muse": "https://api.meta.ai/v1"}  # pinned on purpose, like the engine's own brains
REQUEST_TIMEOUT = 25.0
MAX_TOKENS = 1000


def cached_tokens(usage) -> int | None:
    """How many prompt tokens the provider says it served from its cache, or None when it says nothing. The field name is not yet
    verified against the real service, so the usual spellings are read; credit day shows which one is real."""
    if not isinstance(usage, dict):
        return None
    details = usage.get("prompt_tokens_details")
    for value in (details.get("cached_tokens") if isinstance(details, dict) else None, usage.get("cached_tokens"),
                  usage.get("prompt_cache_hit_tokens")):
        if isinstance(value, int) and not isinstance(value, bool) and value >= 0:
            return value
    return None


class MuseBrain:
    name = "muse"

    def __init__(self, model: str, api_key: str, budget: DailyBudget | None = None, client: httpx.Client | None = None):
        self.model = model
        self._key = api_key  # never shown: see __repr__
        self.budget = budget
        self._client = client or _http.new_client()
        self.last_usage: dict | None = None
        self.last_timings: dict | None = None  # seconds spent encoding the pictures and waiting for the service, per call
        self.last_request: dict = {}  # what the last call carried and cost (for the optional pf-trace/1 file): no words, no pictures

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
        started = time.perf_counter()
        content = [{"type": "text", "text": text}]
        picture_bytes = 0
        for image in images:
            jpeg = to_jpeg_bytes(image)
            picture_bytes += len(jpeg)
            data = base64.standard_b64encode(jpeg).decode("ascii")
            content.append({"type": "image_url", "image_url": {"url": f"data:image/jpeg;base64,{data}"}})
        encoded = time.perf_counter()
        request = {"model": self.model, "max_tokens": MAX_TOKENS,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        response = _http.post(self._client, ENDPOINTS["muse"] + "/chat/completions", self._key, request)
        self.last_timings = {"encode": encoded - started, "request": time.perf_counter() - encoded}  # measured here, inside
        _http.check_status(response.status_code)
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
            cost = self.budget.record(prompt, completion)
        else:
            cost = (prompt or 0) * INPUT_USD_PER_TOKEN + (completion or 0) * OUTPUT_USD_PER_TOKEN if (prompt or completion) else None
        choice = body["choices"][0]
        self.last_request = {"model": self.model, "images": len(images), "image_bytes": picture_bytes, "tokens_in": prompt,
                             "tokens_cached": cached_tokens(usage), "tokens_out": completion,
                             "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None, "cost_usd": cost,
                             "encode_ms": self.last_timings["encode"] * 1000.0, "request_ms": self.last_timings["request"] * 1000.0}
        if not isinstance(answer, str) or not answer.strip():
            raise BrainError("empty_answer")
        return answer
