# playfellow-coop

**Built on the PlayFellow engine (hesham88/playfellow). Two tags say what existed when: before-kickoff = b7b72a8 (committed 08:04, pushed 12:01 on 26 Oct, before the kickoff); pre-hackathon = d63c1b4 (pushed 19:33 on 26 Oct), re-exporting engine work finished before the kickoff in our private repo (LM Studio adapter, memory check, proxy/CA hardening, redaction, game clock), plus packaging. Everything in this repo was built during the event.**

PlayFellow is an open-source engine that plays a PC game *with* you: it watches one game window, asks a brain what to do next, and presses only the keys that game's controls card allows. This repo adds the event work as a plugin package. It does not contain the engine; it installs it.

## What is new in this repo

| Piece | What it does | Status and honest limits |
|---|---|---|
| `playfellow_coop/muse_brain.py` | A brain that asks a Muse model on the Meta Model API what to do. Pinned address, no proxy or CA variables, redirects refused, the key never shown | built; tested against a fake server only. **No live call yet**: the endpoint path and usage field names are unverified until the first capped real call |
| `playfellow_coop/budget.py` | A daily spending cap (dollars and calls) kept in a small file; a call over the cap is stopped before it is sent | built; prices are the published Standard prices for muse-spark |
| `playfellow_coop/handover.py`, `session.py` | **You take over, I take over.** F9 takes the controls: every held key is released, the buddy presses nothing and asks no AI. F9 again hands them back with a one-line summary made only of counted facts (seconds, turns skipped, AI calls made). F12 and the mouse corner still stop everything | built; tested with pretend eyes, hands and brain. **Not yet run live on the Practice Arena** |
| `playfellow_coop/stage_timer.py`, `bench.py`, `bench/speed_bench.py` | Times capture, shrink, encode, request, parse-and-check and key-down per turn and writes one `pf-results/1` file (p50, p90, p95) | built; offline-tested. `encode` is measured only for the Muse brain; `first_byte` and `change_test` are not measured, and the file says "not measured" instead of inventing a number. **No live run yet** |
| `playfellow_coop/sam_marks.py`, `sam_eval.py` | SAM 3.1 marks: where things are on screen, drawn as numbered labels on the picture the buddy sees, with the engine's own legend. Asked again only when the picture changes; every request is gated by the daily budget | built and tested against a **fake server** built from the Practice Arena's own truth. **No real SAM call yet**: the response wrapper is unverified. The scores from the fake server check the harness only and say nothing about SAM's accuracy |
| `playfellow_coop/voice.py` | Voice commands ("grab the coins on the left") with Muse Voice Transcribe in file mode (push-to-talk), and **typed commands as the fallback**, so the demo never needs a microphone. The command goes to the planner next to the marks; only keys on the controls card are pressed | built; offline-tested (`tests/test_voice.py`). No real voice call yet |
| `playfellow_coop/realtime_voice.py`, `push_to_talk.py`, `microphone.py` | **Hold a key, speak, release.** The microphone streams to Muse Voice Transcribe over a WebSocket; partial text shows live; the final words become a command; a typed line works the same. The key goes only in the handshake frame. It also measures the time from letting go of the talk key to the buddy's first game key | built and tested against a **fake WebSocket server** and a pretend microphone. **Not yet run against the real service or a real microphone**: the frame format comes from our notes, so the first real call saves the real frames as a fixture before anything else builds on them. The measured key-release-to-first-key time is "not measured" until a live run |
| `rust/fastpath`, `playfellow_coop/fastpath.py`, `bench/fastpath_bench.py` | An **optional Rust fast path** (grid search and the thumbnail change test) with an identical Python twin; tests require identical answers; the speed-up is measured by the bench | built during the event; see `rust/README.md` |
| Split controls ("you block, I heal") | Share the keys between you and the buddy | planned, a stretch goal |

Items marked planned are not built: a row changes only when a dated commit shows it.

## Install and run

Python 3.11 or newer. Put the engine and this repository **side by side in one folder** (the tests look for the engine next to this repository, or at the folder named in `PLAYFELLOW_ENGINE`), and use one virtual environment for both:

