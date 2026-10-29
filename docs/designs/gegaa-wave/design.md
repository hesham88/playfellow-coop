# Design: a game-agnostic play loop with honest cost control and a sandbox for model-written skills

Written after the fact for work already built (27 to 29 October 2026), so that fresh readers can test whether the document alone explains the system. Method: `docs/egm.md`.

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

## How the pieces decide (added after the first goldfish review)

**Who owns the loop.** `session.play_session` owns it: each turn it calls `take_turn`, which grabs the picture, runs the screen watch, optionally the live loop, asks the model or a skill, and presses keys. The hooks are checked before every turn. `live.py` is a helper object (`parts.live`) the turn consults; it does not run anything by itself.

**Router.** Each turn it gets: novelty (how much of the picture changed, 0 to 1; 0.35 or more counts as novel), whether progress stalled (no change for a set number of ticks), how many times the same action repeated, whether a skill failed, and whether the end-of-game signals fired. Reflex is the default. Any of those wakes the tactical speed if its cooldown allows. An end, or three tactical failures in a row, wakes the strategic speed, with a longer cooldown. The router drops back to reflex only after a calm stretch.

**State-action memory.** A picture is reduced to a 64-bit difference hash (a 9 by 8 grey thumbnail, each pixel compared with its right neighbour). "Near-identical" means at most 4 differing bits and the same coarse HUD reading. Each remembered action carries a trust score, the mean of a Beta(1 + successes, 1 + failures); it is served only at 0.7 or more and only in the reflex speed. After every use the next picture decides success: if the picture changed, the action worked; if not, trust drops, and a distrusted entry is replaced. The memory is cleared when the game or skin changes, so a stale entry cannot outlive its game.

**End of game.** The signals are listed under End-of-game detection. A candidate end is the signals firing on two looks in a row. The free verifier then presses a few different keys that the controls card allows and checks whether anything answers; if nothing does, the match is treated as over. With `--stop-on-end` the session stops; without it the model is told the match may be over.

**Controls card.** A small YAML file per game (the engine's format) listing the allowed actions, the keys behind each, hold times and a short spoken description. The engine drops every action not on it. It is the allow-list, and the chunk executor checks keys against it too.

**Skill interface.** A skill is a class `GeneratedArenaSkill` with `compute_action(obs)`. `obs` is a small dictionary of what the perception step saw (avatar, enemies, items, HUD values, a danger level, a safe direction). The answer is `{"move": [dx, dy] each in -1..1, "buttons": [names], "hold_ms": 0..3000}`; anything else, a late answer or an error becomes the neutral action (press nothing) and marks the skill faulted. The shipped hand-written skills in `skills/` read pixels through calibrated looks instead.

**Three offline gates for a model-written skill.** A: every step answers inside the time limit with a valid action and never raises. B: on recorded steps marked dangerous, at least 70 percent of moves point away from danger, and the moves are not all one direction (a wall lock). C: a short live trial in which the game's own score, or a vision comparison of the HUD, must improve.

**Promotion.** A candidate replaces the current skill only if its score on the validation tasks strictly improves on the current one. The held-out test tasks are never used to choose. The search has a hard cap on dollars and calls, and a second selection round on the same tasks is refused unless the validation set is new (the cited study saw 76.4 fall to 59.1 percent after a second round).

**Sandbox threat model.** The code is untrusted: it may be buggy or hostile. The goal is that it cannot read or write the player's files, see keys in the environment, start other programs or use unbounded memory. Layer one refuses imports outside math, numpy, typing and dataclasses, and any attribute outside a short list per module. The numpy case: the real module reaches files through many functions (memory-mapped files, text loaders, file-based constructors), so blocking names loses; only a short list of array functions exists in the namespace the worker gives the skill. Layer two runs the code in a separate Python process with a clean environment and a per-step time limit. Layer three (Windows) lowers the process's integrity level and puts it in a job object.

**Flags.** `--live on` (router, memory, chunks), `--stop-on-end` (stop when the end is confirmed; needs the screen watch, which is on by default), `--max-steps N` (watchdog), `--input scancode` (press scan codes instead of virtual-key calls). They are independent of one another.

## Glossary

- **Skin or look**: how a game is drawn (colours, sprites); a "look" is the file that tells a skill which colours mean what.
- **Grounding**: finding which thing on screen the keys control.
- **Jump**: a move too large to track as a slide, such as changing lane, measured as where the thing appeared against where it vanished.
- **Change-point test**: a running sum that grows when the picture's summary drifts away from its usual value and fires when the sum crosses a limit.
- **Held-out check**: the screen classifier was fitted on some games and tested on a game it had never seen; it failed.
- **Glass window**: the new desktop window of the private product (private repository, out of scope here). **Private engine**: the older private play loop that window runs.
- **GEGAA**: Generalist Embodied Game-Agnostic Agents, the name in `docs/gegaa.md`. **EGM**: the Elephant-Goldfish Model, `docs/egm.md`. This document does not depend on either to be understood.
- **Sources of the numbers above**: `results/unseen/` (27 October, 0 of 15, $1.19) and `results/glass/muse-skills-20261029.json` (29 October, 15 of 15, $0.042).

Not done and stated plainly: no live run on a real window yet (the desktop was locked, so key holds, focus and pacing on a real window are untested, and every result so far is on the game's own paused clock); the OS containment layer exists only on Windows; the tiers router, memory and chunks are not in the glass window's loop.
