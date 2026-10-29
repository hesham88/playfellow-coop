# Goldfish 2: critic review (2026-10-29)

Reader: a fresh read-only session given design.md and the public files it names; it ran the static gate on one escape sample. 20 findings: 5 Blocker, 5 Major, 10 edge cases and nits. About a third changed the code, the rest changed the document.

| # | Sev | Finding | Resolution |
|---|---|---|---|
| 1 | Blocker | Gate accepts a generator-expression frame walk (`gi_frame.f_back.f_globals`) to the worker's real `__import__`; `str.format` reads attributes named in the string | **Fixed in code**: frame, traceback and `mro` attributes, `format`, `format_map` refused; `format` removed from the worker builtins; test added. The worker-side hardening is an open item |
| 2 | Blocker | Chunk path plays mouse motion not on the card | **Fixed**: mouse only when the card has clicks; test |
| 3 | Blocker | Key names compared in different letter case | **Fixed**: lower case both sides; test |
| 4 | Blocker | A failed release leaves other keys down; long holds not interruptible | **Fixed**: all keys released, error re-raised; 25 ms slices; test. A hard process kill stays open, stated |
| 5 | Blocker | Dollar watchdog not wired in the CLI | **Fixed**: `--max-usd`, `--max-seconds`; the session sums the cost the model calls report; test |
| 6 | Major | Router numbers and novelty meaning wrong in the document; `tactical_failed` never set | **Fixed**: document corrected; `tactical_failed` now set when a model answer leaves the picture unchanged |
| 7 | Major | Memory: HUD key dead in the live loop, trust formula, success measure, replace rule | document corrected (honest weaknesses listed) |
| 8 | Major | `ProbeVerifier` not wired; pressing keys on a game-over screen is risky | document corrected; left unwired on purpose |
| 9 | Major | Gate B passes a trace with no danger; gate C optional | **Fixed**: B must be exercised; C skip stated |
| 10 | Major | Promotion bookkeeping in memory only | document: known gap |
| 11 | Edge | Docstring promised resource limits off Windows | **Fixed** (docstring) |
| 12 | Edge | Containment can fail silently | **Fixed**: `require_containment` option |
| 13 | Edge | One late step faults the skill for the session | document |
| 14 | Edge | Chunks bypass the opposite-direction cleaner | **Fixed**; test |
| 15 | Edge | Per-call spend cap only daily and per machine | document |
| 16 | Edge | Skill run bounded by `hold_ms` up to 3000 | document (25 ms slices bound the stop) |
| 17 | Edge | `--stop-on-end` depends on the screen watch | document |
| 18 | Nit | "Two looks in a row" unverified | verified in `watch.py` (end_candidates after two consecutive looks) |
| 19 | Nit | Module-level assignment can allocate memory at import | document |
| 20 | Nit | Abstract buttons map to real keys without a card check | open item, stated |
