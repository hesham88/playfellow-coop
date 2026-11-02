"""The MCP server: any agent can ask the buddy to play one part of a game, under the same rules as a person.

Start it with `python -m playfellow_coop.mcp_server` (stdio transport). Tools:

- `list_games` and `get_card(game)`: read only. The games are the engine's arena pack; a card is the only keys
  the buddy may ever press in that game.
- `status`: the locked window, who holds the controls, AI calls and spend so far.
- `request_part(goal, turns)`: hand one part ("grab the coins on the left") to the buddy for at most `turns`
  of its turns, then the controls come back to the player by themselves. The hand-back facts are returned.
- `stop`: the same stop as F12. Everything halts and every held key goes up.

The safety rules are part of the server, not options: only the locked chosen window is ever looked at or
pressed in, only keys on the game's card are pressed (the engine checks every reply against the card, and
this server adds its own check before the hands), the budget cap stops a part before a call that would pass
it, F12 and the mouse corner still win at any moment (the engine's Safety is in the loop), and no key or
secret ever appears in a response. The default brain is the engine's built-in one: no key, no network.
Tests drive the same tools with a fake brain (`tests/test_mcp_server.py`); nothing here needs the network.
"""
from __future__ import annotations

import argparse
import json
import sys
import threading
from pathlib import Path
from typing import Any, Callable

ROOT = Path(__file__).resolve().parents[1]
GAME_KEYS: tuple[str, ...] = ()  # filled from the bench table on first use, so importing this module stays cheap


def _game_keys() -> tuple[str, ...]:
    global GAME_KEYS
    if not GAME_KEYS:
        from bench.arena_run import GAMES

        GAME_KEYS = tuple(GAMES)
    return GAME_KEYS


def _engine_dir() -> Path:
    import os

    named = os.environ.get("PLAYFELLOW_ENGINE")
    if named:
        return Path(named)
    return ROOT.parent / "playfellow" / "software"


def _card_path(game: str) -> Path:
    return _engine_dir() / "controls" / f"arena_{game}.yaml"


def _load_card(game: str):
    import controls

    return controls.load_card(_card_path(game))


def _card_json(game: str, card) -> dict:
    actions = []
    for name, action in sorted(card.actions.items()):
        keys = getattr(action, "keys", ()) or ()
        if isinstance(keys, str):
            keys = tuple(k for k in keys.replace("+", " ").split() if k)
        actions.append({"name": name, "kind": getattr(action, "kind", "keys"), "keys": [str(k) for k in keys]})
    return {"game": game, "actions": actions, "uses_clicks": bool(getattr(card, "uses_clicks", False))}


def _builtin_brain_factory(game: str):
    """The default brain: the engine's own, no key and no network. Imported late so read-only tools never need it."""
    from brain.builtin_nav import BuiltinNavBrain

    return BuiltinNavBrain(_load_card(game), max_actions=1)


