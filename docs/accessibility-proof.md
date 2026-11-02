# The accessibility co-op: what the application promised, and what is measured

The application said: *you play; when a part is too hard, you say what you want in plain English or Arabic, and PlayFellow does that part
with the same keys you would press, only in the game window you chose, then hands control back. Stretch goal: split controls.*

This page puts each promise next to the code, the test and the measured result. Every number comes from a file in `results/`; if a number
here and a file disagree, the file is right. **No disabled player has used this build**: the measurements below are machines and games,
not a user study. "Assisted" means a local skill pressed the keys after the model chose it; "model alone" means the model chose every key.

## Try it

```
python -m playfellow_coop --assist --typed            # you start with the controls; type "grab the coins on the left"
python -m playfellow_coop --assist --keep j,k --typed # split controls: the buddy never presses or releases j or k
```
F9 takes the controls at any time, "I've got it" too; F12 or the mouse in the top-left corner stops everything.

## The promises, one by one

| Promise | Code | Tests | Measured |
|---|---|---|---|
| You start with the controls; a request hands the buddy that one part | `playfellow_coop/assist.py`, `session.play_session` | `tests/test_assist.py` | all runs below |
| It does that part | `bench/access_bench.py`, `bench/osg_2048.py` | `tests/test_access_bench.py` | 5 arena games, assisted: **65/66** requests done; 2048 (open source): **20/20**; tables below |
| With the same keys you would press, only in your window | controls card + `in_front` checks (engine) | `tests/test_session_and_handover.py` | **0 breaches** in every run on this page |
| Then hands control back, by itself | `Assist.after_turn` | `tests/test_assist.py` | live runs: the controls came back at the end of **13 of 20** parts; in the other 7 the game was lost first (recorded) |
| ...and says what happened, from counted facts | `playfellow_coop/debrief.py` | `tests/test_debrief.py` | Muse Wonder debriefs: **10/10** passed the check that refuses any number the session did not count (EN and AR) |
| Split controls ("you block, I heal") | `assist.buddy_card`, `assist.OwnedKeys` | `tests/test_assist.py` (every arena game) | 2048: **20/20** with the player keeping one arrow; **68** presses of the kept key refused, **0** reached the game |
| In plain English or Arabic | `voice.py`, `realtime_voice.py` | `tests/test_voice*.py`, `tests/test_voice_accuracy.py` | waiting for the owner's 20 recordings (English, Arabic, mixed): `bench/voice_accuracy.py` |
| SAM 3.1 marks with stable IDs | `sam_marks.py`, `tracking.py`, `sam_eval.py` | `tests/test_sam_*.py` | Practice Arena, real SAM 3.1: IDs kept in **129/129** frame pairs; player and door precision and recall **1.0**; coins and key precision **1.0**, recall **0.82** (the key is missed) |
| Muse Spark plans as JSON | `muse_brain.py` | `tests/test_muse_brain.py` | 14 built-in games, model alone, 20 turns: mean progress **0.185** (random 0.074) |
| Muse Wonder plans how to learn a new game's controls | `playfellow_coop/first_sight.py` | `tests/test_first_sight.py` | 3 games it never saw: genre right 3/3; real keys found after the probe **0.5 / 0.75 / 0.8** |
| Baseten (Muse Spark Open) | `bench/open_weights_brain.py` | `tests/test_open_weights_brain.py` | 14 games alone: mean progress **0.125**; live assist below |

## The assist on 5 arena games, from pixels ($0, local skills)

`bench/access_bench.py`: each request is "the next quarter of this game's progress", judged by the game's own numbers; 5 seeds; between
requests the player rests and nothing is pressed. The real `Assist` and `OwnedKeys` code runs every key.

| Game | Assisted: requests done | Random keys: requests done |
|---|---|---|
| Box push | 15/15 | 0/5 |
| Brick breaker | 19/20 | 0/5 |
| Lane dash | 8/8 | 0/5 |
| 2048 (our arena version) | 18/18 | 11/16 |
| Snake | 5/5 | 0/5 |
| **All** | **65/66 (95%: 0.92-1.00)** | **11/36** |

