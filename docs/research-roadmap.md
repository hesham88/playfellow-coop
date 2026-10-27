# Research roadmap

This project started as an accessibility co-op: you say what you want, the buddy does that part with the same keys, and hands control back. Underneath is an open research question: **can a small open model learn to turn a spoken request plus a marked picture into safe game keys?** This page says plainly what exists, what is being tried, and how to join.

## What exists today (checked in this repository)

| Piece | State |
|---|---|
| A training-data generator for "words plus marked picture to keys" | Built (`train/`). Every row records where it came from. Labels come from our own game's exact state and hand-written phrases, in English and Arabic, with a held-out test split whose phrases never appear in training. The Arabic phrases are marked as not yet reviewed by a native speaker |
| A rule that no row may come from an AI model's output | Built and tested: a row without a recorded origin, or with a model-output origin, is refused |
| A baseline: how well an open model does with no training | In progress. Until a results file written by the code exists, no number is claimed |
| A training run | **Off.** It happens only if partner credits arrive and the earlier work is done. If it does not happen, the generator, the dataset layout and the baseline are published and training continues after the event |

## What we will not do

- Use the output of any AI model as training data.
- Claim a result that no results file backs. Numbers in this repository come from files the code wrote.
- Present anything that was not measured as measured. Arabic accuracy, in particular, is reported separately from English, and only when it has been measured.

## How to join

- **Open an issue** with an idea, a game that would make a good test, or an Arabic phrase that sounds natural (a native speaker's review is the most useful thing anyone can give us).
- **Pull requests are welcome to open and discuss.** Until the hackathon judging ends on 9 November 2026 nothing from outside is merged, because the event requires that the submission was made by approved participants during the event. After that, every pull request is reviewed in depth by the maintainer (see [CONTRIBUTING.md](../CONTRIBUTING.md)).
- Everything is open source under the licence in [LICENSE](../LICENSE), including its non-violence terms.

## What you will and will not find in the open repositories (an honest map)

The PlayFellow project has a larger private desktop prototype than the two open repositories. So that nobody searches in vain:

- **Open engine** (`hesham88/playfellow`, tags `before-kickoff` and `pre-hackathon`): the see-think-act loop, the controls-card allow-list, the F12 stop, the Practice Arena and the built-in test games, the brain interface, the safety layer. It runs a single-rate loop. Its test suite is the one in that repository.
- **This repository** (`playfellow-coop`): everything built during the event: the Muse brain, SAM marks, voice commands and push-to-talk, the one-key hand-over, the stage timer and benchmarks, the training-data pipeline, the web arena, the overlay, and an optional Rust fast path (`rust/fastpath`, written during the event).
- **Not in either open repository, and not claimed as event work:** the private prototype's multi-rate loop with Kalman-filter reflexes, its learned navigation, its inverse-dynamics model, its earlier compiled Rust core, and its larger test suite. They are research we may open later; nothing in the demo depends on them.
- **Early prototype ideas versus event work:** the take-over key and voice commands were explored in the private prototype. The implementations in this repository were written from scratch during the event.
