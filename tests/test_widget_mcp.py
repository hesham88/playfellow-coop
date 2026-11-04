"""The widget MCP server: Meta's Muse Code (or any MCP agent) drives the running PlayFellow widget through the same files the widget and the
game sessions already share. Nothing here opens a window, presses a key or reaches the network; the files live in a temp folder."""
from __future__ import annotations

import json

import pytest

from playfellow_coop import widget_mcp
from playfellow_coop.games.stk import widget


@pytest.fixture
def home(tmp_path, monkeypatch):
    for name, file in (("FEED", "live-feed.txt"), ("LOCK", "widget.pid"), ("STOP", "STOP"), ("HANDOVER", "HANDOVER"),
                       ("STATUS", "STATUS"), ("COMMANDS", "commands.txt")):
        monkeypatch.setattr(widget, name, tmp_path / file)
    monkeypatch.setattr(widget, "widget_running", lambda: True)
    return tmp_path


def feed(home) -> list[str]:
    return [line.split(" ", 1)[1] for line in (home / "live-feed.txt").read_text(encoding="utf-8").splitlines()]


def call(server, name, **args):
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/call", "params": {"name": name, "arguments": args}})
    result = reply["result"]
    return json.loads(result["content"][0]["text"]), result["isError"]


# ---- the widget's own control lines ----------------------------------------------------------------------------------------
@pytest.mark.parametrize("line,expected", [
    ("!open", ("open", None)), ("!fold", ("fold", None)), ("!opacity 0.6", ("opacity", 0.6)), ("!opacity 0.1", ("opacity", 0.3)),
    ("!opacity 7", ("opacity", 1.0)), ("!character vela", ("character", "vela")), ("!character bob", None), ("!rm -rf", None),
    ("hello there", None), ("!opacity lots", None),
])
def test_control_lines_are_parsed_strictly(line, expected):
    assert widget.parse_control(line) == expected


# ---- the MCP tools ----------------------------------------------------------------------------------------------------------
def test_tools_are_listed():
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    reply = server.handle({"jsonrpc": "2.0", "id": 1, "method": "tools/list"})
    names = {tool["name"] for tool in reply["result"]["tools"]}
    assert {"status", "say", "command", "hand_over", "take_back", "stop", "widget", "list_games", "start_widget"} <= names


def test_initialize_names_the_server():
    reply = widget_mcp.WidgetMCP("SuperTuxKart").handle({"jsonrpc": "2.0", "id": 0, "method": "initialize"})
    assert reply["result"]["serverInfo"]["name"] == "playfellow-widget"


