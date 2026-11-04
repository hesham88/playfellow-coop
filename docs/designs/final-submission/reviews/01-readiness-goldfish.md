# Goldfish review 1: implementation readiness (fresh reader, design path only)

Verdict: not ready as first written. Twelve findings, all accepted; the design's section 5 records how each is answered.

1. `__main__.py` imports the engine at the top, so `doctor` would fail on the very machine it should diagnose. Dispatch must run before any engine import.
2. `keys` needs `keyring`, which is in no dependency list; the `all` extra's contents were not listed.
3. `stk` forwarded to an undefined target among several runnable modules.
4. The follow contract (engine `WindowBox` left/top/width/height vs the view's left/top/right/bottom; client area or frame; exceptions) was not stated, and the file table named two places for it.
5. Data sources for `models`, `games` and the engine-tag check were not named.
6. `build_overlay` is called positionally; a new parameter would break the existing fakes.
7. `DESIGN.md` says the key lives in the engine's keyring service; the code uses `playfellow-coop`.
8. Key handling: hidden input, status names only the source, the environment variable wins over the store, sentinel-key tests over stdout and stderr.
9. `doctor --fix` changes the machine: print the plan and ask, or take `--yes`; tests inject the runner.
10. `bootstrap.sh` had no stated purpose on a non-Windows machine.
11. Tests must inject window listing, keyring, pip and git, and `follow` must be cheap and never raise (it runs on every widget tick).
12. No test named for "every existing flag unchanged".
