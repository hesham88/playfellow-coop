# Interfaces and formats for the gegaa-wave design

The design explains why; this file gives the shapes. Where a number lives in a named constant, the constant is named: read it there, it is the one source.

## Session wiring (`playfellow_coop/session.py`)

- `play_session(parts, settings, system, timer, handover=None, on_event=..., max_turns=None, wait=None, commands=None, latency=None) -> str` runs turns until `parts.safety.check()` stops it and returns the stop reason (`"hook_limit"`, `"match_over"`, `"round_done"`, `"stopped_button"`, ...). `parts` is a plain object carrying: `brain` (`ask(system, text, images) -> str`), `card`, `screen` (`find`, `in_front`, `grab`), `hands` (`do`, `resume`, `on_stop`, optional `backend` with `keyDown`, `keyUp`, `moveRel`), `safety`, `memory`; and optionally `hooks`, `live`, `screen_watch`, `stop_on_end`, `skills`, `handover`.
- `take_turn(parts, settings, system, timer, on_event, chat, latency) -> Reply | None` does one turn; `None` means nothing was done (no window, or not in front).
- Order inside a turn: grab, screen watch (`watch.look(picture)`), shrink, optional marks, `live.look(frame, ended)`, `live.cached(frame)` (answer without the model), else brain, then skill or chunk or card steps, then `live.acted(frame, names, from_cache)` and `watch.note_action(...)`.
- Before each turn: `hooks.before_step(state)`; after a candidate end with `stop_on_end`: `hooks.before_finish(state)`.

## Hooks (`harness/hooks.py`)

- `state` is a dict with `step` (turns so far), `spent_usd` (the sum of `cost_usd` the brain reported through `brain.last_request`, or `parts.spent_usd()` if given), `won` (`parts.won()` if given), `progress`, `blank_fields`, `match_over`.
- `ControlHooks.before_step(state) -> "continue" | "force_finish"`; `force_finish` means stop the session now with the reason `hook_limit`. `before_finish(state) -> (allowed, reasons)`; a forced finish is always allowed. A refusal is counted in `blocked` and the loop keeps playing.
- `from_spec({"watchdog": {"max_steps", "max_seconds", "max_usd"}, "gate": [{"check": "won"} | {"check": "no_blank_fields"} | {"check": "progress_at_least", "value": 0.9}]})`. An unknown check name raises `ValueError`. A check that raises counts as a refusal.

## Live loop (`universal/live.py`, `tiers.py`, `cache.py`)

