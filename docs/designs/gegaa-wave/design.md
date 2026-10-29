# Design: a game-agnostic play loop with honest cost control and a sandbox for model-written skills

Written after the fact for work already built (waves 1 to 10, 27 to 29 October 2026), so that fresh readers can test whether the document alone explains the system. Method: `docs/egm.md`.

## Problem

An assistant that plays a game it has never seen has three recurring trouble spots. It cannot tell from the screen when a match is over, or which thing on screen answers its keys, when the game looks different from the last one. Asking a large model for every key press is too slow and too expensive, so most turns should be answered by cheap local code. And a model that writes its own controller for a new game produces code nobody has read, which must be kept away from the player's files and secrets. This design covers the loop that handles those three things and the rules that keep it honest and safe, without any hook into a particular game.

## Technical Plan

The loop looks at the picture, decides which of three speeds should act, and presses keys through one guarded path.

```
screen -> frames -> screen watch (end-of-game signals) --+
                 -> grounding (which thing answers keys?) +--> router --> reflex: a local skill (sandboxed)
                                                                     --> tactical: the model, short key chunks
                                                                     --> strategic: the model, rare, replans
router/cache/chunks -> action binder + card allow-list -> hold timing -> keys into the real window
hooks (watchdog, completion gate) wrap the loop; an honest report says who produced each key
```

- **End-of-game detection** (`universal/eog.py`, wired by `universal/watch.py`): signals that do not depend on how a game over screen looks: the picture stops answering keys, a score or health bar resets or vanishes, the central picture freezes while keys are pressed, a slow change-point test on a cheap picture summary fires. A free verifier presses a few different keys and checks whether anything answers. The session can stop on a confirmed end (`--stop-on-end`).
- **Grounding** (`universal/skin_grounding.py`, `universal/flow_grounding.py`): the avatar is found from key presses alone. For still worlds it is what changes only when a key is pressed. For worlds that move on their own it is the region whose velocity changes with a key, measured against the tick just before; teleports (a lane change) are measured as jumps. The result recolours a skill's look so a skill written for one skin runs on another.
- **Cost levers** (`universal/tiers.py`, `cache.py`, `chunks.py`, `live.py`): a router picks reflex, tactical or strategic from cheap signals with cooldowns. In calm repeating play a state-action memory answers with no model call when a near-identical picture worked before; each use updates its trust. A model answer in chunk form is played as timed holds, only on keys the active controls card binds, and every key comes back up. All of it is off unless `--live on`.
- **Input physics** (`universal/hold.py`, `winio.py`, `scan_backend.py`): hold times follow from the game's poll rate (a tap shorter than a frame can be missed), opposite directions are cleaned, input goes into the real window as scan codes with per-monitor DPI handling and a focus lock.
- **Model-written skills** (`skillsmith/`): a model writes a class; a static gate allow-lists modules and their members; the code runs in a separate process that is only given proxy namespaces (never a real module), with a scrubbed environment and a hard time limit per step; on Windows that process also runs at low integrity inside a job object that allows no second process and caps memory. Three offline gates decide whether a skill may play. A promotion rule requires a strict improvement on held-out episodes.
- **Hooks and clean evaluation** (`harness/hooks.py`, `evalkit/isolation.py`): a watchdog ends a session at a step, time or dollar limit; a completion gate refuses to stop before its checks pass; checks come from the game, never from the model grading itself. An evaluation can run with the network off, with a size limit on the always-on prompt and a ledger of what the whole improvement search cost.
- **Honest report** (`evalkit/attribution.py`, `bench/arena_run.py`): every result file says who produced the keys (a person's skill, a model's skill, a model chunk, the fallback) and labels the row accordingly.

## Alternatives

- **A screen classifier for game over.** Rejected: measured on every test game it failed the held-out check, so nothing ships; only a strict black-frozen loading rule remains.
- **Ask the model on every turn.** Rejected: measured at 0 wins of 15 and $1.19 for raw-pixel play on 27 October; one decision that starts a skill won 12 of the first 12 episodes in the next paid run (2026-10-29).
- **Block dangerous numpy functions by name.** Rejected after a security review: the module reaches files by more names than a list can keep up with. The gate and the worker allow-list members instead.
- **Run skills in the main process with restricted builtins.** Rejected: one gate bug would reach the player's files and keys.
- **A learned world model as the only planner.** Kept as an option behind a trust check (`agent/worldmodel.py`), not the default: it must predict real transitions before it is used.
- **Reading the game's own memory or hooks.** Rejected by principle: the system plays from pixels and keys like a person, so it works on any game and on online games without touching them.

## Detailed Implementation

Every file below already exists; the reason is why it is part of this design.

Public repository `playfellow-coop`:

| File | Why |
|---|---|
| `playfellow_coop/universal/eog.py` | end-of-game signals and the free probe verifier |
| `playfellow_coop/universal/watch.py` | screen watch that runs the signals and tells the session |
| `playfellow_coop/universal/skin_grounding.py` | avatar from key presses in still worlds; look recolouring |
| `playfellow_coop/universal/flow_grounding.py` | avatar in worlds that move on their own |
| `playfellow_coop/universal/hold.py`, `chunks.py`, `winio.py`, `scan_backend.py` | input physics and key chunks |
| `playfellow_coop/universal/cache.py`, `tiers.py`, `live.py` | router, state-action memory, live-loop switch |
| `playfellow_coop/skillsmith/ast_gate.py`, `_worker.py`, `osjail.py`, `sandbox.py` | the three sandbox layers |
| `playfellow_coop/skillsmith/verify.py`, `promote.py`, `loop.py`, `synth.py`, `library.py` | gates, promotion, improvement loop, synthesis, skill library |
| `playfellow_coop/harness/hooks.py` | watchdog and completion gate |
| `playfellow_coop/evalkit/isolation.py`, `attribution.py`, `stats.py` | clean evaluation, who played, statistics |
| `playfellow_coop/session.py`, `playfellow_coop/__main__.py` | wiring and the flags `--live`, `--stop-on-end`, `--max-steps`, `--input scancode` |
| `tests/test_eog.py`, `test_skin_grounding.py`, `test_flow_grounding.py`, `test_realtime.py`, `test_skillsmith.py`, `test_hooks_isolation.py`, `test_session_and_handover.py` | the checks for each piece |
| `docs/gegaa.md`, `docs/egm.md`, `README.md` files | the explanation a new reader starts from |

Private repository: `tools/live_skills.py`, `tools/eog_check.py`, `tools/grounding_check.py`, `tools/flow_check.py`, `tools/gym_check.py` measure the pieces on the new look; `software/nav/self_model.py` finds motion on smooth sprites; the glass window runs the private engine's own loop and does not yet use `universal/live.py` or the hooks.

Not done and stated plainly: no live run on a real window yet (the desktop was locked); the OS containment layer exists only on Windows; the tiers router, memory and chunks are not in the glass window's loop.
