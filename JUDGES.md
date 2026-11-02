# Judges: try it in four ways

Everything below was run once on the K lane machine on 2026-11-02, and the output is pasted as it came out (paths trimmed). No run below spends money: the live part stops before any paid call unless you put in your own key.

Set-up for every part: install as in the README (engine clone beside this repo, one virtual environment, `pip install -e .`), and set `PLAYFELLOW_ENGINE` to the engine clone's `software` folder when it is not beside this repo.

## 1. Replay with no key

A recorded session log becomes the web page's recording, fully offline.

```
python -m pytest tests/test_record_replay.py -q -W error
```

Output:

```
40 passed in 1.18s
```

The same conversion for a real log you recorded yourself (part 3 writes one with `--log`):

```
python demo/record_replay.py session-logs/run1.jsonl
```

It refuses any log that does not prove a real brain with real marks, so a scripted run can never be passed off as a live one.

## 2. Offline play with no key

After the architect's assist change is merged, the offline run is:

```
python -m playfellow_coop --assist --typed
```

then type:

```
grab the coins on the left
```

Run on this branch (the assist flag is not in this branch yet; it lands with the architect's merge):

```
__main__.py: error: unrecognized arguments: --assist
```

The same run without that flag works on this branch today. It needs no key and no network (built-in brain, typed line in, dry run so nothing is pressed):

```
python -m playfellow_coop --typed --dry-run --max-seconds 20
```

Output on this machine (its engine dependencies are not installed here, so it stops at that step; the offline test suite below covers the typed-command path end to end):

```
ModuleNotFoundError: No module named 'pydirectinput'
```

Offline proof that does run here today, typed command included:

```
python -m pytest tests/test_record_replay.py tests/test_arena_run.py -q -W error
```

Output (first run, both files together):

```
54 passed in 6.65s
```

## 3. Live with your own keys

Copy `.env.example` to your own environment (never commit a filled copy): set `MODEL_API_KEY` to your Meta Model API key. `BASETEN_API_KEY` is only for the owner's recorded open-weights bench rows; public and judge traffic never goes there. Then:

```
python -m playfellow_coop --brain muse --typed --max-usd 0.20
```

`--max-usd` caps the session spend; the daily cap in `budget.py` applies as well. F9 hands the controls to you, F9 again hands them back, F12 stops everything.

Run here with no key set (this machine also lacks the engine's input dependency, so it stops one step earlier; with the install done and still no key, the run refuses with a no-key message before any paid call):

```
ModuleNotFoundError: No module named 'pydirectinput'
```

## 4. Test it yourself on a game

1. Open your game and note its window title.
2. Make a controls card for it (the engine's card format lists the only keys the buddy may press).
3. Dry-run first, so it looks and speaks but presses nothing:

```
python -m playfellow_coop --typed --dry-run --window "<your game window title>"
```

4. Type a line such as `grab the coins on the left`, check the spoken plan names only card keys, then run again without `--dry-run` when you are satisfied.

The built-in Practice Arena check that ships with this repo, no key needed:

```
python -m pytest tests/test_arena_run.py -q -W error
```

Output:

```
14 passed in 5.09s
```

Every win in this repo's result files is labelled **assisted** (a local skill helped) or **model alone**; nothing here claims a level above L0 on the Practice Arena.
