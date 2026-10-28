"""The computer-use brain against a fake Responses server on 127.0.0.1: the observe-act loop, the translation onto the controls card, and safety checks that only the player can acknowledge."""
from __future__ import annotations

import http.server
import json
import os
import threading
from pathlib import Path

import pytest
from PIL import Image

import controls
from brain import BrainError
from playfellow_coop import muse_brain
from playfellow_coop.budget import DailyBudget
from playfellow_coop.control_words import APPROVE, DECLINE, control_action
from playfellow_coop.cua_brain import CuaBrain, translate
from reply import parse_reply

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])
CHESS = controls.load_card(ENGINE / "controls" / "arena_mini_chess.yaml")  # a click card
SNAKE = controls.load_card(ENGINE / "controls" / "arena_snake.yaml")  # a key card
IMAGE = Image.new("RGB", (401, 201), (10, 20, 30))
SECRET = "cua-test-key-S3cr3t"


def call(actions, call_id="call_1", checks=None):
    return {"type": "computer_call", "id": "cc_1", "call_id": call_id, "actions": actions, "pending_safety_checks": checks or [], "status": "completed"}


def response(*items, rid="resp_1", usage=(120, 30)):
    return {"id": rid, "output": list(items), "usage": {"input_tokens": usage[0], "output_tokens": usage[1], "input_tokens_details": {"cached_tokens": 100},
                                                        "output_tokens_details": {"reasoning_tokens": 5}}}


def message(text):
    return {"type": "message", "role": "assistant", "content": [{"type": "output_text", "text": text}]}


class Handler(http.server.BaseHTTPRequestHandler):
    def do_POST(self):  # noqa: N802
        body = json.loads(self.rfile.read(int(self.headers.get("Content-Length") or 0)) or b"{}")
        self.server.hits.append({"path": self.path, "auth": self.headers.get("Authorization"), "body": body})
        data = json.dumps(self.server.script.pop(0)).encode("utf-8")
        self.send_response(200)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def log_message(self, *args):
        pass


@pytest.fixture
def server():
    srv = http.server.ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    srv.hits, srv.script = [], []
    threading.Thread(target=srv.serve_forever, daemon=True).start()
    yield srv
    srv.shutdown()
    srv.server_close()


@pytest.fixture
def make(server, monkeypatch, tmp_path):
    monkeypatch.setitem(muse_brain.ENDPOINTS, "muse", f"http://127.0.0.1:{server.server_address[1]}/v1")
    made = []

    def build(card=CHESS, **kw):
        brain = CuaBrain("muse-spark-1.3", SECRET, budget=DailyBudget(tmp_path / "b.json", cap_usd=5.0, max_calls=100), **kw)
        brain.set_card(card)
        made.append(brain)
        return brain

    yield build
    for brain in made:
        brain.close()


# ---- translation onto the card ------------------------------------------------------------------------------------------------
def test_clicks_become_card_clicks_on_the_grid_and_everything_without_a_card_action_is_dropped_out_loud():
    actions, notes = translate([{"type": "click", "button": "left", "x": 200, "y": 100}, {"type": "double_click", "x": 0, "y": 200}, {"type": "type", "text": "rm -rf"},
                                {"type": "scroll", "x": 1, "y": 1, "scroll_x": 0, "scroll_y": 5}, {"type": "click", "button": "right", "x": 5, "y": 5}], CHESS, (401, 201))
    assert actions == [{"action": "CLICK", "x": 500, "y": 500}, {"action": "CLICK", "x": 0, "y": 1000}, {"action": "CLICK", "x": 0, "y": 1000}]
    assert any("type has no action" in n for n in notes) and any("scroll has no action" in n for n in notes) and any("right" in n for n in notes)
    reply = parse_reply(json.dumps({"thought": "", "say": "", "actions": actions}), CHESS, 8)
    assert [s.action for s in reply.steps] == ["CLICK"] * 3 and reply.steps[0].x == 500 and not reply.dropped  # the engine's own reply check accepts them


def test_keypresses_only_become_the_cards_own_keys():
    actions, notes = translate([{"type": "keypress", "keys": ["Up", "Space", "Left"]}, {"type": "wait"}, {"type": "screenshot"}], SNAKE, (100, 100))
    assert [a for a in actions if isinstance(a, str)] == [name for name in actions] and "UP" in actions and "LEFT" in actions
    assert any("'Space'" in n for n in notes)  # snake has no space key
    assert translate([{"type": "click", "x": 1, "y": 1}], SNAKE, (10, 10))[0] == []  # a key card has no click action
    assert translate([{"type": "click"}], CHESS, (10, 10))[1] == ["click was malformed and was dropped"]
    assert translate([{"type": "drag", "path": [{"x": 0, "y": 0}, {"x": 10, "y": 10}]}], CHESS, (11, 11))[0] == []  # no drag on the chess card


