"""The prompt's stable prefix. A provider's prompt cache can only hit text that is byte-identical at the START of every request, so the
system prompt (the buddy's rules and the game's controls card) must never change between turns, and everything that does change
(the marks legend, the recent steps, what the player said, the pictures) must come after it, the newest picture last.

The golden hash below pins the system prompt for the Practice Arena card with default settings. If it fails, the engine's wording changed:
that is not automatically wrong, but it breaks every cached prefix, so look at the change, then update the hash on purpose."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path

import controls
import play
import settings as engine_settings
from PIL import Image

from playfellow_coop import session, trace
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.stage_timer import StageTimer
from tests.test_session_and_handover import make
from tests.test_smoke import server  # noqa: F401  (server is a fixture)

GOLDEN_SYSTEM_SHA256 = "85503d7830b8455888a40e56e9308382e76e828a6e4d3b079f57e0d555e402c0"
REPLY = json.dumps({"thought": "t", "say": "", "actions": []})


def card():
    return controls.load_card(Path(os.environ["PLAYFELLOW_ENGINE"]) / "controls" / "practice_arena.yaml")


def system_text(**changes) -> str:
    parts = type("P", (), {})()
    parts.card = card()
    return play.system_for(parts, engine_settings.Settings(**changes))


def test_the_system_prompt_matches_the_golden_hash():
    assert hashlib.sha256(system_text().encode("utf-8")).hexdigest() == GOLDEN_SYSTEM_SHA256, (
        "the system prompt changed: the provider's prompt cache will miss until it is stable again; review the change, then update the hash")


def test_the_system_prompt_does_not_depend_on_anything_that_changes_between_turns():
    base = system_text()
    assert system_text() == base
    for turn_level in ({"goal": "Find the door instead."}, {"look_every_seconds": 5.0}, {"image_width": 480}):
        assert system_text(**turn_level) == base, turn_level  # the goal, the pace and the picture size are not part of the system prompt


def test_the_system_prompt_holds_the_controls_card_and_the_rules():
    text = system_text()
    assert "You control the game ONLY with these actions" in text and "Answer with JSON only" in text
    assert "UP" in text and "Every turn:" in text


def test_the_trace_hash_of_the_system_prompt_is_the_golden_hash():
    assert trace.prefix_hash(system_text()) == GOLDEN_SYSTEM_SHA256


def test_on_the_wire_the_system_prompt_is_first_and_identical_on_every_turn_and_the_newest_picture_is_last(server, tmp_path):  # noqa: F811
    server.answers["/chat/completions"] = {"choices": [{"message": {"content": REPLY}}], "usage": {"prompt_tokens": 10, "completion_tokens": 2}}
    parts, cfg = make()
    parts.card = card()
    parts.brain = MuseBrain("muse-spark", "k")
    parts.tracer = trace.Trace(tmp_path / "t.jsonl", "pin")
    system = play.system_for(parts, cfg)
    try:
        parts.safety.start()
        for turn in range(1, 4):
            parts.screen.grab = lambda box, shade=turn * 40: Image.new("RGB", (64, 48), (shade, shade, shade))  # a different picture each turn
            timer = StageTimer()
            timer.begin_turn()
            session.take_turn(parts, cfg, system, timer, chat=[f"say number {turn}"])
            timer.end_turn()
    finally:
        parts.brain.close()
        parts.tracer.close()
    bodies = [json.loads(b) for b, path in zip(server.bodies, server.paths) if path.endswith("/chat/completions")]
    assert len(bodies) == 3
    assert [b["messages"][0]["role"] for b in bodies] == ["system"] * 3
    assert len({b["messages"][0]["content"] for b in bodies}) == 1 and bodies[0]["messages"][0]["content"] == system  # byte-identical, first
    texts = [b["messages"][1]["content"][0] for b in bodies]
    assert all(part["type"] == "text" for part in texts) and len({part["text"] for part in texts}) == 3  # the part that changes follows the prefix
    images = [[p for p in b["messages"][1]["content"][1:]] for b in bodies]
    assert [len(i) for i in images] == [1, 2, 3] and all(p["type"] == "image_url" for group in images for p in group)  # pictures after the text
    assert images[2][-1] != images[1][-1] != images[0][-1]  # and the newest picture is the last one
    hashes = {json.loads(line)["prefix_hash"] for line in (tmp_path / "t.jsonl").read_text(encoding="utf-8").splitlines()[1:] if '"request"' in line}
    assert hashes == {trace.prefix_hash(system)}  # the trace says the same: one prefix, every request
