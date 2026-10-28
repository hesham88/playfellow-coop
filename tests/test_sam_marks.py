"""SAM marks against a fake server built from the Practice Arena's own truth. No credits, no Meta call."""
from __future__ import annotations

import json
import time

import pytest
from PIL import Image

from brain import BrainError
from playfellow_coop import sam_marks
from playfellow_coop.budget import DailyBudget
from playfellow_coop.fakes import FakeSam
from playfellow_coop.sam_eval import arena_truth, evaluate, score, tile_box
from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker, answer_text, parse_boxes
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
    text = "<0f>1<|box;x1=10;y1=20;x2=30;y2=60;w=100;h=200|><|mask;x=0;y=0;data=5,5,!!!!|> <0f>2<|box;x1=1;y1=2;x2=3;y2=4;w=100;h=200|>"
    assert parse_boxes(text) == [((10.0, 20.0, 31.0, 61.0), (100.0, 200.0)), ((1.0, 2.0, 4.0, 5.0), (100.0, 200.0))]  # x2 and y2 are inclusive: right = x2 + 1
    assert parse_boxes("no boxes here") == []


def test_the_published_protocol_rules_fields_by_name_confidence_order_payload_text_and_bad_tokens():
    """github.com/meta-models/meta-sam protocol/sam3.md: fields are read by name in any order, an optional c is the confidence, a mask payload may hold text like
    'c=' that must not be taken for a field, and a malformed or outside-the-picture box is skipped."""
    from playfellow_coop.sam_marks import parse_records
    text = ("<7f>0<|box;h=80;w=100;y2=24;x2=14;y1=20;x1=10;c=0.75|><|mask;x=0;y=0;c=0.75;data=5,5,~!c=9;x1=1!!(QO|>"
            "<7f>1,<|mask;x=0;y=0;data=1,1,!!!!|><|box;x1=0;y1=0;x2=0;y2=0;w=10;h=10|>"      # the comma and the order of box and mask are free
            "<7f>2<|box;x1=a;y1=0;x2=3;y2=3;w=10;h=10|>"                                   # not a number: skipped
            "<7f>3<|box;x1=0;y1=0;x2=10;y2=3;w=10;h=10|>"                                   # runs outside the picture: skipped
            "<7f>4<|box;x1=1;y1=1;x2=2;y2=2;w=0;h=10|>")                                    # zero width: skipped
    records = parse_records(text)
    assert [r["confidence"] for r in records] == [0.75, None]
    assert records[0]["box"] == (10.0, 20.0, 15.0, 25.0) and records[0]["size"] == (100.0, 80.0)
    assert records[1]["box"] == (0.0, 0.0, 1.0, 1.0)


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


def test_a_failing_service_never_stops_play_and_the_error_is_kept(game, fake, tmp_path):
    m = marker(tmp_path)
    good = m(game.render())
    for phrase in DEFAULT_PROMPTS.values():
        fake.statuses[phrase] = 500
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
    import itertools
    import threading

    counter, lock = itertools.count(), threading.Lock()

    def clock():  # a clock that moves 0.5 s every time anyone reads it: the numbers come from the marker's own reads
        with lock:
            return next(counter) * 0.5

    m = marker(tmp_path, clock=clock)
    m(game.render())
    assert len(m.latencies) == 4 and all(seconds > 0 and seconds % 0.5 == 0 for seconds in m.latencies)
    assert len(m.keyframe_latencies) == 1 and m.keyframe_latencies[0] >= max(m.latencies)  # the whole keyframe takes at least its slowest request
    assert evaluate(m, [], source="SAM 3.1")["latency_p50_s"] == sorted(m.latencies)[1]


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


# ---- one encode, concurrent phrases, charge only on a 2xx -----------------------------------------------------------
def test_the_picture_is_encoded_once_and_every_phrase_gets_the_same_bytes(game, fake, tmp_path, monkeypatch):
    calls = []
    real = sam_marks.base64.standard_b64encode
    monkeypatch.setattr(sam_marks.base64, "standard_b64encode", lambda data: calls.append(len(data)) or real(data))
    marker(tmp_path)(game.render())
    assert len(calls) == 1 and len(fake.requests) == len(DEFAULT_PROMPTS)
    urls = {r["body"]["input"][0]["content"][1]["image_url"] for r in fake.requests}
    assert len(urls) == 1  # four requests, one picture