# ---- the loop ---------------------------------------------------------------------------------------------------------------------
def test_the_observe_act_loop_chains_turns_and_sends_one_screenshot_per_turn_and_finishes_on_a_message(make, server):
    brain = make()
    server.script += [response(call([{"type": "click", "button": "left", "x": 200, "y": 100}]), rid="r1"),
                      response(call([{"type": "click", "button": "left", "x": 400, "y": 200}], "call_2"), rid="r2", usage=(90, 20)),
                      response(message("The game is won."), rid="r3")]
    first = json.loads(brain.ask("SYSTEM", "win the game", [IMAGE, IMAGE]))
    assert first["actions"] == [{"action": "CLICK", "x": 500, "y": 500}]
    second = json.loads(brain.ask("SYSTEM", "win the game", [IMAGE]))
    assert second["actions"] == [{"action": "CLICK", "x": 1000, "y": 1000}]
    last = json.loads(brain.ask("SYSTEM", "win the game", [IMAGE]))
    assert last["actions"] == [] and "won" in last["thought"] and brain.finished
    one, two, three = (h["body"] for h in server.hits)
    assert server.hits[0]["path"] == "/v1/responses" and server.hits[0]["auth"] == f"Bearer {SECRET}"
    assert one["tools"] == [{"type": "computer"}] and one["model"] == "muse-spark-1.3" and "previous_response_id" not in one and one["instructions"].endswith("SYSTEM")
    assert one["input"][0]["content"][1]["image_url"].startswith("data:image/jpeg;base64,") and one["reasoning"] == {"effort": "minimal"}
    assert two["previous_response_id"] == "r1" and two["input"][0]["type"] == "computer_call_output" and two["input"][0]["call_id"] == "call_1"
    assert two["input"][0]["output"]["type"] == "computer_screenshot" and two["input"][0]["acknowledged_safety_checks"] == [] and two["tools"] == [{"type": "computer"}]
    assert three["previous_response_id"] == "r2" and three["input"][0]["call_id"] == "call_2"
    assert brain.last_request["tokens_cached"] == 100 and brain.last_request["reasoning_tokens"] == 5
    assert SECRET not in repr(brain)


def test_a_step_cap_ends_a_run_that_never_finishes_and_nothing_more_is_sent(make, server):
    brain = make(max_steps=2)
    server.script += [response(call([{"type": "wait"}], f"c{i}"), rid=f"r{i}") for i in range(5)]
    for _ in range(4):
        brain.ask("s", "t", [IMAGE])
    assert len(server.hits) == 2 and brain.finished


def test_a_reply_with_no_picture_or_no_card_is_refused_before_anything_is_sent(make, server):
    with pytest.raises(BrainError):
        make().ask("s", "t", [])
    nocard = make()
    nocard._card = None
    server.script += [response(call([{"type": "wait"}]))]
    with pytest.raises(BrainError):
        nocard.ask("s", "t", [IMAGE])


# ---- safety checks ----------------------------------------------------------------------------------------------------------------
CHECK = {"id": "csc_1", "code": "malicious_instructions", "message": "Potentially unsafe action detected."}


def test_a_safety_check_holds_the_action_until_the_players_own_approval_and_is_then_acknowledged_in_the_next_request(make, server):
    brain = make()
    server.script += [response(call([{"type": "click", "button": "left", "x": 200, "y": 100}], "call_9", [CHECK]), rid="r1"), response(message("done"), rid="r2")]
    held = json.loads(brain.ask("s", "t", [IMAGE]))
    assert held["actions"] == [] and "Potentially unsafe" in held["say"] and brain.waiting_for_player == [CHECK]
    for _ in range(3):  # asking again changes nothing and sends nothing: the model cannot approve itself
        assert json.loads(brain.ask("s", "t", [IMAGE]))["actions"] == []
    assert len(server.hits) == 1
    brain.acknowledge()
    released = json.loads(brain.ask("s", "t", [IMAGE]))
    assert released["actions"] == [{"action": "CLICK", "x": 500, "y": 500}] and brain.waiting_for_player == [] and len(server.hits) == 1
    brain.ask("s", "t", [IMAGE])
    sent = server.hits[1]["body"]["input"][0]
    assert sent["call_id"] == "call_9" and sent["acknowledged_safety_checks"] == [CHECK]


def test_declining_a_safety_check_ends_the_run_and_nothing_is_pressed(make, server):
    brain = make()
    server.script += [response(call([{"type": "click", "button": "left", "x": 1, "y": 1}], "c", [CHECK]))]
    brain.ask("s", "t", [IMAGE])
    brain.decline()
    assert brain.finished and brain.waiting_for_player == [] and json.loads(brain.ask("s", "t", [IMAGE]))["actions"] == [] and len(server.hits) == 1


def test_only_whole_phrases_approve_or_decline_and_the_session_passes_them_to_the_brain(make, server):
    from playfellow_coop import session
    assert control_action("Approve it!") == APPROVE and control_action("don't do it") == DECLINE and control_action("I approve of this plan") is None
    brain = make()
    server.script += [response(call([{"type": "click", "button": "left", "x": 1, "y": 1}], "c", [CHECK]))]
    brain.ask("s", "t", [IMAGE])
    parts = type("P", (), {})()
    parts.brain = brain
    said = []
    session._apply_control(APPROVE, parts, None, lambda kind, data: said.append((kind, data)))
    assert brain.approved and said and said[0][0] == "say"
    other = type("P", (), {})()
    other.brain = object()  # a brain with nothing to approve: the word does nothing
    session._apply_control(APPROVE, other, None, lambda kind, data: said.append("wrong"))
    assert "wrong" not in said


def test_the_contributor_model_is_still_refused(tmp_path):
    with pytest.raises(ValueError):
        CuaBrain("muse-spark-contributor", SECRET)
