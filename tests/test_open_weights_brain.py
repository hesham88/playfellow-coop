"""The open-weights bench brain: pinned partner address, the partner's key scheme, the same schema and effort as the Muse brain, no cache key, an https-only rule."""
from __future__ import annotations

import json

import httpx
import pytest

from bench.open_weights_brain import OPEN_BASE, OPEN_MODEL, OpenWeightsBrain
from playfellow_coop.muse_brain import MuseBrain


def test_it_posts_to_the_pinned_address_with_the_partner_key_scheme_and_the_same_schema():
    seen = {}

    def handler(request):
        seen["url"], seen["auth"], seen["body"] = str(request.url), request.headers["authorization"], json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"finish_reason": "stop", "message": {"content": "{}"}}], "usage": {"prompt_tokens": 220, "completion_tokens": 190}})

    brain = OpenWeightsBrain("KEY", client=httpx.Client(transport=httpx.MockTransport(handler)))
    brain.set_actions(["up", "down"])
    brain.ask("system", "text", [])
    assert seen["url"] == OPEN_BASE + "/chat/completions" and seen["auth"] == "Api-Key KEY"
    assert seen["body"]["model"] == OPEN_MODEL and seen["body"]["reasoning_effort"] == "low"  # the hosted service runs minimal as low: we say low
    assert seen["body"]["response_format"]["json_schema"]["schema"]["properties"]["actions"]["items"]["enum"] == ["up", "down"]
    assert "prompt_cache_key" not in seen["body"]
    assert "KEY" not in repr(brain)


def test_the_default_muse_brain_is_unchanged_and_a_plain_http_address_is_refused():
    brain = MuseBrain("muse-spark-1.3", "k")
    assert brain.base == "https://api.meta.ai/v1" and brain.auth_scheme == "Bearer"
    with pytest.raises(ValueError):
        MuseBrain("m", "k", base_url="http://example.test/v1")
    with pytest.raises(ValueError):
        MuseBrain("m", "k", auth_scheme="Basic")


def test_the_open_brain_asks_for_a_bigger_answer_budget_because_its_thinking_counts_against_it():
    from bench.open_weights_brain import OPEN_MAX_TOKENS, OpenWeightsBrain
    from playfellow_coop.muse_brain import MAX_TOKENS, MuseBrain
    assert OpenWeightsBrain("k").max_tokens == OPEN_MAX_TOKENS > MAX_TOKENS == MuseBrain("m", "k").max_tokens


def test_the_open_weight_brain_maps_minimal_to_low_and_refuses_the_efforts_the_model_rejects():
    from bench.open_weights_brain import OpenWeightsBrain
    assert OpenWeightsBrain("k", effort="minimal").effort == "low" and OpenWeightsBrain("k").effort == "low"
    assert OpenWeightsBrain("k", effort="xhigh").effort == "xhigh"
    import pytest
    for bad in ("none", "max", "ludicrous"):
        with pytest.raises(ValueError):
            OpenWeightsBrain("k", effort=bad)
