# Live checks on a real desktop (one sitting, about 15 minutes)

Two checks need a person at the keyboard because they press real keys or look at a real screen. Nothing in this repository counts as
"working" for these two things until you have done them and the files they write say so.

## Before you start (every command below assumes exactly this)

1. Do the README's **Install and run** steps once. They make one folder that holds the engine (`playfellow`) and this repository side by side, with one virtual environment (`.venv`).
2. Open **two** PowerShell windows in that folder and, in each one, turn the environment on: `.venv\Scripts\activate`. The prompt then starts with `(.venv)`. A plain `python` without it gives "No module named playfellow_coop" or "No module named practice_arena".
3. In each window, `cd` into this repository's folder. `python -m playfellow_coop --help` must print the options; if it does not, step 1 or 2 is missing.
4. For the Muse brain, put the key in the second window only, typed masked as in "Credit day: the first real calls" below (PowerShell 7). The key is never shown, never written to a file, and cleared when you close the window.
- Close other heavy programs. This PC has little free memory.
- Start the Practice Arena in the first window: `python -m practice_arena.arena`. If it can be set to borderless or windowed, use that.
- Do not use a game that is online or has anti-cheat. Use the Practice Arena first; SuperTux (borderless) second.

## Check 1: you take over, I take over (about 5 minutes)

1. In the second window (environment on, in this repository's folder) run: `python -m playfellow_coop --typed`
2. Click the arena window so it is in front. The buddy starts playing.
3. Press **F9**. The buddy must stop at once and say "It's yours." Play a few moves yourself.
4. Press **F9** again. The buddy must say how long you played and how many turns it waited, then play again.
5. Type `stop` in the terminal and press Enter, or press **F12**. Everything must stop and no key may stay held down.
6. Write down: did it feel instant? did any key stay stuck? did the numbers in the sentence look right?

## Check 2: the floating panel does not disturb the game (about 5 minutes)

0. You are asked to do this only after the builder has rehearsed it: `python demo/overlay_live_check.py --dry-run` (second window, this repository's folder) runs the same steps over a plain window of its own, with no game. If you were not told that rehearsal passed, wait.
1. With the arena open and in front, run in another terminal: `python demo/overlay_live_check.py`
2. When it asks, click the arena window, then do **not** touch the keyboard or mouse for about 20 seconds.
3. It opens and closes the panel 50 times, looks at only the panel's own rectangle in two screenshots (kept in memory, never saved), and prints two numbers and a saved file name.
4. Send those two numbers back. The file also says what it could not measure.

What good looks like: **focus losses 0** and **panel pixels 0 or very small** (the game itself moves, so a small count can be the game).

Check 2 drives the older Tk panel. The widget that `--overlay` now opens is the Qt one (check 2b).

## Check 2b: the in-game widget over a full-screen game (about 5 minutes)

1. Start the game full screen. Then, in the second window (environment on, in this repository's folder, key set as in step 4 above), run:
   `python -m playfellow_coop --window "<its window title>" --card any_game --brain muse --overlay --talk-key f8 --assist 4 --brief --input scancode`
   Use the game's own card instead of `any_game` when there is one (`--card rayman_legends`). The title is the one shown in the taskbar.
   With `any_game`, the widget keys are not checked against the game (that card lists every key): press Ctrl+Alt+P and Ctrl+Alt+O once each and watch whether the game itself reacts. If it does, start again with `--summon-key` or `--see-through-key` set to another combination.
2. A slim bar must appear at the top centre, over the game, and see-through. The game must keep the focus, so its keys still work.
3. Press **Ctrl+Alt+P** (or click the arrow if the game shows a mouse). The panel must slide down smoothly; the same key slides it back up. The bar writes every key on itself.
4. Press **Ctrl+Alt+O** a few times (or drag the slider). The widget steps through four levels of see-through and is still visible at the lowest.
5. Hold **F8** (or the mic on the bar), say a short request, and release after the last word. A tap too short to carry words says "I didn't hear anything". The request must show in the panel, and the buddy must act on it.
6. Write down: did it ever disappear behind the game? did the game lose a key or the focus?

Results so far, 2 November 2026, over a full-screen commercial game:
- Step 2 passed: the bar showed at the top centre, see-through, and the game kept the focus and its keys.
- F8 and F9 worked.
- The widget's mouse buttons did nothing, because the game had taken the mouse. That is why every control now has a key written on the bar.
- The panel grew past its height. Fixed: the chat now shows its last 4 lines in a fixed window.
- Steps 3 to 6 are to repeat with the keys above.

## Check 3 (only if checks 1 and 2 went well): a calm open-source game

Repeat check 2 over SuperTux in borderless mode, and watch that not one key is dropped.

## Credit day: the first real recording (after the builder says the log and recorder are ready)

1. Play one real session with the Muse brain and SAM marks, writing a log: `python -m playfellow_coop --brain muse --log run1.jsonl --log-level garden` (a bare name goes under `session-logs/`, which git ignores; the file is never overwritten).
2. Turn the log into the page's recording: `python demo/record_replay.py session-logs/run1.jsonl`. It refuses unless the log proves a real brain and real SAM marks.
3. A REAL recording goes into `demo/web/replay.mjs` and the public repo ONLY after the maintainer has looked at the file. Do not commit it, and do not push it, before that.
4. `--log-level` says which web level the run matches; the log cannot prove it, so check that the arena level you played is that level.

## Credit day: the first real calls (about 5 minutes, under one cent in practice, never more than 10 dollars)

1. In a terminal, open PowerShell 7 ("pwsh"), not "Windows PowerShell" (the Start menu usually opens the old one, where the next line gives an error). Put the key in the environment for this window only (it is never read from a file): `$env:MODEL_API_KEY = Read-Host -MaskInput "Meta key"`. You paste the key at the prompt and it is not shown on screen; do not paste the key into any chat, file or message.
   If you can only use Windows PowerShell 5.1, use this instead (it asks the same way):

   `$s = Read-Host -AsSecureString "Meta key"; $env:MODEL_API_KEY = [Net.NetworkCredential]::new('', $s).Password; Remove-Variable s`

   The key is never typed on the command line itself: PSReadLine saves command lines to disk, while text typed at a `Read-Host` prompt is not saved.
2. Run `python demo/first_real_calls.py`. It prints its plan (five calls: one chat, SAM twice, one voice file, one short realtime voice stream of at most 5 seconds) and waits. It sends nothing until you type `YES`; it refuses to run without the key, and it stops at the 10 dollar cap.
3. It prints one line per call, `OK` or `DIFFERS`, and where it saved the raw answers (the key is replaced by `***`). Keep those lines exactly as they are for the maintainer.
4. Run `python demo/scrub_fixtures.py`. It replaces ids, e-mail addresses, key shapes and paths in the saved files with fixed placeholders of the same kind (it prints how many, never a value) and changes nothing else.
5. The files are in `tests/fixtures/real/`: `muse_chat.json`, `sam_responses.json`, `sam_no_match.json`, `voice_transcribe.json`, `realtime_voice.json`. Do not commit the fixture files; the maintainer reads all of them before anything is committed.
6. Clear the key: `Remove-Item Env:MODEL_API_KEY`, then close the window.