- `LiveLoop.look(frame, ended=False, skill_fault=False) -> tier` (settles the previous action's success, runs the router); `cached(frame) -> list[str] | None` (action names, reflex tier only); `acted(frame, names, from_cache=False)`; `summary() -> dict` (tier shares, model calls, served from memory, hit rate).
- `Signals(novelty, progress_delta, repeat_count, skill_fault, tactical_failed, ended)`; `Router.observe(signals) -> Decision(tier, reasons, changed)`. `ended` is a reason for the tactical speed as well as the strategic one. Repeat count: consecutive turns whose action names are identical and non-empty. Cooldowns count router ticks (turns). "Calm" is that many consecutive ticks with no reason.
- `StateActionMemory(capacity=512, max_distance=4, min_trust=0.7)`: `lookup(frame, hud=None)`, `record(frame, hud, action, worked)`. Fingerprint: the picture resized to 9 by 8 (area average), converted to grey with weights 0.299, 0.587, 0.114, each pixel compared with its right neighbour, the 64 bits packed row by row. The action is stored as a tuple of names and compared for equality. When full, the least recently used entry is dropped.

## Chunk grammar (`universal/chunks.py`, `live.py`)

`<|action_start|>dx dy dz; K1; K2 K3; ...<|action_end|>`: the first part holds three integers (mouse movement, each at most 2000 in size); every following part is one 33 ms chunk (`CHUNK_MS`) holding key names separated by spaces, commas or plus signs (`none` or empty = no key); at most 16 chunks; the first block in the answer counts, a malformed block is dropped whole. `run_chunks(raw, allowed, backend, should_stop, sleep=None, allow_mouse=False) -> events performed`; `backend` is anything with `keyDown(key)`, `keyUp(key)`, `moveRel(dx, dy)`. A key stays down while consecutive chunks name it (state-difference holding). `should_stop` is polled between 25 ms slices.

## Controls card

A YAML file per game: `name`, `name_ar`, `window` (the window title), `default_goal`, `genre`, `game_hint`, `actions` (a map from an action name to `{keys, hold, says, says_ar}` or `{wait}` or a click or drag description) and optionally `win_hud`. The loaded card exposes `actions` (name to a record with `kind`, `keys` tuple, `hold`), `uses_clicks`, `window`. Anything a model or memory answers that is not an action name on the card is dropped before a key is pressed.

## Sandbox worker (`skillsmith/_worker.py`, `sandbox.py`, `ast_gate.py`)

- Protocol: one JSON object per line over the worker's stdin and stdout. Parent to worker: `{"code": str, "class": str}` once, then `{"obs": {...}}` or `{"call": method, "args": [...]}`. Worker to parent: `{"ready": true}`, `{"action": {...}}`, `{"result": ...}` or `{"error": str}`.
- `SandboxedSkill(code, step_timeout_ms=50.0, python=None, require_containment=False).step(obs) -> action dict`; a late, failed or malformed answer returns the neutral action `{"move": [0.0, 0.0], "buttons": [], "hold_ms": 0}` and sets `faulted`. `SandboxedProgram.call(method, *args)` is the generic form for other classes (a world model).
- Action schema (`clean_action`): `move` two numbers in -1..1 (anything outside is rejected, not clipped); `buttons` at most 4 names from `BUTTONS` (jump, attack, use, guard, dash, item, confirm, cancel, fire, special); `hold_ms` 0 to 3000; extra keys are dropped. `action_to_tokens(action, dead_zone=0.3)` holds a direction when `|move| > 0.3` and taps each button.
- The gate: allowed imports `ALLOWED_MODULES`; allowed members per module `MODULE_ALLOWED` (numpy: `NUMPY_ALLOWED` plus `linalg`); refused names `BANNED_NAMES`, refused attributes `BANNED_ATTRS`; no `while`, `global`, `nonlocal`, `async`, `await`, `yield`; no number above 10^9 or string above 200 characters; at most `MAX_NODES` (800) syntax nodes; only imports, classes, functions, simple assignments and a docstring at the top level.
- The environment: only `PATH` (empty) and, on Windows, `SYSTEMROOT` and `SYSTEMDRIVE`; `TEMP` and `TMP` point at a private empty folder that is also the working directory. Windows containment: low integrity label `S-1-16-4096`, a job object with kill on close, one active process, a 1 GiB process memory limit and UI restrictions (`MEMORY_LIMIT_BYTES`, `osjail.py`).

## Gates and promotion (`skillsmith/verify.py`, `promote.py`)

- A trace is a list of observation dicts with at least `danger` (0..1) and `escape` (a direction vector); `progress_dir` is optional. A step is dangerous when `danger >= 0.5` and `escape` is present. A move points away when its dot product with `escape` is positive. Gate B needs at least one dangerous step, at least 70 percent of them answered away, and (for traces over 20 steps) a Shannon entropy above zero over the moves snapped to nine directions. Gate A: every answer within the step limit, a valid action, no error, and a p99 latency within `limit_ms` (20 by default). Gate C: a callable that returns whether the live trial's score improved; `None` skips it.
- `Selector.choose(current, scores, validation_seeds, test_seeds=()) -> Decision(promote, name, reason, scores)`: `scores` is one mean score per candidate on the same validation tasks; a candidate must score strictly above `current`; ties keep the current skill; the seeds must not overlap the test seeds; a validation set already used is refused. `Budget(max_usd, max_calls).spend(usd, calls=1)` raises `BudgetExceeded` before the cap would be passed.

## Grounding thresholds

`skin_grounding.probe`: a pixel changed when a colour channel moves by more than 24; a blob needs at least 4 pixels. `flow_grounding.probe_flow`: a region is the set of changed pixels grown by 3; velocity is the phase-correlation slide of the region's crop (padding at least 12 pixels, at least the region's size) with a peak of 0.1 or more (`SLIDE_CONFIDENCE`); a key's binding is the change in velocity against the tick just before, kept when 1 pixel or more; a jump (appeared against vanished centre of pixels that changed only with the key) is used when it is at least 2 pixels and the slide is under 0.4 of it (`SLIDE_OVER_JUMP`) or no slide was measured.

## Result files

`bench/run_condition.py` writes `{schema, written, condition, brain, model, note, overall, by_game, honesty, episodes}`; `overall` and `by_game` carry episodes, wins, win rate, Wilson interval, mean progress, tokens in and out, cost, local-help episodes and skill steps; `honesty` carries the rung, the label and the action-origin shares. The skill library (`skillsmith/library.py`) stores `<root>/.agents/skills/<game>/<name>.py` with a receipt holding a SHA-256 of the code, plus one `EXPERIENCE.md`.

## Platform

Windows only: `universal/winio.py` (per-monitor DPI awareness v2, `GetClientRect` and `ClientToScreen`, `AttachThreadInput` with an Alt tap, `SendInput` with scan codes and the extended flag, integrity level through `OpenProcessToken`), `universal/scan_backend.py`, `skillsmith/osjail.py`. Everything else runs on any platform with numpy.
