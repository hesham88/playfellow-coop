"""The widget MCP server: Meta's Muse Code, or any MCP agent, drives the PlayFellow widget that sits on a real game window.

    python -m playfellow_coop mcp --game "SuperTuxKart"      (MCP over stdio)

Tools: `status`, `say`, `command`, `hand_over`, `take_back`, `stop`, `widget` (open, fold, opacity, character), `list_games`,
`start_widget`. They use the same small files the widget and the game sessions already share (the feed, STOP, HANDOVER, STATUS,
commands), so an agent has exactly the player's powers and no more:

- an agent's free words reach the running widget as typed input (a `!type` line it handles like the panel's box); the session still
  presses only the keys on the game's controls card, only while the game is in front;
- `stop` is the same stop as F12 and "stop"; an agent may stop the buddy or take the controls for the player, but it can never clear
  a stop or undo the player's own F9: while either is in force, the widget ignores the agent's words;
- `say` writes one clean line (it can never smuggle a control line in); the widget's own controls are a short fixed list;
- no tool reads, prints or sends a key; nothing here touches the network.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Callable

WIDGET_ACTIONS = ("open", "fold", "opacity", "character")


def _widget():
    from playfellow_coop.games.stk import widget  # read at call time, so the game set by --game (and tests) take effect
    return widget


def _launch(title: str) -> None:  # pragma: no cover - starts a real window
    """The widget as its own detached process on the named game."""
    root = str(Path(__file__).resolve().parents[1])
    engine = os.environ.get("PLAYFELLOW_ENGINE", "")
    env = dict(os.environ, PLAYFELLOW_GAME_TITLE=title, PYTHONPATH=os.pathsep.join(p for p in (root, engine) if p))
    flags = 0x00000008 | 0x00000200 if sys.platform == "win32" else 0  # detached, own process group
    subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.widget"], env=env, cwd=root, stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL, creationflags=flags)


def _list_windows() -> list[str]:  # pragma: no cover - needs a desktop
    from playfellow_coop.cli_tools import _list_windows as listing
    return listing()


def _is_blocked(title: str) -> bool:  # pragma: no cover - the engine's own list
    from playfellow_coop.cli_tools import _is_blocked as blocked
    return blocked(title)


def _one_line(text: str, limit: int = 240) -> str:
    """One line of plain words: it can never start with '!' (a widget control) or '~' (a mood cue), however it is padded."""
    line = " ".join(str(text).split())
    while line[:1] in ("!", "~", " ") and line:
        line = line[1:]
    return line[:limit].strip()


TOOLS = [
    {"name": "status", "description": "The game, whether the widget runs, who holds the controls, whether stopped, and the widget's last lines.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "say", "description": "Show one line on the widget, as the buddy's words.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "command", "description": "Words for the buddy, as if typed in the widget (e.g. 'grab the gift boxes'). 'stop' always works; 'wait' takes the controls for the player; 'go' gives back only what an agent took.",
     "inputSchema": {"type": "object", "properties": {"text": {"type": "string"}}, "required": ["text"]}},
    {"name": "hand_over", "description": "The player takes the controls (as F9): the buddy lets go of every key and waits.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "take_back", "description": "The buddy takes the controls back (as F9 again).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "stop", "description": "Stop everything now, the same as F12: every held key goes up.",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "widget", "description": "Change the widget itself: action open | fold | opacity (value 0.3-1.0) | character (fello, dalil, rami, hakim, vela).",
     "inputSchema": {"type": "object", "properties": {"action": {"type": "string", "enum": list(WIDGET_ACTIONS)}, "value": {"type": "string"}},
                     "required": ["action"]}},
    {"name": "list_games", "description": "The open windows PlayFellow may play (launchers, browsers, chat, mail, system tools and payment pages are never listed).",
     "inputSchema": {"type": "object", "properties": {}}},
    {"name": "start_widget", "description": "Start the widget on the game named when the server started, if it is not running yet.",
     "inputSchema": {"type": "object", "properties": {}}},
]


def _result(payload: dict, is_error: bool = False) -> dict:
    return {"content": [{"type": "text", "text": json.dumps(payload, ensure_ascii=False)}], "isError": is_error}


class WidgetMCP:
    def __init__(self, game: str, launch: Callable[[str], None] = _launch, list_windows: Callable[[], list[str]] = _list_windows,
                 is_blocked: Callable[[str], bool] = _is_blocked):
        self.game = game
        self.launch, self.list_windows, self.is_blocked = launch, list_windows, is_blocked
        self.running = lambda: bool(_widget().widget_running())

    # ---- tools ----
    def status(self) -> dict:
        w = _widget()
        lines: list[str] = []
        try:
            lines = [line.split(" ", 1)[1] if line[2:3] == ":" else line for line in w.FEED.read_text(encoding="utf-8").splitlines()]
        except OSError:
            pass
        shown = [line for line in lines if not line.startswith(("!", "~"))][-5:]
        return {"game": self.game, "widget_running": self.running(), "holder": "player" if w.HANDOVER.exists() else "buddy",
                "stopped": w.STOP.exists(), "now": w.status_text(), "last_lines": shown}

    def say(self, text: str) -> dict:
        line = _one_line(text)
        if not line:
            raise ValueError("say needs some words")
        _widget().say_line(line, _widget().FEED)
        return {"shown": line}

    def command(self, text: str) -> dict:
        said = _one_line(text, 300)
        if not said:
            raise ValueError("command needs the player's words")
        w, low = _widget(), said.lower()
        if re.search(r"\b(stop|halt)\b|توقف|قف", low):
            return {"heard": said, "widget_says": w.command(said)}  # stopping is always allowed
        if re.match(r"\s*(wait|hand over|you take it|my turn|i got it|i've got it)\b|\s*(استنى|انتظر|خدها|اخذها)", low):
            return {"heard": said, "widget_says": w.hand_over(True, by="agent")}
        if re.match(r"\s*(go|continue|resume)\W*$|\s*(take it back|your turn)\b|\s*(كمل|يلا)", low):
            return self.take_back()
        if w.player_holds():
            raise ValueError("the player has the controls (or everything is stopped); only the player can change that")
        w.say_line(f"!type {said}", w.FEED)  # the running widget handles it like typing in its box
        return {"heard": said, "sent_to": "the widget, as typed input"}

    def take_back(self) -> dict:
        w = _widget()
        if w.STOP.exists():
            raise ValueError("everything is stopped; only the player can start again (F9 or 'go')")
        if w.HANDOVER.exists() and w.HANDOVER.read_text(encoding="utf-8").strip() != "agent":
            raise ValueError("the player took the controls; only the player gives them back (F9 or 'go')")
        return {"widget_says": w.hand_over(False)}

    def widget(self, action: str, value: str | None = None) -> dict:
        if action not in WIDGET_ACTIONS:
            raise ValueError(f"action must be one of: {', '.join(WIDGET_ACTIONS)}")
        line = f"!{action}" if action in ("open", "fold") else f"!{action} {value}"
        parsed = _widget().parse_control(line)
        if parsed is None:
            raise ValueError("opacity takes a number from 0.3 to 1.0; character takes fello, dalil, rami, hakim or vela")
        shown = f"!{parsed[0]}" if parsed[1] is None else f"!{parsed[0]} {parsed[1]}"
        _widget().say_line(shown, _widget().FEED)
        return {"applied": shown[1:]}

    def list_games(self) -> dict:
        titles, seen = [], set()
        for title in self.list_windows():
            title = title.strip()
            if title and title not in seen and not self.is_blocked(title):
                seen.add(title)
                titles.append(title)
        return {"games": titles}

    def start_widget(self) -> dict:
        if self.running():
            return {"started": False, "why": "the widget is already running"}
        self.launch(self.game)
        return {"started": True, "game": self.game}

    # ---- the wire: MCP over stdio (JSON-RPC 2.0, one message per line) ----
    def _call(self, name: str, args: dict) -> dict:
        try:
            if name == "status":
                return _result(self.status())
            if name == "say":
                return _result(self.say(str(args.get("text", ""))))
            if name == "command":
                return _result(self.command(str(args.get("text", ""))))
            if name == "hand_over":
                return _result({"widget_says": _widget().hand_over(True, by="agent")})
            if name == "take_back":
                return _result(self.take_back())
            if name == "stop":
                return _result({"widget_says": _widget().command("stop")})
            if name == "widget":
                value = args.get("value")
                return _result(self.widget(str(args.get("action", "")), None if value is None else str(value)))
            if name == "list_games":
                return _result(self.list_games())
            if name == "start_widget":
                return _result(self.start_widget())
            return _result({"error": f"unknown tool {name!r}"}, is_error=True)
        except Exception as error:  # noqa: BLE001 - one bad call is an error reply, never a dead server
            return _result({"error": str(error) or type(error).__name__}, is_error=True)

    def handle(self, message: dict) -> dict | None:
        method, msg_id = message.get("method", ""), message.get("id")
        if method == "initialize":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"protocolVersion": "2024-11-05", "capabilities": {"tools": {}},
                                                               "serverInfo": {"name": "playfellow-widget", "version": "0.1.0"}}}
        if method.startswith("notifications/"):
            return None
        if method == "ping":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {}}
        if method == "tools/list":
            return {"jsonrpc": "2.0", "id": msg_id, "result": {"tools": TOOLS}}
        if method == "tools/call":
            params = message.get("params")
            params = params if isinstance(params, dict) else {}
            args = params.get("arguments")
            return {"jsonrpc": "2.0", "id": msg_id, "result": self._call(str(params.get("name", "")), args if isinstance(args, dict) else {})}
        if msg_id is None:
            return None
        return {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32601, "message": f"method not found: {method}"}}

    def serve(self, instream, outstream) -> None:
        for line in instream:
            line = line.strip()
            if not line:
                continue
            try:
                message = json.loads(line)
                reply = self.handle(message) if isinstance(message, dict) else None
            except Exception as error:  # noqa: BLE001 - a bad message never ends the server
                msg_id = message.get("id") if isinstance(locals().get("message"), dict) else None
                reply = None if msg_id is None else {"jsonrpc": "2.0", "id": msg_id, "error": {"code": -32603, "message": type(error).__name__}}
            if reply is not None:
                outstream.write(json.dumps(reply, ensure_ascii=False) + "\n")
                outstream.flush()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="PlayFellow widget MCP server (stdio): an agent drives the widget on a real game.")
    parser.add_argument("--game", default="SuperTuxKart", help="the game window's title, as `python -m playfellow_coop games` lists it")
    args = parser.parse_args(argv)
    os.environ["PLAYFELLOW_GAME_TITLE"] = args.game  # before the widget module loads: its files are per game
    for stream in (sys.stdin, sys.stdout):  # MCP is UTF-8 on the wire: Arabic words must survive a Windows pipe
        stream.reconfigure(encoding="utf-8")
    WidgetMCP(args.game).serve(sys.stdin, sys.stdout)
    return 0


if __name__ == "__main__":
    sys.exit(main())