class CoopServer:
    """The tool core, apart from the wire: tests call these methods (and `handle`) directly."""

    def __init__(self, game: str = "snake", brain_factory: Callable[[str], Any] | None = None,
                 cap_usd: float = 1.0, max_calls: int = 100, seed: int = 0):
        if game not in _game_keys():
            raise ValueError(f"unknown game {game!r}; list_games says what there is")
        self.game = game
        self.window = f"arena:{game}"  # the one locked window; a part can never move it to another game
        self._brain_factory = brain_factory or _builtin_brain_factory
        self.cap_usd = float(cap_usd)
        self.max_calls = int(max_calls)
        self.seed = int(seed)
        self.holder = "player"  # the player starts with the controls, as in the assist
        self.ai_calls = 0
        self.spent_usd = 0.0
        self.stopped = False
        self._active = False
        self._lock = threading.Lock()
        self._stop = threading.Event()
        self._session: Any = None  # the live part's parts, so stop() takes the F12 path on it

    # ---- read-only tools ----

    def list_games(self) -> dict:
        games = []
        for key in _game_keys():
            games.append({"game": key, "has_card": _card_path(key).is_file()})
        return {"games": games, "count": len(games), "locked_game": self.game}

    def get_card(self, game: str) -> dict:
        if game not in _game_keys():
            raise ValueError(f"unknown game {game!r}; list_games says what there is")
        return _card_json(game, _load_card(game))

    def status(self) -> dict:
        with self._lock:
            return {"window": self.window, "game": self.game, "holder": self.holder,
                    "ai_calls": self.ai_calls, "spent_usd": round(self.spent_usd, 6),
                    "cap_usd": self.cap_usd, "stopped": self.stopped, "part_active": self._active}

    # ---- the stop, the same path as F12 ----

    def stop(self) -> dict:
        self._stop.set()
        self.stopped = True
        session, self._session = self._session, None
        if session is not None:
            session.safety.stop("stopped_button")  # F12's own path: the loop ends and the hands let go
            session.hands.on_stop()
        with self._lock:
            self.holder = "player"
            self._active = False
        return {"stopped": True, "holder": self.holder, "window": self.window}

    # ---- one part, then the controls come back ----

    def request_part(self, goal: str, turns: int) -> dict:
        goal = " ".join(str(goal).split())[:300]
        if not goal:
            raise ValueError("request_part needs the player's words for the part")
        turns = max(1, min(int(turns), 60))
        with self._lock:
            if self._active:
                raise ValueError("a part is already running; stop it first")
            if self.stopped:
                raise ValueError("the server is stopped; start it again for another part")
            self._stop.clear()  # a stop from before this part must not kill it; a stop during it must never be cleared away
            self._active = True
            self.holder = "buddy"
        try:
            return self._run_part(goal, turns)
        finally:
            with self._lock:
                self._active = False
                self.holder = "player"  # the controls come back by themselves, whatever happened

    def _run_part(self, goal: str, turns: int) -> dict:
        from bench.arena_run import VirtualHands, VirtualScreen, load_game
        from memory import Memory
        from safety import Safety
        import settings as engine_settings
        from brain.prompts import system_prompt

        from playfellow_coop import session as session_module
        from playfellow_coop.stage_timer import StageTimer
        from playfellow_coop.gym.progress import PROGRESS

        game = load_game(self.game, self.seed)
        card = _load_card(self.game)
        brain = self._brain_factory(self.game)
        cfg = engine_settings.Settings(look_every_seconds=0.0, max_actions_per_step=4, image_width=480,
                                       goal=str(goal))
        parts = type("Parts", (), {})()
        parts.brain, parts.card = brain, card
        parts.screen, parts.hands = VirtualScreen(game), VirtualHands(game, card)
        parts.safety, parts.memory = Safety(60, self.max_calls), Memory(cfg.memory_steps)
        self._session = parts
        parts.safety.start()
        before = dict(game.progress())
        calls_then, spent_then = self.ai_calls, self.spent_usd
        done_turns, ended = 0, "turn_limit"
        try:
            while done_turns < turns and not game.done:
                if self._stop.is_set() or parts.safety.check() is not None:
                    ended = "stopped"
                    break
                if self.spent_usd >= self.cap_usd or self.ai_calls >= self.max_calls:
                    ended = "budget_cap"  # the cap stops the part before the call that would pass it
                    break
                timer = StageTimer()
                timer.begin_turn()
                reply = session_module.take_turn(parts, cfg, system_prompt(cfg, card), timer, chat=[goal] if done_turns == 0 else [])
                timer.end_turn()
                done_turns += 1
                usage = getattr(brain, "last_request", None) or {}
                with self._lock:
                    self.ai_calls += 1
                    self.spent_usd += float(usage.get("cost_usd") or 0.0)
                if reply is not None and reply.dropped:
                    pass  # off-card actions were dropped by the engine's check; the count is in the reply, never pressed
        finally:
            parts.hands.on_stop()  # every held key goes up, as on F12
            self._session = None
        score = None
        try:
            score = round(1.0 if game.is_won() else float(PROGRESS[self.game](before, game.progress())), 4)
        except Exception:  # noqa: BLE001 (progress is a report, never a reason to fail the hand-back)
            score = None
        if ended == "turn_limit" and game.done:
            ended = "game_over"
        return {"request": goal, "game": self.game, "window": self.window, "done": bool(game.is_won()),
                "ended": ended, "turns": done_turns, "ai_calls": self.ai_calls - calls_then,
                "spent_usd": round(self.spent_usd - spent_then, 6), "progress": score,
                "keys_pressed": list(parts.hands.pressed), "holder": "player"}