def test_say_shows_one_clean_line(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out, error = call(server, "say", text="  Nice drift!\n!open  ")
    assert not error and feed(home) == ["Nice drift! !open"]  # one line
    out, error = call(server, "say", text="!fold")
    assert feed(home)[-1] == "fold"  # a leading '!' is dropped, so a said line can never become a control line
    assert all(widget.parse_control(line) is None for line in feed(home))


def test_hand_over_take_back_and_stop_use_the_widget_files(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    call(server, "hand_over")
    assert (home / "HANDOVER").exists() and call(server, "status")[0]["holder"] == "player"
    call(server, "take_back")
    assert not (home / "HANDOVER").exists() and call(server, "status")[0]["holder"] == "buddy"
    call(server, "stop")
    assert (home / "STOP").exists() and call(server, "status")[0]["stopped"] is True


def test_command_reaches_the_widget_and_wait_takes_the_controls_for_the_player(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out, _ = call(server, "command", text="grab the gift boxes")
    assert feed(home)[-1] == "!type grab the gift boxes"
    call(server, "command", text="wait")
    assert (home / "HANDOVER").read_text(encoding="utf-8") == "agent"


def test_widget_actions_become_control_lines_and_bad_values_are_refused(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    call(server, "widget", action="open")
    call(server, "widget", action="opacity", value="0.5")
    call(server, "widget", action="character", value="dalil")
    assert feed(home) == ["!open", "!opacity 0.5", "!character dalil"]
    out, error = call(server, "widget", action="explode")
    assert error and "open" in out["error"]
    out, error = call(server, "widget", action="character", value="nobody")
    assert error


def test_status_reports_the_last_lines_and_never_a_key(home, monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "pk-SENTINEL-never-shown-0123456789")
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    call(server, "say", text="first")
    call(server, "say", text="second")
    out, _ = call(server, "status")
    assert out["game"] == "SuperTuxKart" and out["widget_running"] is True and out["last_lines"][-1] == "second"
    assert "SENTINEL" not in json.dumps(out)


def test_list_games_skips_blocked_windows(monkeypatch):
    server = widget_mcp.WidgetMCP("SuperTuxKart", list_windows=lambda: ["SuperTuxKart", "Discord", "Endless Sky"],
                                  is_blocked=lambda t: t == "Discord")
    out, _ = call(server, "list_games")
    assert out["games"] == ["SuperTuxKart", "Endless Sky"]


def test_start_widget_runs_the_injected_launcher_once(home):
    started = []
    server = widget_mcp.WidgetMCP("SuperTuxKart", launch=lambda title: started.append(title))
    out, error = call(server, "start_widget")
    assert not error and started == []  # already running: nothing started twice
    server.running = lambda: False
    call(server, "start_widget")
    assert started == ["SuperTuxKart"]


def test_unknown_tool_is_an_error_not_a_crash():
    out, error = call(widget_mcp.WidgetMCP("SuperTuxKart"), "format_disk")
    assert error and "unknown tool" in out["error"]


def test_the_main_command_has_an_mcp_word():
    from playfellow_coop import cli_tools

    assert cli_tools.is_tool(["mcp"])


# ---- review fixes: the player's F9 and F12 always win over an agent -------------------------------------------------------
def test_an_agent_cannot_undo_the_players_f9(home):
    widget.hand_over(True)  # the player pressed F9
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out, error = call(server, "take_back")
    assert error and (home / "HANDOVER").exists()
    out, error = call(server, "command", text="go")
    assert error and (home / "HANDOVER").exists()


def test_an_agent_can_give_back_only_what_it_took(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    call(server, "hand_over")
    assert (home / "HANDOVER").read_text(encoding="utf-8") == "agent"
    out, error = call(server, "take_back")
    assert not error and not (home / "HANDOVER").exists()


def test_an_agent_can_never_clear_a_stop(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    call(server, "stop")
    for name, args in (("take_back", {}), ("command", {"text": "continue"}), ("command", {"text": "take it back"})):
        out, error = call(server, name, **args)
        assert error and (home / "STOP").exists(), name


def test_stop_works_on_a_fresh_game_folder(tmp_path, monkeypatch):
    fresh = tmp_path / "never-made"
    for name, file in (("FEED", "live-feed.txt"), ("STOP", "STOP"), ("HANDOVER", "HANDOVER"), ("STATUS", "STATUS"), ("COMMANDS", "commands.txt")):
        monkeypatch.setattr(widget, name, fresh / file)
    monkeypatch.setattr(widget, "GAME_DIR", fresh)
    out, error = call(widget_mcp.WidgetMCP("SuperTuxKart"), "stop")
    assert not error and (fresh / "STOP").exists()


def test_free_words_reach_the_widget_as_typed_input(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out, error = call(server, "command", text="grab the gift boxes")
    assert not error and feed(home)[-1] == "!type grab the gift boxes"
    assert widget.parse_control("!type grab the gift boxes") == ("type", "grab the gift boxes")


def test_say_cannot_smuggle_a_control_line_past_spaces(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    for text in ("! !fold", "~ ~happy", " ! ! ! !type go"):
        call(server, "say", text=text)
    assert all(not line.startswith(("!", "~")) for line in feed(home))


def test_bad_messages_get_an_error_not_a_dead_server(home):
    import io

    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out = io.StringIO()
    lines = ['[1, 2]', '{"jsonrpc":"2.0","id":7,"method":"tools/call","params":"oops"}',
             '{"jsonrpc":"2.0","id":8,"method":"tools/call","params":{"name":"say","arguments":[1]}}',
             '{"jsonrpc":"2.0","id":9,"method":"ping"}']
    server.serve(io.StringIO("\n".join(lines) + "\n"), out)
    replies = [json.loads(line) for line in out.getvalue().splitlines()]
    assert replies[-1] == {"jsonrpc": "2.0", "id": 9, "result": {}}  # still alive after the bad ones


def test_arabic_survives_the_wire(home):
    server = widget_mcp.WidgetMCP("SuperTuxKart")
    out, error = call(server, "say", text="هات النيترو")
    assert not error and feed(home)[-1] == "هات النيترو"


def test_a_game_folder_name_is_always_safe():
    for title in ("A|B", r"..\..\Windows", "C: drive", "Endless Sky", ""):
        name = widget.folder_name(title)
        assert name and all(ch.isalnum() or ch in "-._" for ch in name) and ".." not in name, (title, name)
