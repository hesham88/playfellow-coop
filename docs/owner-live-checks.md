# Owner live checks (one sitting, about 15 minutes)

Two checks need a person at the keyboard because they press real keys or look at a real screen. Nothing in this repository counts as
"working" for these two things until you have done them and the files they write say so.

## Before you start

- Close other heavy programs. This PC has little free memory.
- Start the Practice Arena from the engine folder: `python -m practice_arena.arena`. If it can be set to borderless or windowed, use that.
- Do not use a game that is online or has anti-cheat. Use the Practice Arena first; SuperTux (borderless) second.

## Check 1: you take over, I take over (about 5 minutes)

1. In this repository's folder run: `python -m playfellow_coop --typed`
2. Click the arena window so it is in front. The buddy starts playing.
3. Press **F9**. The buddy must stop at once and say "It's yours." Play a few moves yourself.
4. Press **F9** again. The buddy must say how long you played and how many turns it waited, then play again.
5. Type `stop` in the terminal and press Enter, or press **F12**. Everything must stop and no key may stay held down.
6. Write down: did it feel instant? did any key stay stuck? did the numbers in the sentence look right?

## Check 2: the floating panel does not disturb the game (about 5 minutes)

0. You are asked to do this only after the builder has rehearsed it: `python demo/overlay_live_check.py --dry-run` runs the same steps over a plain window of its own, with no game. If you were not told that rehearsal passed, wait.
1. With the arena open and in front, run in another terminal: `python demo/overlay_live_check.py`
2. When it asks, click the arena window, then do **not** touch the keyboard or mouse for about 20 seconds.
3. It opens and closes the panel 50 times, looks at only the panel's own rectangle in two screenshots (kept in memory, never saved), and prints two numbers and a saved file name.
4. Send those two numbers back. The file also says what it could not measure.

What good looks like: **focus losses 0** and **panel pixels 0 or very small** (the game itself moves, so a small count can be the game).

## Check 3 (only if checks 1 and 2 went well): a calm open-source game

Repeat check 2 over SuperTux in borderless mode, and watch that not one key is dropped.

## Credit day: the first real recording (after the builder says the log and recorder are ready)

1. Play one real session with the Muse brain and SAM marks, writing a log: `python -m playfellow_coop --brain muse --log run1.jsonl --log-level garden` (a bare name goes under `session-logs/`, which git ignores; the file is never overwritten).
2. Turn the log into the page's recording: `python demo/record_replay.py session-logs/run1.jsonl`. It refuses unless the log proves a real brain and real SAM marks.
3. A REAL recording goes into `demo/web/replay.mjs` and the public repo ONLY after the architect has looked at the file. Do not commit it, and do not push it, before that.
4. `--log-level` says which web level the run matches; the log cannot prove it, so check that the arena level you played is that level.
