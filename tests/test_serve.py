"""The tactical WebSocket session (without a socket or a GPU), the Truss handler's honesty, and the model routing matrix."""
from __future__ import annotations

import ast
import asyncio
import base64
import json
from pathlib import Path

import pytest
import yaml

from playfellow_coop.serve import routing
from playfellow_coop.serve.protocol import MAX_FRAME_BYTES, StreamingBlocks, TacticalSession

ROOT = Path(__file__).resolve().parents[1]
JPEG = base64.b64encode(b"\xff\xd8\xff fake jpeg bytes \xff\xd9").decode()
BLOCK = "<|action_start|>12 -4 0; w; w d; w d; w; ; <|action_end|>"


def run(coro):
    return asyncio.run(coro)


def pieces(text, size=7):
    async def gen(prompt, images):
        gen.prompts.append(prompt)
        gen.images.append(len(images))
        try:
            for i in range(0, len(text), size):
                yield text[i:i + size]
            gen.drained = True
        finally:
            gen.closed = True

    gen.prompts, gen.images, gen.drained, gen.closed = [], [], False, False
    return gen


def frame(i=1, **extra):
    return json.dumps({"type": "frame", "id": i, "jpeg": JPEG, **extra})


# ---- streaming parser ---------------------------------------------------------------------------------------------------------------
def test_blocks_are_found_in_text_that_arrives_in_pieces_and_a_half_written_tag_is_kept():
    parser = StreamingBlocks()
    out = []
    for piece in ["thinking <|act", "ion_start|>1 2 3; w<|action_", "end|> and <|action_start|>0 0 0; a<|action_end|>"]:
        out.extend(parser.feed(piece))
    assert out == ["<|action_start|>1 2 3; w<|action_end|>", "<|action_start|>0 0 0; a<|action_end|>"]
    assert StreamingBlocks().feed("no block at all") == []


# ---- the session --------------------------------------------------------------------------------------------------------------------
def test_the_first_complete_block_is_returned_at_once_with_its_time_and_the_stream_is_closed_not_drained():
    gen = pieces("Let me think about this carefully... " + BLOCK + " and many more words after the block that nobody needs " * 5)
    session = TacticalSession(gen)
    reply = run(session.handle(frame(7, goal="win the race", hud={"hp": 3, "lap": 1})))
    assert len(reply) == 1 and reply[0]["type"] == "chunk" and reply[0]["id"] == 7 and reply[0]["text"] == BLOCK and reply[0]["first_ms"] >= 0
    assert gen.closed and not gen.drained  # the rest of the generation was dropped
    assert "Goal: win the race" in gen.prompts[0] and "hp=3" in gen.prompts[0] and gen.prompts[0].startswith("You are the tactical controller")  # stable prefix first


def test_frames_are_kept_as_a_short_history_and_a_reset_clears_it():
    gen = pieces(BLOCK)
    session = TacticalSession(gen)
    for i in range(8):
        run(session.handle(frame(i)))
    assert gen.images[-1] == 5 and gen.images[0] == 1  # the newest frame plus four earlier ones, never more
    assert run(session.handle(json.dumps({"type": "reset"}))) == [{"type": "reset_ok"}]
    run(session.handle(frame(99)))
    assert gen.images[-1] == 1


def test_bad_client_messages_get_an_error_not_an_exception():
    session = TacticalSession(pieces(BLOCK))
    raws = ["not json", "[1, 2]", json.dumps({"type": "dance", "id": 3}), json.dumps({"type": "frame", "id": 4, "jpeg": "###"}), json.dumps({"type": "frame", "id": 5, "jpeg": ""})]
    assert [run(session.handle(raw))[0]["code"] for raw in raws] == ["bad_json", "bad_message", "unknown_type", "bad_image", "bad_image_size"]
    huge = base64.b64encode(b"x" * (MAX_FRAME_BYTES + 1)).decode()
    assert run(session.handle(json.dumps({"type": "frame", "id": 6, "jpeg": huge})))[0]["code"] == "bad_image_size"
    assert run(TacticalSession(pieces("no block here")).handle(frame(8)))[0]["code"] == "no_action_block"
    assert run(TacticalSession(pieces(BLOCK)).handle(frame(9, goal="x\x00\n" * 500)))[0]["type"] == "chunk"


# ---- the Truss deployment ----------------------------------------------------------------------------------------------------------
def test_the_truss_config_asks_for_a_websocket_and_the_handler_refuses_to_invent_actions_without_a_model():
    config = yaml.safe_load((ROOT / "deploy" / "partner_gpu" / "playfellow_tactical" / "config.yaml").read_text(encoding="utf-8"))
    assert config["runtime"]["transport"]["kind"] == "websocket" and config["resources"]["use_gpu"] is True
    source = (ROOT / "deploy" / "partner_gpu" / "playfellow_tactical" / "model" / "model.py").read_text(encoding="utf-8")
    ast.parse(source)
    namespace: dict = {}
    exec(compile(source, "model.py", "exec"), namespace)  # the handler module is plain Python; nothing here talks to a network or loads a model

    class Socket:
        def __init__(self):
            self.inbox, self.sent = [frame(1)], []

        async def receive_text(self):
            if not self.inbox:
                raise ConnectionError("closed")
            return self.inbox.pop(0)

        async def send_text(self, text):
            self.sent.append(json.loads(text))

    socket = Socket()
    handler = namespace["Model"]()
    handler.load()
    run(handler.websocket(socket))
    assert socket.sent and socket.sent[0]["code"] == "model_unavailable"


# ---- routing ------------------------------------------------------------------------------------------------------------------------
def test_the_router_picks_the_cheapest_allowed_model_per_role_and_never_one_that_trains_on_play_data():
    assert routing.route("strategic").id == "muse-spark-1.3" and routing.route("strategic", prefer="muse-wonder-1.0").id == "muse-wonder-1.0"
    assert routing.route("tactical").id == "muse-glimmer-30b" and routing.route("segmentation").id == "sam-3.1" and routing.route("verifier").id == "muse-glimmer-30b"
    assert routing.BY_ID["muse-spark-1.3-contributor"].trains_on_data
    for role in ("strategic", "tactical", "verifier"):
        assert not routing.route(role).trains_on_data
    assert routing.route("tactical", prefer="muse-spark-1.3-contributor").id != "muse-spark-1.3-contributor"  # asking for it by name does not get it


def test_zero_retention_and_latency_and_price_limits_change_the_choice_or_fail_loudly():
    assert routing.route("strategic", zero_retention=True).id == "muse-spark-open-816b" and routing.route("tactical", zero_retention=True).id == "muse-glimmer-30b"
    with pytest.raises(routing.NoModel):
        routing.route("segmentation", zero_retention=True)
    assert routing.route("tactical", max_first_token_ms=100).id == "muse-glimmer-30b"
    with pytest.raises(routing.NoModel):
        routing.route("strategic", max_first_token_ms=100)
    with pytest.raises(routing.NoModel):
        routing.route("strategic", max_call_usd=0.0001)
    with pytest.raises(ValueError):
        routing.route("mentor")
    assert routing.plan_for()["strategic"] == "muse-spark-1.3" and routing.plan_for(zero_retention=True)["segmentation"] == "none"
    assert routing.BY_ID["muse-wonder-1.0"].call_usd(cached=True) == pytest.approx(0.0092) and routing.BY_ID["muse-wonder-1.0"].call_usd(cached=False) == pytest.approx(0.0244)