```
python -m venv .venv
.venv\Scripts\activate
git clone --branch pre-hackathon https://github.com/hesham88/playfellow.git
pip install -e playfellow
cd <this repository's folder>
pip install -e .
pip install pytest setuptools
```

The engine's controls cards and settings files sit next to its code, so the engine is installed editable (`-e`), from a clone of the tag. `pytest` is not installed by the package, and `setuptools` is needed by one install test on Python 3.12 and newer.

## How to run the demo (no microphone needed)

1. Install as above, then open the Practice Arena from the engine: `python -m practice_arena.arena` (in the engine's `software` folder).
2. In this repo, start the buddy with the built-in brain, which needs no key and no network, and with typed commands:

   ```
   python -m playfellow_coop --typed
   ```

   With a Muse key in `MODEL_API_KEY`, add `--brain muse` (SAM marks are then on by default; `--marks off` turns them off). To talk instead of typing, add `--talk-key f8` and hold F8 while you speak.
3. Click the arena window so it is in front: the buddy presses keys only while the game is in front.
4. **You take over, I take over.** Press **F9**: the buddy lets go of every key and waits, asking no AI. Play yourself. Press **F9** again: the buddy takes the controls back and says in one line how long you played and how many turns it waited out.
5. Type a command in the terminal, for example `grab the coins on the left`, and press Enter. It goes to the planner on the buddy's next turn.
6. **F12**, or the mouse in the top-left corner, stops everything at once.

What was checked, and what was not: the hand-over, the typed commands and the marks are tested offline with pretend eyes, hands and a fake server. They have not yet been run live on the Practice Arena, and no real Meta call has been made.

## Tests

```
python -m pytest -q
```

To use the Muse brain, put your own key in the environment as `MODEL_API_KEY` (Meta's name for it) or in the Windows credential manager. It is never read from a file in this repo, and it is never printed. Then:

```
python -m playfellow_coop --brain muse --marks sam  # F9 takes the controls, F9 again gives them back, F12 stops
python -m playfellow_coop --brain local-open --model <id>  # an open model on this PC through LM Studio (the engine's memory check runs first)
python -m playfellow_coop --overlay                # the floating command center (Ctrl+Alt+P opens and closes it); built, offline-tested, NOT yet run live: see docs/owner-live-checks.md
python -m playfellow_coop                     # the same with the engine's built-in brain (no key, no network)
```

Without the optional Rust DLL (see `rust/README.md`), the tests that compare it with its Python twin are skipped, not failed. Every test runs offline: a fake server on 127.0.0.1 stands in for the Meta API, and nothing presses a key, grabs the screen or spends money.

The realtime voice socket refuses a redirect (the key is never sent to wherever a server points): that holds on websockets 16.1.1 and 17.3, the two versions it is tested on, so `pyproject.toml` allows only `websockets>=16,<18`.

## What this does and does not do

It plays and talks with you. It does not judge or score the player. The demo uses our own Practice Arena, the arena pack and one open-source game.

## Contributing

This is an open project, and the maintainer reviews every contribution in depth: [CONTRIBUTING.md](CONTRIBUTING.md) says how, [SECURITY.md](SECURITY.md) says how to report a vulnerability privately, and [CODE_OF_CONDUCT.md](CODE_OF_CONDUCT.md) says how we treat each other. Because the hackathon requires that the submission was made during the event by approved participants, **no outside change is merged before the judging ends on 9 November 2026**; issues and pull requests are welcome to open and discuss before then. The open research behind this work, and what is done and not done, is in [docs/research-roadmap.md](docs/research-roadmap.md); the three-part design (open model, open framework, private platform), the loop, the equations and the checks for every piece are in [docs/gegaa.md](docs/gegaa.md).

**Judges:** see the access note in the submission.

## Credits and licence

Built by Hesham Aboul-Fetouh ([@hesham88](https://github.com/hesham88)) with AI coding assistance, including Meta's Muse Code. Licence: the `LICENSE` file here is the engine's OpenRAIL-S licence with its no-war attachment, copied verbatim. Meta, Muse and SAM are Meta's names, used here as plain text; this project is not affiliated with or endorsed by Meta.
