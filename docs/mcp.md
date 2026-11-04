# MCP: drive PlayFellow from Meta's Muse Code or any agent

PlayFellow has two MCP servers, both over stdio, both under the player's own rules:

| Server | Start | What an agent can do |
|---|---|---|
| **The widget server** (real games) | `python -m playfellow_coop mcp --game "<window title>"` | Drive the widget on a real game window: show a line, give a command as if typed, hand over and take back, stop (as F12), open or fold the widget, set its see-through level or character, list the open games, start the widget |
| **The part server** (arena games) | `python -m playfellow_coop.mcp_server --game snake` | Ask the buddy to play one part of an arena game and get the hand-back facts |

**One widget, however it was started.** The PlayFellow widget follows the same small files whether it came from the main command
(`.\playfellow --window "<title>" --overlay ...`) or from a game pack (`.\playfellow stk widget`). Start the MCP server with the
**same title** (`--game "<title>"`) and the agent drives that widget.

## Add it to Meta's Muse Code (or any MCP client)

Add this to the agent's MCP settings (the usual `mcpServers` block; use the virtual environment's Python, so the engine is found):

```json
{
  "mcpServers": {
    "playfellow": {
      "command": "C:\\path\\to\\playfellow-coop\\.venv\\Scripts\\python.exe",
      "args": ["-m", "playfellow_coop", "mcp", "--game", "SuperTuxKart"]
    }
  }
}
```

Then ask the agent, for example: *"Open the PlayFellow widget, set it to 70% see-through, say 'ready when you are', and tell the
buddy to grab the gift boxes."* It calls `widget` (open), `widget` (opacity 0.7), `say` and `command`.

### Widget server tools

| Tool | What it does |
|---|---|
| `status` | The game, whether the widget runs, who holds the controls (`player` or `buddy`), whether stopped, what the buddy is doing, the last 5 lines |
| `say(text)` | One line on the widget, as the buddy's words (one clean line; it can never become a control line) |
| `command(text)` | Words for the buddy, handled by the running widget like typing in its box ("grab the gift boxes"). "stop" always works; "wait" takes the controls for the player; "go" gives back only what an agent took |
| `hand_over` / `take_back` | The agent hands the controls to the player / gives back only a hand-over the agent made: it can never undo the player's own F9 or clear a stop |
| `stop` | The same stop as F12 and "stop": every held key goes up |
| `widget(action, value)` | `open`, `fold`, `opacity` (0.3–1.0: never invisible), `character` (fello, dalil, rami, hakim, vela) |
| `list_games` | The open windows PlayFellow may play; launchers, browsers, chat, mail, system tools and payment pages are never listed |
| `start_widget` | Start the widget on the server's game if it is not running yet |

The widget server uses the same small files the widget and the game sessions already share, so an agent has exactly the player's
powers: its words reach the game only as a command, the session still presses only the controls card's keys and only while the game
is in front, and the player's own F9 and F12 still win at any moment. No tool reads, prints or sends a key, and nothing reaches the
network.

# The part server: let another agent ask for one part

Any agent that speaks the Model Context Protocol can ask PlayFellow's buddy to do one part of a game —
"grab the coins on the left" — under exactly the rules a person gets. The buddy does that part, then the
controls come back to the player by themselves.

## Start it

```
python -m playfellow_coop.mcp_server --game snake
```

Stdio transport, one JSON-RPC message per line. Options: `--game` (the arena game whose window is locked;
`list_games` says what there is), `--seed`, `--cap-usd` (budget cap, default 1.00), `--max-calls`
(AI call cap for the run, default 100). The default brain is the engine's built-in one: no key, no network.
The server locks onto that one game at start and never moves to another window.

## Tools

| Tool | What it does |
|---|---|
| `list_games` | The games the buddy can play a part in, and which one is locked. Read only. |
| `get_card(game)` | That game's controls card: the only keys the buddy may press in it. Read only. |
| `status` | The locked window, who holds the controls (`player` or `buddy`), AI calls and spend so far, the cap, whether a part is running. |
| `request_part(goal, turns)` | Hand one part to the buddy in the player's words, for at most `turns` of its turns. Returns the hand-back facts: turns, AI calls, spend, the game's own progress, the keys pressed, and how it ended (`turn_limit`, `game_over`, `budget_cap`, `stopped`). The controls are the player's again when it returns. |
| `stop` | Stop everything now — the same stop as F12. Every held key goes up and the player has the controls. |

Example exchange (one message per line):

```
{"jsonrpc": "2.0", "id": 1, "method": "initialize", "params": {}}
{"jsonrpc": "2.0", "method": "notifications/initialized"}
{"jsonrpc": "2.0", "id": 2, "method": "tools/call", "params": {"name": "request_part", "arguments": {"goal": "grab the coins on the left", "turns": 6}}}
```

`request_part` runs on its own thread, so a `stop` call lands while a part is running and wins at the next
turn boundary.

## The safety rules are the server, not options

- **Only the locked window.** The game is chosen once, at start. No tool can point the buddy at another
  window or game, and keys are pressed only while that window is the one being played.
- **Only the card's keys.** Every reply is checked against the game's controls card before the hands move
  (the engine's own check); an action that is not on the card is dropped and never pressed.
- **The budget cap.** Spend is counted per AI call from what the brain itself reports; a part stops before
  a call that would pass `--cap-usd`, and the whole run stops at `--max-calls`.
- **F12 always wins.** `stop` takes the engine's own stop path: the session's safety stop, every held key
  released, the player holding the controls. The engine's F12 and mouse-corner stops stay live underneath.
- **No secrets out.** Responses contain counted facts only — never a key, a header or an environment value.

## How it is tested

`tests/test_mcp_server.py` drives every tool with a fake brain (no network, no key): the card check, the
budget cap, stop winning mid-part, the hand-back facts, the secret scan, and a real stdio session through
`python -m playfellow_coop.mcp_server`. The part loop is the public session turn
(`playfellow_coop.session.take_turn`) on the arena's virtual screen and hands, so what is tested is the
same turn the benchmark runs.