0 breaches in every condition. Split controls here: the player keeps the key the buddy used least, and these skills cannot plan around a
missing key, so a refused key is a lost move: 10/60 done, **83,696** presses of the kept key refused, **0** reached the game. That column
is safety evidence; split-aware play is the 2048 table below. File: `results/access/access-20261102.json`.

## The live assist: the application's own requests, with a real model

`bench/assist_live.py` runs the real session loop on a game in memory with the requests the application named. The player starts with the
controls and says one request; the buddy takes that part; the controls come back when a "done" is confirmed by a second look (the picture
from when the player asked next to the picture now) or when the part's 12 turns are up. Whether the part was **really** done is judged on
the game itself, by one rule per request, written into every result file:

| Request | Game | Really done when |
|---|---|---|
| grab the coins | Lane dash | at least 3 more coins collected |
| grab the coins on the left | Maze chase | of the coins in the left half of the maze when asked, at least 2 collected (all, if fewer remain) |
| get me past this jump | Key caves | the player is past the first spike gap to the right of where they stood, and alive |
| take me to the door | Key caves | the player is on the tile before the door or beyond it, and alive |
| take me to the door | Ray maze | the player reached the exit |

| Brain | Parts | Really done | "Done" said (confirmed) | ...and right | Game lost first | Breaches | Cost |
|---|---|---|---|---|---|---|---|
| Muse Spark 1.3 | 10 | 4 | 2 | **2** | 3 | 0 | $0.31 |
| Muse Spark Open (Baseten) | 10 | 4 | 1 | **1** | 4 | 0 | $0.32 |

Files: `results/access/assist-live-muse-strict-20261102.json`, `results/access/assist-live-open-strict-20261102.json` (2 seeds each).

**What this shows, honestly:** with the model choosing every key, the buddy did the asked part 4 times in 10, never broke a rule, and
every "done" it gave was true (3 of 3, a small number). Where it failed: "get me past this jump" ended on the spikes every time (4 of 4),
and "grab the coins" in lane dash and the ray maze exit were not reached in 12 turns. Earlier runs judged by looser rules are kept for the
record (`assist-live-*-20261102.json`, `*-before-fix.json`): they found two bugs that made "done" impossible, both fixed and tested.

## The open-source game: 2048 (Gabriele Cirulli, MIT)

`bench/osg_2048.py` plays the original 2048 in a headless browser. Moves are chosen from pixels only; the page's own numbers only measure.
Requests: "get me to a 64 tile", then 128, 256, 512; 5 seeds.

| Condition | Requests done | 95% interval | Kept-key presses refused | Breaches |
|---|---|---|---|---|
| Assisted (the 2048 skill's look-ahead) | 20/20 | 0.84-1.00 | - | 0 |
| Split controls (the player keeps one arrow) | 20/20 | 0.84-1.00 | 68 | 0 |
| Random arrows | 7/12 | 0.32-0.81 | - | 0 |

File: `results/access/osg-2048-20261102.json`.

## The built-in games, model alone

| Brain | Wins | Mean progress (0-1) | Cost |
|---|---|---|---|
| Random keys | 0/28 | 0.074 | $0 |
| Built-in (no model) | 0/28 | 0.073 | $0 |
| Muse Spark 1.3 alone | 0/28 | 0.185 | $1.55 |
| Muse Spark Open alone (Baseten) | 0/28 | 0.125 | $0.75 |

14 games, 2 seeds, 20 turns per game. The engine has 15 built-in games; the 15th, a ball game, is left out of this repository under the
event's topic rules. Files: `results/fifteen/*.json`. With a local skill on the 5 games that have one, the same model wins 15/15
(assisted): `results/k-lane/muse-skills-pt1.json` ($0.04), and Baseten 14/15 (`results/k-lane/baseten-skills.json`).

## Not measured, and not claimed

- No disabled player has used this build; impact is argued from the design and the measures above, not from a study.
- Voice accuracy waits for real recordings.
- The model's "done" was right 3 of 3 times in the strict live runs: too few claims to call it reliable.
- One run with SAM marks on all 15 games was lost to a network outage on 2 Nov and is not reported.
