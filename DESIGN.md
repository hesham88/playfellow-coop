# playfellow-coop: design note

Status: design note for the plugin. The engine is installed from a clone of the tag `pre-hackathon`; nothing here copies it.
Sources: a survey of the engine's public hook points, with file and line, made at the tag.

## 1. What it is, in one paragraph

`playfellow-coop` is a small plugin package for the open PlayFellow engine. The engine is a buddy that watches one game window, asks a brain what to do,
and presses only keys on that game's controls card. This package adds, during the event: a Muse brain, SAM marks that label what is on screen, a stage timer with a
speed benchmark, and a hand-over mode where the player and the buddy pass the controls back and forth. It contains **only** event work. The engine is installed from
its public repo at the tag `pre-hackathon` and is never copied here.

## 2. Repository layout (all new files, all written during the event)

```
playfellow-coop/
  README.md              first lines: what pre-existed (the engine, public since 22 Oct, tag pre-hackathon) and what is new
  DESIGN.md              this note, trimmed
  pyproject.toml         depends on playfellow @ git+https://github.com/hesham88/playfellow@pre-hackathon
  playfellow_coop/
    __init__.py
    __main__.py          `python -m playfellow_coop ...`: the plugin's own entry point (it owns main())
    muse_brain.py        MuseBrain: ask(system, text, images) -> str, against the Meta Model API
    sam_marks.py         SamMarker: marker(image) -> list[Mark], built on the engine's grounding.mark_from_box
    stage_timer.py       StageTimer, STAGES, and thin timing wrappers around the engine's parts
    handover.py          HandOver: take the controls back with F9, give them back, say what happened
    session.py           the turn loop (written fresh; it calls the engine's public building blocks one by one)
  bench/
    speed_bench.py       runs N turns, writes one pf-results/1 file
    README.md
  results/               files written by the bench (only measured numbers, never typed)
  tests/                 fake-server tests; no network, no real keys, no real key presses
  demo/script.md         the 3-minute plan (opens with the one-line disclosure)
```

## 3. How it plugs into the engine (rule: no patching, no new engine hook, no copy of the engine's loop)

The plugin owns `main()` and a short turn loop of its own. The loop calls the engine's PUBLIC building blocks one by one and times
each stage itself. Every call below was checked in the public engine at b7b72a8 (`software/...`); all are plain public names.

| Stage / job | Engine function the plugin calls | Where | Public name? |
|---|---|---|---|
| Find the game window | `Screen.find(title)` | `eyes.py:140` | yes |
| Is it in front? | `Screen.in_front(title)` | `eyes.py:173` | yes |
| capture | `Screen.grab(box)` | `eyes.py:190` | yes |
| shrink | `shrink(image, width)` | `eyes.py:26` | yes |
| Click grid for click games | `add_grid(image)`, `ControlsCard.uses_clicks` | `eyes.py:33`, `controls.py:72` | yes |
| Marks on the picture | `Parts.marker`-style call to the plugin's SAM marker, then `label_marks`, `draw_marks`, `legend` | `grounding.py:44, 58, 112` | yes |
| The prompt | `system_prompt(settings, card)`, `turn_text(goal, memory_text, chat, captain_note, ...)` | `brain/prompts.py:14, 89` | yes |
| Memory of the last steps | `Memory.add/recent/as_text`, `Moment` | `memory.py:23, 26, 32, 11` | yes |
| request (the Muse call) | the plugin's own `MuseBrain.ask` | plugin | n/a |
| parse + reply check against the card | `parse_reply(raw, card, max_actions)` (drops off-card actions) | `reply.py:64` | yes |
| key down | `Hands.do(step, box)` | `hands.py:53` | yes |
| Stop / release | `Hands.on_stop()`, `Hands.resume()`, `CornerStop` | `hands.py:254, 261, 16` | yes |
| Limits, F12, waiting | `Safety.start/check/stop/wait/count_ai_call`, `listen_for_f12` | `safety.py:21, 55, 32, 63, 47, 85` | yes |
| Window rules | `is_blocked(title)`, `needs_online_warning(title)` | `games.py:162, 154` | yes |
| Load the card | `load_card(path)` | `controls.py:109` | yes |

Flags: (1) `play._look` is private (leading underscore) and `play.take_turn` is deliberately not used, so the plugin writes its own
look step with `add_grid`, the SAM marker and `label_marks/draw_marks/legend` (about 8 fresh lines). (2) `play.MEMORY_IMAGE_WIDTH`,
`MAX_ERRORS_IN_ROW` and `MAX_WAIT_SECONDS` are plain constants in `play.py` (lines 42-44); importing `play` for three numbers pulls in
the whole module, so the plugin defines its own constants. (3) `Safety.stopped` is a property (`safety.py:43-45`), not a method. (4) The brain
registry stays closed (`--brain muse` does not exist in the engine); the plugin's own entry point selects the Muse brain. (5) The
install needs EXP-1 (`pyproject.toml`, squashed as b9e3517) and `pip install -e` of the engine.

## 4. The pieces

