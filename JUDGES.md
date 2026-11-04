# Judges: try it in five ways

Judges: see the access note in the submission.

## No download, no account, no password

1. **The evidence, on this page's site:** every number with its result file is in [docs/metrics.md](docs/metrics.md); the files
   themselves are in [results/](results/), readable in the browser.
2. **The arena in your browser:** [hesham88.github.io/playfellow-coop](https://hesham88.github.io/playfellow-coop/). Play it with
   the arrow keys, press **F9** to hand the controls over and back and **F12** to stop, in English or Arabic (`?lang=ar`). It is the
   controls and the safety rules only: the buddy's brain runs in the Windows app below.
3. **The code, tests and replays in a cloud workspace:** [open this repository in GitHub Codespaces](https://codespaces.new/hesham88/playfellow-coop)
   with your GitHub account. It installs itself (`bootstrap.sh`), then sections 1, 2 and 5 below run there as written, with no key
   (checked on 4 Nov in a clean Linux container: the replay tests 40 passed, the co-op bench printed the same lines as section 2, the
   model-written skill replayed). Playing a real game needs Windows.
4. **Everything else, on your PC,** in one line (sections 0 to 5 below). Nothing asks for a password; a Meta key is needed only for
   the live part (section 3), and the rest runs with no key.

Everything below was run on a development machine on 2026-11-02, and the output is pasted as it came out (paths trimmed). No run below spends money: the live part stops before any paid call unless you put in your own key.

## 0. Set up in one line

Windows, Python 3.11+, Git. In PowerShell:

```powershell
irm https://raw.githubusercontent.com/hesham88/playfellow-coop/main/install.ps1 | iex
cd $env:USERPROFILE\PlayFellow\playfellow-coop
.\playfellow doctor
```

Every `python -m playfellow_coop ...` below can be run as `.\playfellow ...` with no activation step; to use `python` itself, run
`.venv\Scripts\activate` first (if PowerShell refuses scripts, `.\playfellow` needs no policy change).

The bootstrap makes a virtual environment, clones the engine at its pinned tag beside this folder, installs both, and runs the doctor,
which lists anything still missing (`doctor --fix` installs it after showing the plan). On Linux or macOS, `sh bootstrap.sh` sets up
parts 1, 2 and 5 below (they need no game window). If the engine sits elsewhere, set `PLAYFELLOW_ENGINE` to its `software` folder.

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

Store your Meta Model API key once, with hidden input, in the Windows credential manager (or set `MODEL_API_KEY` in your environment; never commit it):

```
python -m playfellow_coop keys set
python -m playfellow_coop keys status     # says where the key comes from; never shows it
```

`BASETEN_API_KEY` is only for the recorded open-weights bench rows; public and judge traffic never goes there. Then:

```
python -m playfellow_coop --brain muse --typed --max-usd 0.20
```

`--max-usd` caps the session spend; the daily cap in `budget.py` applies as well. F9 hands the controls to you, F9 again hands them back, F12 stops everything.

With no key set, the run refuses with a no-key message before any paid call. `python -m playfellow_coop models` lists every brain
with its measured cost per run, read from the committed result files.

## 4. Test it yourself on a game

1. Open your game, then let PlayFellow find it; it prints the start command for each window it may play:

```
python -m playfellow_coop games
```

2. The general card `any_game` works on any game; for a tighter list of keys, make a controls card in the engine's card format.
3. Dry-run first, so it looks and speaks but presses nothing (the widget docks at the top centre of the game window):

```
python -m playfellow_coop --typed --dry-run --overlay --window "<your game window title>" --card any_game
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

## 5. Watch a model-written skill play, no key

One command replays the newest committed live SkillSmith file: it reloads the skill source saved inside that file, checks its fingerprint, puts it through the same static gate and sandbox, and plays it again on the file's held-out seeds. No key and no network are needed; play after writing is local.

```
python -m bench.skillsmith_run --replay latest
```

| Game (brain) | Saved held-out result | File |
|---|---|---|
| maze_chase (muse) | 0 wins, IQM 0.58 | `results/skillsmith/skillsmith-muse-room-20261102.json` |
| key_caves (muse) | 0 wins, IQM 0.3333 | `results/skillsmith/skillsmith-muse-room-20261102.json` |
| action_quest (muse) | not played (nothing promoted) | `results/skillsmith/skillsmith-muse-room-20261102.json` |
| osg_2048 (muse) | 0 wins, IQM 0.6 | `results/skillsmith/skillsmith-muse-2048-20261103.json` |
| maze_chase (open) | 0 wins, IQM 0.58 | `results/skillsmith/skillsmith-open-20261102.json` |
| key_caves (open) | 0 wins, IQM 0.3333 | `results/skillsmith/skillsmith-open-20261102.json` |
| action_quest (open) | not played (nothing promoted) | `results/skillsmith/skillsmith-open-20261102.json` |
| osg_2048 (open) | 0 wins, IQM 0.65 | `results/skillsmith/skillsmith-open-2048-20261103.json` |
