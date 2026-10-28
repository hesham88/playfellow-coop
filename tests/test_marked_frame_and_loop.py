"""The marked Practice Arena frame, and the marks inside the composed loop (offline, fake SAM server)."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageChops

from playfellow_coop import sam_marks
from playfellow_coop.budget import DailyBudget
from playfellow_coop.fakes import FakeSam
from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker, mark_image
from playfellow_coop.stage_timer import StageTimer
from practice_arena.game import ArenaGame
from tests.test_session_and_handover import Brain, make, session

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import make_marked_frame  # noqa: E402


def test_the_demo_picture_is_a_real_marked_frame_and_says_it_is_fake(tmp_path):
    picture, words = make_marked_frame.make(tmp_path)
    marked = Image.open(picture).convert("RGB")
    plain = ArenaGame().render().convert("RGB")
    assert marked.size == plain.size and ImageChops.difference(marked, plain).getbbox() is not None  # marks really are drawn
    text = words.read_text(encoding="utf-8")
    assert "FAKE server" in text and "not SAM's accuracy" in text
    assert "[R1] = something good to get" in text and "[D1] = a way through" in text  # the engine's own legend words
    assert "FAKE" in picture.name  # the file name cannot be mistaken for a real SAM result


def test_with_a_marker_the_brain_gets_the_labels_and_the_marked_picture(tmp_path, monkeypatch):
    game = ArenaGame()
    with FakeSam(game, DEFAULT_PROMPTS) as fake:
        monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", fake.url)
        parts, cfg = make()
        parts.marker = SamMarker("k", budget=DailyBudget(tmp_path / "b.json", cap_usd=5, max_calls=100))
        parts.screen.grab = lambda box: game.render()  # the pretend screen shows the arena
        seen = {}

        def ask(system, text, images):
            seen["text"], seen["image"] = text, images[-1]
            return json.dumps({"thought": "", "say": "", "actions": []})

        parts.brain.ask = ask
        timer = StageTimer()
        parts.safety.start()
        timer.begin_turn()
        session.take_turn(parts, cfg, "system", timer)
        turn = timer.end_turn()
        parts.marker.close()
    # the labels change every turn, so they come LAST (prompt caching matches from the start: the stable goal and rules lead)
    assert seen["text"].startswith("The goal:") and "Labels drawn on the picture:" in seen["text"] and "[ME] = you" in seen["text"]
    assert seen["text"].index("The goal:") < seen["text"].index("Labels drawn on the picture:")
    assert "mark" in turn and turn["mark"] > 0
    plain = Image.new("RGB", seen["image"].size)
    assert ImageChops.difference(seen["image"].convert("RGB"), plain).getbbox() is not None


def test_without_a_marker_the_loop_is_unchanged_and_has_no_mark_stage():
    parts, cfg = make()
    timer = StageTimer()
    parts.safety.start()
    timer.begin_turn()
    session.take_turn(parts, cfg, "system", timer)
    assert "mark" not in timer.end_turn()


def test_a_marker_that_finds_nothing_leaves_the_picture_and_the_prompt_alone():
    image = Image.new("RGB", (64, 64), (5, 5, 5))
    out, words = mark_image(image, lambda img: [])
    assert out is image and words == ""
    assert pytest is not None and Brain is not None
