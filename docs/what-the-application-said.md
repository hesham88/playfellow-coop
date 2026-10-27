# What the application said, and what this repository shows

The hackathon application was sent on 22 October 2026 and cannot be edited. Some of its sentences describe our larger private prototype, not what is in the two open repositories. This page puts the public facts next to each sentence so that nobody has to search in vain. It is a correction, not a defence. For the full map of what is and is not open, see [research-roadmap.md](research-roadmap.md).

| The application said | What is in the open repositories | Where to check |
|---|---|---|
| A Rust core, about 27 times faster | The Rust code here is a small optional fast path written during the event. Measured on one PC: grid search 17.3 to 23.9 times faster than its Python twin (identical paths), one run, 15 repeats per size. The 27 times figure belongs to the private prototype and cannot be reproduced from public code, so we do not claim it | `rust/README.md`, `results/fastpath_bench-20261027-032325-efc6314.json`, `bench/fastpath_bench.py` |
| Three decision speeds, 20 Hz, Kalman-filter reflexes | The open code runs one single-rate loop: see, mark, think, check, act. The multi-rate research is private and is not claimed | `playfellow_coop/session.py`; the "not claimed" list in `research-roadmap.md` |
| An inverse-dynamics model | Not in either open repository, and not claimed as event work | the honest map in `research-roadmap.md` |
| F9 watches while you play and can record your play | F9 hands over. While you hold the controls the buddy watches nothing and asks no AI, by design | `playfellow_coop/handover.py`, `tests/test_session_and_handover.py` |
| About 2,600 tests, winning in every combination | Only counts a judge can run are quoted. At commit 6d07a5d this repository collects 647 tests in 24 test files with `python -m pytest --collect-only -q`, and they run offline. The engine repository has its own suite beside it. The larger private suite and its mode matrix are not open | `tests/` in each repository |
| About 600 commits in a week | Not something the open repositories can show. Their history is short and dated: the engine has a few snapshot commits behind two tags, and this repository's commits are dated 26 and 27 October 2026. Read the tags and dates, not a commit count | `git log`, tags `before-kickoff` and `pre-hackathon` |
| A model version "1.3" and a model that writes the debrief | The code calls `muse-spark` and no version number. No model writes the hand-back line: it is made only of counted facts (seconds, turns skipped, AI calls made) | `playfellow_coop/__main__.py`, `playfellow_coop/handover.py` |

Numbers on this page come from files in this repository or from commands anyone can run. If a number here and a file disagree, the file is right and this page is the mistake: please open an issue.
