# The MCP server: let another agent ask for one part

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
