"""SAM marks against a fake server built from the Practice Arena's own truth. No credits, no Meta call."""
from __future__ import annotations

import json
import time

import pytest
from PIL import Image

from brain import BrainError
from meta_playfellow import sam_marks
from meta_playfellow.budget import DailyBudget
from meta_playfellow.fakes import FakeSam
from meta_playfellow.sam_eval import arena_truth, evaluate, score, tile_box
from meta_playfellow.sam_marks import DEFAULT_PROMPTS, SamMarker, answer_text, parse_boxes
from practice_arena.game import ArenaGame

KEY = "sam-test-key-S3cr3t"


@pytest.fixture
def game():
    return ArenaGame()


@pytest.fixture
def fake(game, monkeypatch):
    with FakeSam(game, DEFAULT_PROMPTS) as server:
        monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", server.url)
        yield server


def marker(tmp_path, **kw):
    kw.setdefault("budget", DailyBudget(tmp_path / "sam.json", cap_usd=5, max_calls=1000))
    return SamMarker(KEY, **kw)


def test_the_box_tokens_of_the_docs_are_parsed():
    text = "<1f>1<|box;x1=10;y1=20;x2=30;y2=60;w=100;h=200|><|mask;one_bit|> <1f>2<|box;x1=1.5;y1=2.5;x2=3;y2=4;w=100;h=200|>"
    assert parse_boxes(text) == [((10.0, 20.0, 30.0, 60.0), (100.0, 200.0)), ((1.5, 2.5, 3.0, 4.0), (100.0, 200.0))]
    assert parse_boxes("no boxes here") == []


def test_both_answer_wrappers_are_read():
    assert answer_text({"output_text": "A"}) == "A"
    assert answer_text({"output": [{"content": [{"text": "A"}, {"text": "B"}]}]}) == "A\nB"
    assert answer_text("junk") == "" and answer_text({}) == ""


def test_marks_from_the_fake_answer_match_the_arenas_truth(game, fake, tmp_path):
    m = marker(tmp_path)
    marks = m(game.render())
    result = evaluate(marker(tmp_path), [game], source="fake server")
    for kind in ("me", "reward", "door"):
        assert result["kinds"][kind]["precision"] == 1.0 and result["kinds"][kind]["recall"] == 1.0, kind
    assert {mark.kind for mark in marks} == {"me", "reward", "door"}
    assert "checks the harness only" in result["note"]
    m.close()


def test_the_request_has_the_sam_shape_and_a_png_data_url(game, fake, tmp_path):
    marker(tmp_path)(game.render())
    first = fake.requests[0]
    assert first["path"] == "/v1/responses" and first["body"]["model"] == "sam-3.1"
    parts = first["body"]["input"][0]["content"]
    assert parts[0]["type"] == "input_text" and parts[1]["type"] == "input_image"
    assert parts[1]["image_url"].startswith("data:image/png;base64,")


def test_keyframes_only_an_unchanged_picture_sends_nothing(game, fake, tmp_path):
    m = marker(tmp_path)
    frame = game.render()
    first = m(frame)
    sent = len(fake.requests)
    assert m(frame) == first and len(fake.requests) == sent  # the same picture: cached, no request, no cost
    game.press("right")
    m(game.render())
    assert len(fake.requests) > sent  # the player moved: the picture changed enough to ask again


def test_every_request_is_charged_at_the_published_per_image_price(game, fake, tmp_path):
    m = marker(tmp_path)
    m(game.render())
    saved = json.loads((tmp_path / "sam.json").read_text(encoding="utf-8"))
    assert saved["calls"] == len(DEFAULT_PROMPTS) and saved["spent_usd"] == pytest.approx(len(DEFAULT_PROMPTS) * 2.50 / 1000)


def test_the_budget_stops_requests_before_they_are_sent_and_play_keeps_the_last_marks(game, fake, tmp_path):
    budget = DailyBudget(tmp_path / "cap.json", cap_usd=0.004, max_calls=1000)  # room for one request, not for a second frame
    m = marker(tmp_path, budget=budget)
    first = m(game.render())
    sent = len(fake.requests)
    game.press("right")
    again = m(game.render())  # over the cap: a BrainError inside, swallowed, last marks returned
    assert len(fake.requests) == sent and m.last_error is not None and m.last_error.key == "token_cap_day"
    assert again == first


def test_a_failing_service_never_stops_play_and_the_error_is_kept(game, monkeypatch, tmp_path):
    with FakeSam(game, DEFAULT_PROMPTS) as server:
        monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", server.url)
        m = marker(tmp_path)
        good = m(game.render())
        server.server.RequestHandlerClass.do_POST = lambda self: (self.send_response(500), self.end_headers())
        game.press("right")
        marks = m(game.render())
    assert marks == good and m.last_error is not None and m.last_error.key == "busy"


def test_the_key_is_never_shown(game, fake, tmp_path, caplog):
    import logging

    with caplog.at_level(logging.DEBUG):
        m = marker(tmp_path)
        m(game.render())
    assert KEY not in repr(m) and KEY not in caplog.text


def test_false_alarms_and_misses_are_scored_as_such(game):
    truth = arena_truth(game)
    good = [m for ms in truth.values() for m in ms]
    from grounding import Mark

    noisy = good + [Mark("reward", 999, 999)]  # one invented coin
    result = score(noisy, truth)
    assert result["reward"]["fp"] == 1 and result["reward"]["recall"] == 1.0 and result["reward"]["precision"] < 1.0
    missing = score([m for m in good if m.kind != "door"], truth)
    assert missing["door"]["fn"] == 1 and missing["door"]["recall"] == 0.0 and missing["door"]["precision"] is None


def test_a_coin_is_found_once_even_if_two_marks_land_on_it(game):
    truth = arena_truth(game)
    coin = truth["reward"][0]
    from grounding import Mark

    result = score([coin, Mark("reward", coin.x + 5, coin.y)], truth)
    assert result["reward"]["tp"] == 1 and result["reward"]["fp"] == 1


def test_latency_is_measured_not_typed(game, fake, tmp_path):
    ticks = iter([0.0, 0.25, 1.0, 1.5, 2.0, 2.1, 3.0, 3.4])
    m = marker(tmp_path, clock=lambda: next(ticks))
    m(game.render())
    assert m.latencies == pytest.approx([0.25, 0.5, 0.1, 0.4])
    assert evaluate(m, [], source="SAM 3.1")["latency_p50_s"] == 0.25


def test_the_marker_is_pinned_to_its_address(monkeypatch):
    for name in ("SAM_BASE_URL", "OPENAI_BASE_URL", "MODEL_API_BASE"):
        monkeypatch.setenv(name, "http://203.0.113.9:9")
    assert sam_marks.ENDPOINTS["sam"] == "https://api.meta.ai/v1"
    assert tile_box((1, 1))[0] == 48 and time is not None


def test_the_marker_uses_the_shared_safe_client(tmp_path):
    m = marker(tmp_path)
    try:
        assert m._client._trust_env is False and m._client.follow_redirects is False  # no proxy variables, no redirects
    finally:
        m.close()
