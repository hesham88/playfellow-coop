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
from playfellow_coop import _http, backoff
from playfellow_coop.budget import INPUT_USD_PER_TOKEN, OUTPUT_USD_PER_TOKEN, DailyBudget

ENDPOINTS = {"muse": "https://api.meta.ai/v1"}  # pinned on purpose, like the engine's own brains
# The model the API really serves in Standard mode (found on credit day: the plain name "muse-spark" answers 404 model_not_found). The "-contributor"
# variants are cheaper because Meta trains on what is sent: never for play data (terms s.6.2), so they are refused below.
DEFAULT_MODEL = "muse-spark-1.3"
# muse-spark-1.3 thinks before it answers, and the thinking is billed as output. Credit day measured the same small request: default effort used 600 to 1000
# tokens in 3 to 5 s (and at max_tokens 1000 it sometimes ran out and answered nothing); "minimal" used about 170 tokens in 1.4 s with the same answer.
EFFORTS = ("minimal", "low", "medium", "high", "xhigh", "max")
DEFAULT_EFFORT = "minimal"
# Measured on credit day (27 Oct) on a real Practice Arena frame, same prompt: asked in plain words the answer came back as "down, down, down" and no JSON at all
# in 12.6 s; with response_format json_schema it was valid JSON in 3.4 s every time. And with a stable prompt_cache_key the second call served 881 of 971
# prompt tokens from the cache (about 91 percent; cached input costs $0.15 per million against $1.25). The cookbook's rules: stable content first, one shared
# key per shared prefix (never one per user), retention 24h for bursty play.
CACHE_KEY = "playfellow-coop-plan-v1"
CACHE_RETENTION = "24h"
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


def reasoning_tokens(usage) -> int | None:
    """The chain-of-thought tokens inside the output count (billed as output): `completion_tokens_details.reasoning_tokens` on Chat Completions."""
    details = usage.get("completion_tokens_details") if isinstance(usage, dict) else None
    value = details.get("reasoning_tokens") if isinstance(details, dict) else None
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


