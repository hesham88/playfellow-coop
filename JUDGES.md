# Judges: try it in five ways

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

## 2. Offline play with no key: the assist

You start with the controls. A typed request hands one part to the buddy; the controls come back by themselves.

```
python -m playfellow_coop --assist 6 --typed
```

then type:

```
grab the coins on the left
```

What you will see offline is exactly this: the built-in brain never says a part is done, so the part ends at its turn limit (6 turns here, so it ends quickly) with "I couldn't finish …" and hands the controls back. That is the offline behaviour — do not read it as the buddy detecting a finished part. **F9** takes the controls back at any moment; **F12** stops everything.

Run on the machine that wrote this file (2026-11-02, on the branch where `--assist` lands; its engine input dependency is not installed here, so the live run stops at that step, and the offline bench and tests below are the proof that runs here):

```
ModuleNotFoundError: No module named 'pydirectinput'
```

"Done" hand-backs that are measured, at $0, come from the games themselves:

```
python -m bench.access_bench --seeds 5
```

Result (committed as `results/access/access-20261102.json`, `done_by: game_progress`): **65 of 66 parts done, 0 breaches, 21,066 presses spared**; split controls refused 83,696 presses of kept keys with **0 breaches**; the random control finished 11 of 36 parts. No disabled player was simulated or involved: the player rests between requests. The assist tests agree:

```
python -m pytest tests/test_assist.py tests/test_access_bench.py -q -W error
```

```
37 passed, 2 skipped
```

Live, with your own key (`--brain muse --assist`, part 3): "done" is the model's word (`done_by: model_said`), with the screen-goal check beside it when it fires (`done_by: screen_goal`). The record always says which.

Offline proof of the typed-command path on this branch today:

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

## 5. Watch a model-written skill play, no key

One command replays the newest committed live SkillSmith file: it reloads the skill source saved inside that file, checks its fingerprint, puts it through the same static gate and sandbox, plays it again on the file's held-out seeds, and prints the saved wins and progress beside the replayed ones, plus the sandbox proof table. No key and no network are needed; play after writing is local.

```
python -m bench.skillsmith_run --replay latest
```

Until a live file is committed, the command says so plainly and still succeeds. Run here on 2026-11-02 (no live SkillSmith file is committed yet; only the sandbox proof is):

```
no live file yet: no committed live SkillSmith file under results/skillsmith/ to replay
```

(exit 0). Once the architect's live F1 file lands under `results/skillsmith/`, the same command prints each game's saved and replayed wins and progress (a mismatch exits 1, a changed or gate-failing source is refused with exit 2), followed by the sandbox proof rows naming the layer that stopped each planted hostile skill. The offline rehearsal of exactly this path, with the stand-in model, is covered by `tests/test_skillsmith_run.py` (the judge-replay and replay-latest tests).

Every win in this repo's result files is labelled **assisted** (a local skill helped) or **model alone**; nothing here claims a level above L0 on the Practice Arena.

The ADK evaluator (`playfellow_coop/adk_app/arena_eval/run.py`, run in the pinned ADK environment from `tools/adk_env.py`) also needs the engine installed, exactly as in the README install step: clone the engine at the `pre-hackathon` tag beside this repo and `pip install -e playfellow`, or set `PLAYFELLOW_ENGINE` to its `software` folder. Without an engine it now stops as a setup failure; it never reports a lost game.
