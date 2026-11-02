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

## 2. The accessibility co-op with no key ($0, no network)

The application's promise: you ask for one part, the buddy does it with the keys the game's card allows, and the controls come back to
you by themselves. This runs the real assist and split-controls code on two built-in games from pixels, with the local skills (no model):

```
python -m bench.access_bench --seeds 1 --games snake,box_push --out my-access.json
```

Output on this machine (2 Nov):

```
assist/ALL   done 4/4 (100%, 95% (0.5101, 1.0)) spared 72 refused 0 breaches 0
random/ALL   done 0/2 (0%, 95% (0.0, 0.6576)) spared 611 refused 0 breaches 0
split/ALL    done 1/3 (33%, 95% (0.0615, 0.7923)) spared 526 refused 69 breaches 0
```

"done" counts requests ("make the next quarter of progress") judged by the game's own numbers; "spared" is key presses the player did not
have to make; "refused" is presses of the key the player kept (split controls) that never reached the game; "breaches" must be 0.
The full run (`python -m bench.access_bench --seeds 5`, committed as `results/access/access-20261102.json`): **65 of 66 parts done,
0 breaches, 21,066 presses spared**; split controls refused 83,696 presses of kept keys with **0 breaches**; random keys finished 11 of 36.
No disabled player was simulated or involved.

The tests of the assist itself (hand-back by itself, a crashing check never counts as done, F12 stays a stop, kept keys never pressed or
released on any route, new words replace the running part, the second look before "done" counts):

```
python -m pytest tests/test_assist.py tests/test_access_bench.py -q -W error
```

To play it yourself with the built-in brain (no key): start the engine's Practice Arena, then

```
python -m playfellow_coop --assist 6 --typed
```

and type `grab the coins on the left`. Offline, the built-in brain never says a part is done, so the part ends at its turn limit (6 here)
with "I couldn't finish ..." and the controls come back with a line of counted facts; do not read that as the buddy detecting a finished
part. Add `--keep j,k` to keep keys for yourself. **F9** takes the controls back at any moment; **F12** stops everything.

With your own key (`--brain muse --assist`, part 3), a part ends when the model says it is done **and a second look** at the picture from
when you asked and the picture now agrees (`done_by: model_verified`); the record always says which.

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

The ADK evaluator (`playfellow_coop/adk_app/arena_eval/run.py`, run in the pinned ADK environment from `tools/adk_env.py`) also needs the engine installed, exactly as in the README install step: clone the engine at the `pre-hackathon` tag beside this repo and `pip install -e playfellow`, or set `PLAYFELLOW_ENGINE` to its `software` folder. Without an engine it now stops as a setup failure; it never reports a lost game.