def test_the_phrases_are_asked_at_the_same_time(game, fake, tmp_path):
    fake.delay = 0.3
    m = marker(tmp_path)
    m(game.render())
    assert len(fake.requests) == 4 and m.keyframe_latencies[0] < 0.9  # four in a row would take at least 1.2 s


@pytest.mark.parametrize("status", [401, 403, 429, 500])
def test_a_request_that_was_not_answered_with_a_2xx_is_never_charged(game, fake, tmp_path, status):
    for phrase in DEFAULT_PROMPTS.values():
        fake.statuses[phrase] = status
    m = marker(tmp_path)
    m(game.render())
    assert m.calls == 4 and m.failed_calls == 4 and m.last_error is not None
    saved = tmp_path / "sam.json"
    spent = json.loads(saved.read_text(encoding="utf-8"))["spent_usd"] if saved.is_file() else 0.0
    assert spent == 0.0  # a wrong key or a rate limit must not drain the local cap


def test_only_the_answered_requests_are_charged_when_one_of_four_fails(game, fake, tmp_path):
    fake.statuses[DEFAULT_PROMPTS["hazard"]] = 429
    m = marker(tmp_path)
    m(game.render())
    saved = json.loads((tmp_path / "sam.json").read_text(encoding="utf-8"))
    assert m.calls == 4 and m.failed_calls == 1 and saved["calls"] == 3 and saved["spent_usd"] == pytest.approx(3 * 2.50 / 1000)


def test_a_partly_failed_keyframe_keeps_the_last_good_marks(game, fake, tmp_path):
    m = marker(tmp_path)
    good = m(game.render())
    game.press("right")
    fake.statuses[DEFAULT_PROMPTS["door"]] = 500
    assert m(game.render()) == good and m.last_error is not None and m.last_error.key == "busy"


def test_the_budget_file_survives_four_answers_arriving_at_once(game, fake, tmp_path):
    m = marker(tmp_path)
    for _ in range(3):
        game.press("right")
        m(game.render())
    saved = json.loads((tmp_path / "sam.json").read_text(encoding="utf-8"))
    assert saved["calls"] == m.calls - m.failed_calls and saved["spent_usd"] == pytest.approx(saved["calls"] * 2.50 / 1000)


def test_specks_are_dropped_and_real_objects_kept():
    """Real answer, credit day 27 Oct: 'yellow circle' on the Practice Arena returned the five coins and a 6x7 px speck (the door's knob)."""
    from playfellow_coop.sam_marks import big_enough
    text = ("<0f>0<|box;x1=492;y1=132;x2=516;y2=156;w=576;h=504|><|mask;x=0;y=0;data=x|>"
            "<0f>1<|box;x1=510;y1=332;x2=516;y2=339;w=576;h=504|><|mask;x=0;y=0;data=y|>")
    kept = big_enough(parse_boxes(text))
    assert [box for box, _ in kept] == [(492.0, 132.0, 517.0, 157.0)]


def test_the_default_phrases_are_the_visible_descriptions_the_real_service_answers():
    assert DEFAULT_PROMPTS["me"] == "blue circle" and DEFAULT_PROMPTS["reward"] == "yellow circle" and DEFAULT_PROMPTS["door"] == "brown box"
    for vague in ("the player character", "coin or collectible item", "door or exit", "hazard or enemy"):
        assert vague not in DEFAULT_PROMPTS.values()


def test_the_tracker_answers_small_moves_without_asking_sam_and_sam_is_asked_again_when_a_thing_is_lost(game, fake, tmp_path):
    from playfellow_coop.tracking import Tracker
    m = marker(tmp_path, tracker=Tracker())
    first = m(game.render())
    asked = len(fake.requests)
    assert asked == len(DEFAULT_PROMPTS) and first
    game.press("right")
    second = m(game.render())  # the player moved one step: the same things, a little apart
    assert len(fake.requests) == asked and m.tracked_pictures == 1 and len(second) == len(first)
    moved_me = [mk for mk in second if mk.kind == "me"][0]
    before_me = [mk for mk in first if mk.kind == "me"][0]
    assert (moved_me.x, moved_me.y) != (before_me.x, before_me.y)  # the mark followed the move
    for key in ("left", "right") * 8:  # many changed pictures later the tracker asks SAM to confirm (refresh), so a request is made again
        game.press(key)
        m(game.render())
    assert len(fake.requests) > asked
