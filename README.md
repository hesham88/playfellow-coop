# meta-playfellow

**Built on the PlayFellow engine (hesham88/playfellow, tag `pre-hackathon` = the engine at kickoff plus packaging/test-isolation commits made in the first hour; no new features). Everything in this repo was built during the event.**

PlayFellow is an open-source engine that plays a PC game *with* you: it watches one game window, asks a brain what to do next, and presses only the keys that game's controls card allows. This repo adds the event work as a plugin package. It does not contain the engine; it installs it.

## What is new in this repo

| Piece | What it does | Status and honest limits |
|---|---|---|
| `meta_playfellow/muse_brain.py` | A brain that asks a Muse model on the Meta Model API what to do. Pinned address, no proxy or CA variables, redirects refused, the key never shown | built; tested against a fake server only. **No live call yet**: the endpoint path and usage field names are unverified until the first capped real call |
| `meta_playfellow/budget.py` | A daily spending cap (dollars and calls) kept in a small file; a call over the cap is stopped before it is sent | built; prices are the published Standard prices for muse-spark |
| `meta_playfellow/handover.py`, `session.py` | **You take over, I take over.** F9 takes the controls: every held key is released, the buddy presses nothing and asks no AI. F9 again hands them back with a one-line summary made only of counted facts (seconds, turns skipped, AI calls made). F12 and the mouse corner still stop everything | built; tested with pretend eyes, hands and brain. **Not yet run live on the Practice Arena** |
| `meta_playfellow/stage_timer.py`, `bench.py`, `bench/speed_bench.py` | Times capture, shrink, encode, request, parse-and-check and key-down per turn and writes one `pf-results/1` file (p50, p90, p95) | built; offline-tested. `encode` is measured only for the Muse brain; `first_byte` and `change_test` are not measured, and the file says "not measured" instead of inventing a number. **No live run yet** |
| SAM 3.1 marks | Labels what is on screen so the brain can say "go to R1" instead of guessing pixels | planned (needs API credits) |
| Voice | Talk to the buddy | planned |

Items marked planned are not built: a row changes only when a dated commit shows it.

## Install and run

```
git clone --branch pre-hackathon https://github.com/hesham88/playfellow.git
pip install -e playfellow
pip install -e .
```

The engine's controls cards and settings files sit next to its code, so the engine is installed editable (`-e`), from a clone of the tag.

## Tests

```
python -m pytest -q
```

To use the Muse brain, put your own key in the environment as `MODEL_API_KEY` (Meta's name for it) or in the Windows credential manager. It is never read from a file in this repo, and it is never printed. Then:

```
python -m meta_playfellow --brain muse        # F9 takes the controls, F9 again gives them back, F12 stops
python -m meta_playfellow                     # the same with the engine's built-in brain (no key, no network)
```

Every test runs offline: a fake server on 127.0.0.1 stands in for the Meta API, and nothing presses a key, grabs the screen or spends money.

## What this does and does not do

It plays and talks with you. It does not judge or score the player. The demo uses our own Practice Arena, the arena pack and one open-source game.

## Credits and licence

Built by Hesham Aboul-Fetouh ([@hesham88](https://github.com/hesham88)) with AI coding assistance, including Muse Code. Licence: the `LICENSE` file here is the engine's OpenRAIL-S licence with its no-war attachment, copied verbatim. Meta, Muse and SAM are Meta's names, used here as plain text; this project is not affiliated with or endorsed by Meta.