### 4.1 `muse_brain.py`
- Talks to the Meta Model API with the OpenAI-compatible request shape (images as data URLs, JSON reply). Base URL pinned in one constant, like the engine's `ENDPOINTS`.
- The key comes from the player's own credential store (the engine's keyring service), under its own entry name. The owner's key never ships and is never printed.
- Never uses Contributor mode and never sends play data for training; Standard mode only (Meta API terms). Model names appear as plain text; no Meta marks.
- Returns the raw text; the engine's `parse_reply` does the checking against the card.
- Failure mapping: 401/403 -> `BrainError("bad_key")`, 429 -> `BrainError("busy", retry=True, wait_seconds=...)`, 5xx/timeouts -> `busy` or `offline`. A BrainError detail never carries the request body.
- Records `request_sent` and `last_byte` itself. `first_byte` only if the API streams; if it does not, the results file says `first_byte: not measured`.
- Uses a plain httpx client with `trust_env=False` and certifi roots (the same promise as the engine's brains), so a proxy variable or a CA variable cannot redirect a screenshot.

### 4.2 `sam_marks.py`
- `SamMarker(call)`: `call(image, prompts)` returns masks/boxes; the marker converts each to a `Mark` with `mark_from_box(kind, box, size)` and returns the list. The engine labels, draws and explains them (`label_marks`, `draw_marks`, `legend`).
- Closed loop, not a describer: see -> mark -> act -> check. Marks feed the next action; the results file reports what the marks changed (success rate, steps), not captions.
- Keyframes only (SAM is slow): the marker caches by a cheap picture hash and re-asks when the picture changes enough.
- Reports precision, recall and latency against the Practice Arena's known object positions (a measured file, not a claim).

### 4.3 `stage_timer.py`
- `STAGES` is one list: capture, shrink, encode, request_sent, first_byte, last_byte, parse, reply_check, key_down. (`change_test` is dropped: the
  engine has no such step and we do not report an unmeasured stage. It returns only when the "think on scene change" experiment builds a real one.)
- `StageTimer` is a small context manager: `with timer.stage("capture"): ...` records `time.perf_counter()` per stage into a per-turn dict. The
  plugin's own loop wraps each engine call in it, so there is no patching and no wrapper objects.
- Honest limits (stay in the README): `encode` is measured only for the Muse brain (the engine's other brains encode inside their SDK call);
  `first_byte` only if the API streams, otherwise the results file says `not measured`; `parse` and `reply_check` are the two halves of
  `parse_reply`, which is one call, so they are reported as one stage `parse_and_check`.
- No number is typed in anywhere. The bench writes only what it measured.

### 4.4 `handover.py`
- F9 (global hotkey) toggles who has the controls. Player takes over: `hands.on_stop()` (keys released at once), the loop stops asking the AI, nothing is pressed. Player hands back: `hands.resume()`, the loop asks again.
- The spoken summary after a hand-back is built from facts the plugin counted (turns taken, keys pressed, seconds), never from a model's guess.
- F12 and the corner stop still end everything; this module never weakens them (the engine's `Safety` stays in charge).

### 4.5 `session.py` (the plugin's own loop, written fresh, about 40 lines)
Start `Safety`, `Hands.resume()`, then loop `while safety.check() is None`: skip the turn when the human has the controls; otherwise find
the window, check it is in front, grab, shrink, add marks, build the prompt, ask the brain, `parse_reply`, press each step with `Hands.do` while
`safety` has not stopped and the window is in front, store the moment in `Memory`. Each step sits inside a `timer.stage(...)`. Errors use `BrainError`
(`key`, `retry`, `wait_seconds`) with a retry rule written here. `Hands.on_stop()` always runs in `finally`.

## 5. Tests (all offline, red first)
1. MuseBrain against a real fake server on 127.0.0.1: request shape, JSON reply, each error code mapping, the pinned base URL, a proxy variable receiving nothing, an `SSL_CERT_FILE` certificate not trusted, the key never in any error/log/repr.
2. SamMarker with a fake SAM server: boxes become marks, the legend is right, a slow call is cached.
3. StageTimer: with fake eyes, brain and hands one turn emits every stage in order, each > 0; a brain that sleeps 300 ms lands in the request stages and < 50 ms everywhere else.
4. HandOver: after F9 no key is pressed and the AI is not asked; after the hand-back both resume; F12 still stops.
5. Bench: writes one file with commit, machine, load flag, brain/model and p50/p90/p95 per stage; a dirty tree is labelled diagnostic.
6. A scan test: no file in the package contains a word from the banned list (kept in the test as data), and none imports a private (non-public) engine module.

## 6. Compliance rules baked into the repo
- First lines of the README: the one-line disclosure (what pre-existed, what is new) and the pinned engine tag.
- Only the owner is named as the human author; the README says it was built with AI coding assistance.
- Demo games: our Practice Arena, the arena pack and one open-source game. The video shows actions and results, not descriptions.
- Wording: the buddy "plays and talks". The banned words in report 11 section 4 appear nowhere, and the engine's internal helper brain part is not imported by name or described.
- The course, the tutor and the product pages are not part of this repo.

## 7. Risks and open points
1. The organisers' answer on the fresh-repo structure is pending; nothing is pushed until the owner has it.
2. Decided: no patching and no new engine hook; the plugin composes the engine's public functions itself.
3. The engine's modules are top-level, so the install is `pip install -e` of a checkout (data files stay next to the code).
4. Muse access and credits depend on the owner's card and the day-4 yes; until then every Muse test uses the fake server.
5. `first_byte` may be unmeasurable if the API does not stream.
6. Time: Glimmer-class local models need a 24 GB GPU (D66); the open-weight bonus needs a hosted partner route.