# ---- the wire: MCP over stdio (JSON-RPC 2.0, one message per line) ----

TOOLS = [
    {"name": "list_games", "description": "The games the buddy can play a part in (read only).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "get_card", "description": "The controls card of one game: the only keys the buddy may press in it (read only).",
     "inputSchema": {"type": "object", "properties": {"game": {"type": "string"}}, "required": ["game"]}},
    {"name": "status", "description": "The locked window, who holds the controls, AI calls and spend so far.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "request_part", "description": "Hand one part (the player's words) to the buddy for at most `turns` turns; the controls then come back to the player.",
     "inputSchema": {"type": "object", "properties": {"goal": {"type": "string"}, "turns": {"type": "integer"}}, "required": ["goal", "turns"]}},
    {"name": "stop", "description": "Stop everything now, the same as F12: every held key goes up and the player has the controls.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _tool_result(payload: dict, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": is_error}


class MCPServer:
    """One CoopServer behind the MCP stdio protocol. `request_part` runs on its own thread so `stop` can land while a part runs."""

    def __init__(self, coop: CoopServer):
        self.coop = coop
        self._write_lock = threading.Lock()
        self._out = None

    def _call_tool(self, name: str, args: dict) -> dict:
        try:
            if name == "list_games":
                return _tool_result(self.coop.list_games())
            if name == "get_card":
                return _tool_result(self.coop.get_card(str(args.get("game", ""))))
            if name == "status":
                return _tool_result(self.coop.status())
            if name == "request_part":
                return _tool_result(self.coop.request_part(str(args.get("goal", "")), int(args.get("turns", 1))))
            if name == "stop":
                return _tool_result(self.coop.stop())
            return _tool_result({"error": f"unknown tool {name!r}"}, is_error=True)
        except (ValueError, KeyError) as error:
            return _tool_result({"error": str(error)}, is_error=True)

    def handle(self, message: dict) -> dict | None:
        method = message.get("method", "")
        msg_id = message.get("id")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05",
                    "capabilities": {"tools": {}}, "serverInfo": {"name": "playfellow-coop", "version": "0.1.0"}}}
        if method in ("notifications/initialized", "notifications/cancelled"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            params = message.get("params") or {}
            result = self._call_tool(str(params.get("name", "")), params.get("arguments") or {})
            return {"jsonrpc": "2.0", "id": msg_id, "result": result}
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}

    def _send(self, payload: dict) -> None:
        with self._write_lock:
            self._out.write(json.dumps(payload, ensure_ascii=False) + "\n")
            self._out.flush()

    def serve(self, instream, outstream) -> None:
        self._out = outstream
        for line in instream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
            except ValueError:
                continue
            if (message.get("method") == "tools/call"
                    and (message.get("params") or {}).get("name") == "request_part"):
                threading.Thread(target=self._run_part_request, args=(message,), daemon=True).start()
                continue
            reply = self.handle(message)
            if reply is not None:
                self._send(reply)

    def _run_part_request(self, message: dict) -> None:
        reply = self.handle(message)
        if reply is not None:
            self._send(reply)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PlayFellow co-op MCP server (stdio). One locked game window; the player starts with the controls.")
    parser.add_argument("--game", default="snake", help="the arena game whose window is locked (see list_games)")
    parser.add_argument("--cap-usd", type=float, default=1.0, help="budget cap in dollars; a part stops before a call that would pass it")
    parser.add_argument("--max-calls", type=int, default=100, help="AI call cap for the whole server run")
    parser.add_argument("--seed", type=int, default=0)
    args = parser.parse_args(argv)
    MCPServer(CoopServer(game=args.game, cap_usd=args.cap_usd, max_calls=args.max_calls, seed=args.seed)).serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
