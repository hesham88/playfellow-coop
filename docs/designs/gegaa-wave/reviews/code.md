# Goldfish 4: "mean" code review (2026-10-29)

Reader: a fresh read-only session told to tear the code apart (flow_grounding, live, chunks, hooks, isolation, osjail, ast_gate, _worker, and the session wiring). 22 findings: 5 Blocker, 11 Major, 6 Nit. The reviewer ran the gate on small inputs; it did not run the worker or the OS layer.

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | Blocker | `match` class patterns read attributes as plain strings, bypassing the attribute ban | **Fixed**: `match` refused; test |
| 2 | Blocker | No CPU limit in the worker (nested loops, huge powers) | The parent already kills a worker that answers late (`_ask` timeout then `_fail`, step limit 50 ms; 20 s for the first load). **Fixed**: `**` only with a literal exponent 0 to 16. Off Windows there is still no memory cap (stated) |
| 3 | Blocker | `inf` or `nan` movement raises `OverflowError` in `parse` | **Fixed**; test |
| 4 | Blocker | `forced` and the watchdog clock never reset; gate stays open | **Fixed**: `reset()` on hooks and watchdog, called at session start; test |
| 5 | Blocker | A missing state key passes `no_blank_fields`; a lost match is blocked by a `won` gate | **Fixed**: a missing key is a refusal; a match the game reports over may always stop; session now supplies `progress`; test |
| 6 | Major | Token label size passed to `SetTokenInformation` was not the documented size | **Fixed** (`GetLengthSid`); the existing test that a contained process cannot write a file still passes |
| 7 | Major | Job handle leaked on failure; docstring promised more than it did; "no race" overstated | **Fixed** (handle closed, docstring states partial results and that network is unrestricted) |
| 8 | Major | `NoNetwork` missed `sendto`, `send`, extra lookups; process-wide | **Fixed** (more calls patched, docstring states the limits); test |
| 9 | Major | Executor used a plain sleep, not the promised spin tail; `late_ms` unread | **Fixed**: coarse sleep plus a 1.5 ms spin. `late_ms` is kept as a measurement for the benchmark and is still unread by the loop (open) |
| 10 | Major | Chunk docstring versus code (movement applies to the first chunk only, `dz` unused, plus-sign keys) | Documented in `interfaces.md`; `dz` stays parsed and unused (open) |
| 11 | Major | A release error replaced the original exception | **Fixed**; test |
| 12 | Major | Resized window recorded as a failed key; stale `_asked_last`; no reset; magic number | **Fixed** (constant `MOTION_WORKED`, comparable-shape check, `reset()`); test |
| 13 | Major | `served` overcounted on an empty hit | **Fixed** |
| 14 | Major | `getattr(parts, "won", ...)()` crashes on a plain value | **Fixed** (`_value` helper) |
| 15 | Major | `yield from` passed; parameter names unchecked; two hand-kept member lists | **Fixed** for the first two; a test now compares the two numpy lists |
| 16 | Major | flow_grounding: unmeasured baseline treated as rest, duplicated obstacle boxes, arbitrary avatar choice with two keys, per-key full-frame loops | **Open**: measured to work on the glass games; to be tightened with a larger set of games |
| 17 | Nit | lambda style, redundant list copy, placeholder in `STATE_CHECKS`; spec validation holes | spec validation **fixed** (positive limits, missing value, non-mapping item); style items partly fixed |
| 18 | Nit | A crashing check hid the reason | **Fixed** (the reason names the exception); test |
| 19 | Nit | Token estimate is `len // 4` (wrong for Arabic and code) | **Open** |
| 20 | Nit | `type(c)(...)` instead of `replace` | Left as is |
| 21 | Nit | Keys lower-cased, card casing dropped | By design: key names are compared and pressed in lower case |
| 22 | Nit | Missing tests | added for match and yield from, inf and nan, shape change, hook reuse, missing state key, UDP sends, release errors |

Open after this review: flow-grounding robustness (16), the token estimate (19), unread `late_ms` and unused `dz` (9, 10).
