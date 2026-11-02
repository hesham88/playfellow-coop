# K lane to architect — for review and merge

Branch `muse/k-harness`. One commit, noreply identity, no trailer lines. Untouched, as agreed: the assist module, `play_session()` in `session.py`, `tests/test_assist.py`, the access-proof doc, bench code and existing results (only `results/k-lane/` is added beside them). The `take_turn`/`_press` edits in `session.py` are the pre-existing lane work.

## What changed

1. GoalChecker (D2 strict), `playfellow_coop/universal/state.py`: a number counts only with the goal word right next to it (at most a space, colon or dash between, either order). "Score 3 / Level 1" and "Level 1 | Total 3" do not satisfy "reach level 3"; "Level 3" and "Level: 3" do. Arabic-Indic digits (U+0660..U+0669, U+06F0..U+06F9) read as plain digits in the goal and on screen. This is the check the assist's "is it done" question depends on, so a stray score can no longer end a task early.
2. ADK eval, `playfellow_coop/adk_app/arena_eval/run.py`: `output_file` is passed only when the installed `AgentEvaluator.evaluate` signature accepts it (by name or through `**kwargs`). Older ADK writes no per-case rows and reports a miss as one assertion for the whole set; with no assertion, every case met the criterion and the answers stay blank rather than invented, and with an assertion the run says plainly that per-case results need the pinned environment.
3. Media guard, `tests/test_media_guard.py`: fails on any image, video or audio file whose file name carries one of three named outside games, anywhere in the repo.
4. Judges entry: `.env.example` (key names only) and `JUDGES.md` (replay with no key; offline play with no key; live with the reader's own keys; test it yourself on a game). Every command in it was run once on this machine and the output pasted.
5. README status table: the stale "fake server only / no live call yet" line is replaced with what the files prove — live capped calls recorded 2026-10-31 in `results/k-lane/`, labelled **Assisted** (the model started local skills), Practice Arena L0, never model alone. Split controls stays planned until you merge it.

## Test discipline (failing test first, then fix, then planted defect)

- GoalChecker: new tests in `tests/test_k_harness.py` failed first on "Level 1 | Total 3" (same line, wrong noun). After the fix: 13 passed in that file. Planted defect (loose same-line pairing restored): the strict test failed; fix restored, green again. Note: the spec string "Score 3 / Level 1" already read as not-done before the fix, but for the wrong reason — the fuzzy word match reads "score" as a shop word. The planted case above is the one that proves adjacency.
- ADK: new signature test in `tests/test_adk_eval.py` failed first (no helper; the real run also raised `TypeError` on google-adk 2.0). After the fix: green on google-adk 2.0 (ad-hoc venv, 4 passed) and on the pinned google-adk 2.13 environment (4 passed, `-W error`). Planted defect (always pass `output_file`): the signature test failed; restored, green.
- Media guard: tests failed first (no scanner). After: 2 passed. A planted file in a temp tree and a planted file in this repo (`docs/img/`) both made it fail; both removed, green again.

## Whole suite

One process, `python -m pytest -q -W error` in this worktree (1304 collected): **1038 passed, 265 skipped, 1 failed** in 1367 s.

The one failure, by name: `tests/test_adk_eval.py::test_adks_evaluator_scores_a_real_case_from_our_export` — `ModuleNotFoundError: Eval module is not installed, please install via pip install "google-adk[eval]"`. Cause: this machine's main environment carries a bare google-adk 2.0.0 with no eval extras, so the test runs instead of skipping and stops inside ADK itself. The same file is green where the eval extras exist: google-adk 2.0 ad-hoc venv (4 passed) and the pinned google-adk 2.13 environment from `tools/adk_env.py` (4 passed, `-W error`). In CI's main job ADK is never installed, so the test skips there. No other failure.

## Findings worth a look

- The shop-line word match is loose: "score" reads as a shop word ("store", one letter apart), so a score line can be dropped from goal checks. Not changed here; the strict adjacency fix makes the D2 case correct either way.
- This machine lacks the engine's input dependency (`pydirectinput`), so the live and offline-play commands stop at that install step here; their outputs in `JUDGES.md` say so. The `--assist` flag is not on this branch yet; `JUDGES.md` shows its current output and the working `--typed` run beside it.

## Paid runs: hypotheses and caps — one question for the owner

No paid run was made from this lane. Proposal, as one question:

> May we run three capped rows on Practice Arena L0 (4 games x 3 seeds, minimal effort), total cap $1.25?
> (a) Model alone, skills off, marks off, Muse brain — cap $0.50. Tests whether the PT1 wins need local skills at all.
> (b) Assisted with marks on, same grid — cap $0.50 plus 100 mark calls. Tests whether marks change the matched and won counts against the marks-off PT1 row.
> (c) Model alone on the open-weights service, same grid — cap $0.25. Tests whether the result follows the harness or the provider.
> Every row labelled **assisted** or **model alone**; the daily cap file stays the outer bound.

## Files in this commit

Tracked, modified (12): README.md, RESPONSIBLE_USE.md, bench/arena_run.py, docs/gegaa.md, playfellow_coop/adk_app/arena_eval/run.py, playfellow_coop/session.py, playfellow_coop/universal/README.md, playfellow_coop/universal/__init__.py, playfellow_coop/universal/actions.py, playfellow_coop/universal/state.py, playfellow_coop/universal/timing.py, tests/test_adk_eval.py.

New (5): .env.example, JUDGES.md, to-architect.md (this file), tests/test_k_harness.py, tests/test_media_guard.py.

Results, added untouched (5): results/k-lane/baseten-skills.json, results/k-lane/latency-scripted.json, results/k-lane/muse-probe.json, results/k-lane/muse-skills-pt1-billing-failed.json, results/k-lane/muse-skills-pt1.json.
