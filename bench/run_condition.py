"""Run one benchmark condition over several games and seeds and write one results file.

  python -m bench.run_condition --brain random --games snake,box_push --seeds 5 --turns 30 --out results/unseen/random.json
  MODEL_API_KEY=... python -m bench.run_condition --brain muse --games snake --seeds 3 --turns 20 --marks none --out results/unseen/muse-raw.json
  BASETEN_API_KEY=... python -m bench.run_condition --brain open --games snake --seeds 3 --turns 20 --out results/unseen/open-raw.json

Keys come from the environment only. A spend cap (--max-usd, default 1.00) stops the run before the next episode when the brain's own reported cost reaches it.
Marks: none, or sam (the real SAM marker with the phrases in --phrases, asked of the Meta API; costs are added to the cap)."""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import arena_run as ar  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description=__doc__)
    p.add_argument("--brain", choices=["random", "muse", "open"], required=True)
    p.add_argument("--model", default=None)
    p.add_argument("--games", default="snake")
    p.add_argument("--seeds", type=int, default=3)
    p.add_argument("--first-seed", type=int, default=0)
    p.add_argument("--turns", type=int, default=20)
    p.add_argument("--effort", default="minimal")
    p.add_argument("--marks", choices=["none", "sam"], default="none")
    p.add_argument("--phrases", default="", help='for --marks sam: kind=phrase pairs, e.g. "me=blue circle,reward=pink circle"')
    p.add_argument("--max-usd", type=float, default=1.0)
    p.add_argument("--note", default="")
    p.add_argument("--out", type=Path, required=True)
    p.add_argument("--engine", type=Path, default=ROOT.parent / "playfellow" / "software")
    args = p.parse_args(argv)
    if str(args.engine) not in sys.path:  # the engine is normally pip-installed; otherwise use the clone beside this repo
        sys.path.insert(0, str(args.engine))
    games = [g.strip() for g in args.games.split(",") if g.strip()]
    for g in games:
        if g not in ar.GAMES:
            raise SystemExit(f"unknown game {g!r}; choose from {sorted(ar.GAMES)}")

    import controls
    if args.brain == "random":
        make_brain = lambda g: ar.RandomBrain(list(controls.load_card(args.engine / "controls" / f"arena_{g}.yaml").actions), 0)  # noqa: E731
        model = "none"
    elif args.brain == "muse":
        from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain
        key = os.environ.get("MODEL_API_KEY")
        if not key:
            raise SystemExit("MODEL_API_KEY is not set")
        model = args.model or DEFAULT_MODEL

        def make_brain(g):
            brain = MuseBrain(model, key, effort=args.effort)
            brain.set_actions(controls.load_card(args.engine / "controls" / f"arena_{g}.yaml").actions)
            return brain
    else:
        from bench.open_weights_brain import OPEN_MODEL, OpenWeightsBrain
        key = os.environ.get("BASETEN_API_KEY")
        if not key:
            raise SystemExit("BASETEN_API_KEY is not set")
        model = args.model or OPEN_MODEL

        def make_brain(g):
            brain = OpenWeightsBrain(key, model, effort=args.effort)
            brain.set_actions(controls.load_card(args.engine / "controls" / f"arena_{g}.yaml").actions)
            return brain

    marker = None
    if args.marks == "sam":
        from playfellow_coop.sam_marks import SamMarker
        key = os.environ.get("MODEL_API_KEY")
        if not key:
            raise SystemExit("--marks sam needs MODEL_API_KEY")
        prompts = dict(pair.split("=", 1) for pair in args.phrases.split(",") if "=" in pair) or None
        marker = SamMarker(key, prompts=prompts)

    episodes, spent = [], 0.0
    for game in games:
        for seed in range(args.first_seed, args.first_seed + args.seeds):
            if spent >= args.max_usd:
                print(f"spend cap reached at ${spent:.4f}; stopping before {game} seed {seed}")
                break
            brain = make_brain(game)
            episode = ar.run_episode(game, seed, brain, max_turns=args.turns, max_calls=args.turns, marker=marker, engine_dir=args.engine)
            spent += episode.cost_usd
            episodes.append(episode)
            print(f"{game:12} seed {seed}: {episode.ended:8} progress={episode.progress} turns={episode.turns} tokens={episode.tokens_in}/{episode.tokens_out} ${episode.cost_usd:.4f}")
    note = (args.note + " " if args.note else "") + f"marks={args.marks}; effort={args.effort}; turns<= {args.turns}; the engine's public arena pack (unskinned)."
    args.out.parent.mkdir(parents=True, exist_ok=True)
    ar.write_results(args.out, f"{args.brain}-{args.marks}", args.brain, model, games, episodes, note)
    summary = ar.summarise(episodes)
    print(f"wrote {args.out}: {summary['wins']}/{summary['episodes']} wins {summary['wilson95']}, cost ${summary['cost_usd']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
