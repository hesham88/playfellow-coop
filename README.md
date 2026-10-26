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
| `meta_playfellow/sam_marks.py`, `sam_eval.py` | SAM 3.1 marks: where things are on screen, drawn as numbered labels on the picture the buddy sees, with the engine's own legend. Asked again only when the picture changes; every request is gated by the daily budget | built and tested against a **fake server** built from the Practice Arena's own truth. **No real SAM call yet**: the response wrapper is unverified. The scores from the fake server check the harness only and say nothing about SAM's accuracy |
| `meta_playfellow/voice.py` | Voice commands ("grab the coins on the left") with Muse Voice Transcribe in file mode (push-to-talk), and **typed commands as the fallback**, so the demo never needs a microphone. The command goes to the planner next to the marks; only keys on the controls card are pressed | written; tests pending (they run before this row says "built"). No real voice call yet |
| Voice, realtime | Live streaming transcription | planned: only the file mode is built, because the realtime message format was not in the docs we read |
| Split controls ("you block, I heal") | Share the keys between you and the buddy | planned, a stretch goal |

Items marked planned are not built: a row changes only when a dated commit shows it.

## Install and run

```
git clone --branch pre-hackathon https://github.com/hesham88/playfellow.git
pip install -e playfellow
pip install -e .
```

The engine's controls cards and settings files sit next to its code, so the engine is installed editable (`-e`), from a clone of the tag.

## How to run the demo (no microphone needed)

1. Install as above, then open the Practice Arena from the engine: `python -m practice_arena.arena` (in the engine's `software` folder).
2. In this repo, start the buddy with the built-in brain, which needs no key and no network, and with typed commands:

   ```
   python -m meta_playfellow --typed
   ```

   With a Muse key in `MODEL_API_KEY`, add `--brain muse`.
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
python -m meta_playfellow --brain muse        # F9 takes the controls, F9 again gives them back, F12 stops
python -m meta_playfellow                     # the same with the engine's built-in brain (no key, no network)
```

Every test runs offline: a fake server on 127.0.0.1 stands in for the Meta API, and nothing presses a key, grabs the screen or spends money.

## What this does and does not do

It plays and talks with you. It does not judge or score the player. The demo uses our own Practice Arena, the arena pack and one open-source game.

## Credits and licence

Built by Hesham Aboul-Fetouh ([@hesham88](https://github.com/hesham88)) with AI coding assistance, including Muse Code. Licence: the `LICENSE` file here is the engine's OpenRAIL-S licence with its no-war attachment, copied verbatim. Meta, Muse and SAM are Meta's names, used here as plain text; this project is not affiliated with or endorsed by Meta.