class MuseBrain:
    name = "muse"

    def __init__(self, model: str, api_key: str, budget: DailyBudget | None = None, client: httpx.Client | None = None,
                 effort: str = DEFAULT_EFFORT, cache_key: str | None = CACHE_KEY, base_url: str | None = None, auth_scheme: str = "Bearer",
                 retries: int = 0, sleeper=time.sleep, safety_id: str | None = None, breaker=None):
        if effort not in EFFORTS:
            raise ValueError(f"effort must be one of {EFFORTS}")
        self.effort = effort
        self.max_tokens = MAX_TOKENS  # a model that always reasons spends part of this on thinking; a subclass may raise it
        self.cache_key = cache_key
        # A subclass may name another pinned address (the open-weights bench brain does); a caller cannot pass one from the command line, and an address that is
        # not https is refused. The default is the pinned Meta address.
        self.base = base_url or ENDPOINTS["muse"]
        if (base_url is not None and not base_url.startswith("https://")) or auth_scheme not in ("Bearer", "Api-Key"):
            raise ValueError("a brain address must be https, and the key goes as Bearer or Api-Key")
        self.auth_scheme = auth_scheme
        self.retries = max(0, min(int(retries), 5))  # attempts after the first for a 429, 500 or 503 (never for a 4xx: the request must change)
        self._sleep = sleeper
        self.breaker = breaker  # optional circuit breaker (the engine's brain.breaker.CircuitBreaker): after repeated failures calls stop for a cool-down instead of hammering
        self.guard = backoff.RateGuard()  # reads the rate-limit headers of every answer and pauses before the limit is hit
        self.safety_id = safety_id  # a stable, privacy-preserving id of the end user (a hash, never a name or an e-mail), up to 64 characters
        self.actions: tuple[str, ...] | None = None
        self.skills: tuple[str, ...] | None = None  # the skill names the model may answer with (see playfellow_coop/skills)
        if "contributor" in model.lower():
            raise ValueError("a contributor model is trained on what it is sent; it is never used for play data")
        self.model = model
        self._key = api_key  # never shown: see __repr__
        self.budget = budget
        self._client = client or _http.new_client()
        self.last_usage: dict | None = None
        self.last_timings: dict | None = None  # seconds spent encoding the pictures and waiting for the service, per call
        self.last_request: dict = {}  # what the last call carried and cost (for the optional pf-trace/1 file): no words, no pictures

    def __repr__(self) -> str:
        return f"<MuseBrain model={self.model!r}>"

    def set_actions(self, names) -> None:
        """The keys the active controls card allows. With them set, the reply is constrained to {thought, say, actions[]} by a JSON schema, so a plan
        always parses and can only name an allowed key (the card still filters afterwards; this is a second wall, not the first)."""
        clean = tuple(dict.fromkeys(str(n) for n in names if isinstance(n, str) and 0 < len(n) <= 24 and "<" not in n))
        self.actions = clean or None

    def set_skills(self, names) -> None:
        """Tell the brain which skill names exist for this game; its answers may then carry one (strict schema)."""
        self.skills = tuple(names)

    def _schema(self) -> dict | None:
        if not self.actions:
            return None
        properties = {"thought": {"type": "string"}, "say": {"type": "string"},
                      "actions": {"type": "array", "items": {"type": "string", "enum": list(self.actions)}, "maxItems": 8}}
        if self.skills:
            properties["skill"] = {"type": "string", "enum": list(self.skills)}
        return {"type": "json_schema", "json_schema": {"name": "plan", "strict": True, "schema": {
            "type": "object", "additionalProperties": False, "required": list(properties), "properties": properties}}}

    @staticmethod
    def endpoint() -> str:
        return ENDPOINTS["muse"]

    def close(self) -> None:
        self._client.close()

    def _send(self, url: str, request: dict):
        """POST with the harness's error policy: pause when the rate-limit headers say the budget is nearly gone, retry 429, 500 and 503 with backoff and jitter
        (honouring Retry-After), never retry anything else. The answer of the last attempt is returned either way."""
        if self.breaker is not None and self.breaker.is_open():
            raise BrainError("busy", retry=True, wait_seconds=max(1.0, float(self.breaker.cooldown_seconds())))  # nothing is sent while the breaker is open
        pause = self.guard.wait_seconds()
        if pause:
            self._sleep(pause)
        attempt = 0
        while True:
            try:
                response = _http.post(self._client, url, self._key, request, scheme=self.auth_scheme)
            except BrainError as error:
                if self.breaker is not None:
                    self.breaker.record_error(error)
                raise
            self.guard.note(response.headers)
            if response.status_code < 400:
                if self.breaker is not None:
                    self.breaker.record_success()
            elif response.status_code in (429, 500, 502, 503, 504) and self.breaker is not None:
                self.breaker.record_error(BrainError("busy", retry=True))
            if response.status_code < 400 or attempt >= self.retries:
                return response
            try:
                body = response.json()
            except ValueError:
                body = None
            info = backoff.classify(response.status_code, body, response.headers)
            if info.kind != "retry":
                return response
            attempt += 1
            self._sleep(backoff.delay(attempt, info.retry_after))

    def count_input_tokens(self, system: str, text: str, images: list) -> int | None:
        """The exact number of input tokens this request would use on this model (images included), without generating anything: POST /responses/input_tokens.
        None when the service does not answer with a count. It measures context fit, not the bill."""
        content = [{"type": "input_text", "text": text}]
        for image in images:
            data = base64.standard_b64encode(to_jpeg_bytes(image)).decode("ascii")
            content.append({"type": "input_image", "image_url": f"data:image/jpeg;base64,{data}"})
        body = {"model": self.model, "input": [{"type": "message", "role": "system", "content": [{"type": "input_text", "text": system}]},
                                               {"type": "message", "role": "user", "content": content}]}
        response = self._send(self.base + "/responses/input_tokens", body)
        _http.check_status(response.status_code)
        try:
            count = response.json().get("input_tokens")
        except (ValueError, AttributeError):
            return None
        return count if isinstance(count, int) and not isinstance(count, bool) and count >= 0 else None

    def ask(self, system: str, text: str, images: list) -> str:
        """One planning call. An empty answer that did not come from running out of the output budget is a dropped or truncated stream, a transport failure and not the
        model's decision (cookbook: interleaved reasoning): the call is made once more before it is reported."""
        try:
            return self._ask_once(system, text, images)
        except BrainError as error:
            if error.key == "empty_answer" and (self.last_request or {}).get("finish_reason") != "length":
                return self._ask_once(system, text, images)
            raise

    def _ask_once(self, system: str, text: str, images: list) -> str:
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
        request = {"model": self.model, "max_tokens": self.max_tokens, "reasoning_effort": self.effort,
                   "messages": [{"role": "system", "content": system}, {"role": "user", "content": content}]}
        schema = self._schema()
        if schema is not None:
            request["response_format"] = schema
        if self.safety_id:
            request["safety_identifier"] = str(self.safety_id)[:64]
        if self.cache_key:
            request["prompt_cache_key"] = self.cache_key
            request["prompt_cache_retention"] = CACHE_RETENTION
        response = self._send(self.base + "/chat/completions", request)
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
                             "tokens_cached": cached_tokens(usage), "tokens_out": completion, "reasoning_tokens": reasoning_tokens(usage),
                             "finish_reason": choice.get("finish_reason") if isinstance(choice, dict) else None, "cost_usd": cost,
                             "encode_ms": self.last_timings["encode"] * 1000.0, "request_ms": self.last_timings["request"] * 1000.0}
        if not isinstance(answer, str) or not answer.strip():
            raise BrainError("empty_answer")
        return answer
