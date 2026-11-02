# Cold judge run, 2026-11-02

A fresh folder (`tmp/judge-cold-20261102/`), a clean virtual environment, and the JUDGES.md steps followed word for word. Clones were taken from the local mirrors of the same repositories (no GitHub fetch in the sandbox); every later command is exactly as printed in the README and JUDGES.md. Times are wall clock on this machine.

| Step | Result | Time |
|---|---|---|
| Clone the engine at `pre-hackathon` | ok | 3.7s |
| Clone this repo | ok | 14.3s |
| `python -m venv .venv` | ok | 24.0s |
| `pip install -e playfellow` (engine) | ok | 248.1s |
| `pip install -e .` (this repo) | failed: network unreachable, pip retried for 395.0s (`WinError 10051`) | 395.0s |
| `pip install pytest setuptools` | failed the same way | 341.5s |
| Same installs with `uv pip install` (cached wheels) | ok | 12.1s |
| JUDGES part 1: `pytest tests/test_record_replay.py` | **40 passed** | 5.0s (1.41s inside pytest) |
| JUDGES part 2: `bench.access_bench --seeds 1 --games snake,box_push` | done 4/4, 0 breaches | 15.7s |
| JUDGES part 2: assist tests | 39 passed, 2 skipped | 4.7s |
| JUDGES part 4: `pytest tests/test_arena_run.py` | 14 passed | 8.1s |

**How long a judge waits before the first replay:** about **5 minutes** from an empty folder on this machine (307s on the working path), and almost all of it is installing the engine's dependencies. Once installed, the first replay itself takes 5 seconds. Nothing in the repo's own code broke: every JUDGES.md command that can run without a key passed exactly as printed. The one failure was the sandbox network dropping during `pip install`, where pip's retries alone cost about 12 minutes; with a reachable index (or cached wheels) the same step takes seconds. JUDGES part 3 needs the judge's own key and was not run; it refuses without one, as printed.
