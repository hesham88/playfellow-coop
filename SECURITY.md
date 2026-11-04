# Security

Please **don't** open a public issue for a security problem. Report it privately with GitHub's **"Report a vulnerability"** button (the Security tab of this repository), with steps to reproduce.

This is a single-maintainer project. I will answer as soon as I can and credit you in the fix if you wish. Only the current `main` branch is supported.

**Most important to us:**
- any way input could reach a window other than the game chosen by the player, or bypass the F12 stop, the controls-card allow-list or the blocked-window list;
- any way the hand-over could keep pressing keys after the player took the controls;
- any leak of an API key, a spoken or typed command, personal data or screen content;
- any way a request could be sent to a host other than the pinned Meta API host, through a proxy, a redirect or an environment variable;
- the spending caps: anything that lets a call go out after the daily cap is reached.

**API keys never belong in this repository.** Keys are read from the `MODEL_API_KEY` environment variable or the operating system's credential store at run time. If you ever find a key, a token or a personal path in this repository, report it privately; do not repeat it in an issue.

## How the design answers the main threats

| Threat | What stops it | Where |
|---|---|---|
| Keys pressed in the wrong window | Input only while the chosen game is in front; every reply is checked against the game's controls card before the hands move; the engine's blocked-window list (launchers and stores, browsers, chat and mail, system tools, payment pages) is never played | `session.py`, the engine's `hands.py` and `games.py` |
| A key stuck down when focus is lost | The engine lets go of every key and mouse button on F12, on lost focus and at each step's end, from any thread, under one lock | the engine's `hands.py` (`release_all`) |
| Text on the screen that tries to steer the planner (prompt injection) | The planner can only name keys on the card, so injected text cannot reach another window or key; a "done" counts only after a second look at the screen; the daily cap stops spending before a call is sent; F12 ends everything | `muse_brain.py`, `assist.py`, `budget.py` |
| A model-written skill that misbehaves | It runs in a separate Python process in isolated mode (`-I`), with no keys in its environment, at low integrity inside a job object on Windows, with a hard time limit per step and a safe fallback | `skillsmith/sandbox.py`, `skillsmith/osjail.py` |
| The key leaking | Read only from `MODEL_API_KEY` or the Windows credential manager; `keys set` takes hidden input; `doctor` and `keys status` name the source only; requests go to the pinned Meta host with proxies and redirects refused | `cli_tools.py`, `_http.py`, `realtime_voice.py` |
| The MCP server as a back door | stdio only: it opens no network port; each request runs under the same card, window and stop rules | `mcp_server.py` |
| The companion's web page | A Content Security Policy allows scripts only from the pinned three.js path and lets the page fetch local files only, so it cannot send anything out | `overlay/avatar3d.html` |

**Scope.** This repository holds the event work (the Muse brain, SAM marks, voice, the hand-over, the benchmarks, the web demo and the training pipeline). The engine it plugs into has its own policy at `hesham88/playfellow`.
