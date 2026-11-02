"""The MCP server (owner order, 2 Nov): five tools over stdio, tested with the fake brain, no network.

The safety rules are the point, so each has a test: only the locked window, only the card's keys, the budget
cap stops a part before the call that would pass it, stop is F12's path and always wins, and no secret ever
appears in a response."""
from __future__ import annotations

import json
import os
import subprocess
import sys
import threading
from pathlib import Path

import pytest

from playfellow_coop.mcp_server import CoopServer, MCPServer

ROOT = Path(__file__).resolve().parents[1]


class FakeBrain:
    """Answers with one card action and reports a fixed cost, as the real brains report theirs."""

    def __init__(self, action: str = "WAIT", cost_usd: float = 0.0, delay: float = 0.0):
        self.action, self.cost_usd, self.delay = action, cost_usd, delay
        self.calls = 0
        self.last_request: dict = {}

    def ask(self, system, text, images):
        if self.delay:
            import time

            time.sleep(self.delay)
        self.calls += 1
        self.last_request = {"cost_usd": self.cost_usd, "tokens_in": 10, "tokens_out": 5}
        return json.dumps({"thought": "fake", "say": "", "actions": [self.action]})


def _server(brain: FakeBrain | None = None, **kwargs) -> CoopServer:
    brain = brain or FakeBrain()
    return CoopServer(game="snake", brain_factory=lambda game: brain, **kwargs)


def _call(server: MCPServer, name: str, args: dict | None = None, msg_id: int = 1) -> dict:
    reply = server.handle({"jsonrpc": "2.0", "id": msg_id, "method": "tools/call",
                           "params": {"name": name, "arguments": args or {}}})
    assert reply is not None and "result" in reply
    return reply["result"]


def _payload(result: dict) -> dict:
    return json.loads(result["content"][0]["text"])


def test_list_games_and_get_card_are_read_only():
    server = MCPServer(_server())
    games = _payload(_call(server, "list_games"))
    assert games["count"] >= 5 and games["locked_game"] == "snake"
    assert all(entry["has_card"] for entry in games["games"][:3])
    card = _payload(_call(server, "get_card", {"game": "snake"}))
    names = {a["name"] for a in card["actions"]}
    assert {"UP", "DOWN", "LEFT", "RIGHT"} <= names
    assert all(a["keys"] for a in card["actions"] if a["kind"] == "keys")
    bad = _call(server, "get_card", {"game": "no_such_game"})
    assert bad["isError"] is True  # an unknown game is an answer, never a crash


def test_status_starts_with_the_player_holding_the_controls():
    status = _server().status()
    assert status["holder"] == "player" and status["window"] == "arena:snake"
    assert status["ai_calls"] == 0 and status["spent_usd"] == 0.0 and status["part_active"] is False


def test_request_part_hands_back_counted_facts_and_the_controls():
    brain = FakeBrain(action="RIGHT", cost_usd=0.01)
    server = _server(brain)
    facts = server.request_part("grab the coins on the left", 3)
    assert facts["turns"] == 3 and facts["ai_calls"] == 3 and facts["holder"] == "player"
    assert facts["window"] == "arena:snake" and facts["game"] == "snake"  # the locked window never moved
    assert set(facts["keys_pressed"]) <= {"up", "down", "left", "right"}  # card keys only
    status = server.status()
    assert status["holder"] == "player" and status["ai_calls"] == 3 and status["spent_usd"] == 0.03


def test_an_off_card_action_is_never_pressed():
    brain = FakeBrain(action="FLY")  # not on the snake card: the engine's check drops it, the hands never see it
    server = _server(brain)
    facts = server.request_part("fly to the coins", 2)
    assert facts["keys_pressed"] == []
    assert server.status()["ai_calls"] == 2  # the calls happened; the key did not


def test_the_budget_cap_stops_a_part_before_the_call_that_would_pass_it():
    brain = FakeBrain(action="WAIT", cost_usd=0.60)
    server = _server(brain, cap_usd=1.0)
    facts = server.request_part("wait here", 10)
    assert facts["ended"] == "budget_cap" and brain.calls == 2  # 0.60 + 0.60 reaches the cap; no third call
    assert server.status()["spent_usd"] <= 1.20


def test_stop_wins_while_a_part_is_running():
    brain = FakeBrain(action="WAIT", delay=0.05)  # slow enough that the stop lands mid-part, as F12 would
    server = _server(brain)
    outcome: dict = {}

    def run_part():
        outcome.update(server.request_part("hold position", 60))

    thread = threading.Thread(target=run_part)
    thread.start()
    for _ in range(400):
        if brain.calls >= 1:
            break
        thread.join(timeout=0.01)
    stopped = server.stop()
    thread.join(timeout=30)
    assert stopped["stopped"] is True and stopped["holder"] == "player"
    assert outcome["ended"] == "stopped" and outcome["turns"] < 60
    assert server.status()["holder"] == "player" and server.status()["stopped"] is True


def test_no_secret_ever_appears_in_a_response(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "sentinel-secret-value")
    monkeypatch.setenv("BASETEN_API_KEY", "sentinel-baseten-value")
    server = MCPServer(_server(FakeBrain(action="WAIT")))
    replies = [_call(server, "list_games"), _call(server, "status"),
               _call(server, "get_card", {"game": "snake"}),
               _call(server, "request_part", {"goal": "wait", "turns": 1}), _call(server, "stop")]
    wire = json.dumps(replies)
    assert "sentinel-secret-value" not in wire and "sentinel-baseten-value" not in wire


def test_the_protocol_lists_the_five_tools_and_answers_a_ping():
    server = MCPServer(_server())
    hello = server.handle({"jsonrpc": "2.0", "id": 0, "method": "initialize", "params": {}})
    assert hello["result"]["serverInfo"]["name"] == "playfellow-coop"
    listed = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    assert [t["name"] for t in listed["result"]["tools"]] == ["list_games", "get_card", "status", "request_part", "stop"]
    assert server.handle({"jsonrpc": "2.0", "id": 2, "method": "ping"})["result"] == {}
    assert server.handle({"jsonrpc": "2.0", "method": "notifications/initialized"}) is None
    unknown = server.handle({"jsonrpc": "2.0", "id": 3, "method": "no/such"})
    assert unknown["error"]["code"] == -32601


def test_the_server_starts_as_a_module_and_speaks_stdio(tmp_path):
    env = dict(os.environ)
    env["PLAYFELLOW_ENGINE"] = env.get("PLAYFELLOW_ENGINE") or str(ROOT.parent / "playfellow" / "software")
    proc = subprocess.run(
        [sys.executable, "-m", "playfellow_coop.mcp_server", "--game", "snake"],
        input="\n".join([
            json.dumps({"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}),
            json.dumps({"jsonrpc": "2.0", "method": "notifications/initialized"}),
            json.dumps({"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "list_games", "arguments": {}}}),
            json.dumps({"jsonrpc": "2.0", "id": 3, "method": "tools/call", "params": {"name": "status", "arguments": {}}}),
        ]) + "\n",
        capture_output=True, text=True, cwd=ROOT, env=env, timeout=60)
    assert proc.returncode == 0, proc.stderr
    replies = [json.loads(line) for line in proc.stdout.splitlines() if line.strip()]
    by_id = {r["id"]: r for r in replies}
    games = json.loads(by_id[2]["result"]["content"][0]["text"])
    assert games["locked_game"] == "snake" and games["count"] >= 5
    status = json.loads(by_id[3]["result"]["content"][0]["text"])
    assert status["holder"] == "player" and status["window"] == "arena:snake"
