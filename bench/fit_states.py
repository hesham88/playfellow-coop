"""Build time: fit the screen-state classifier for each arena game that has a skill and save it beside the code, with a held-out check.

  python bench/fit_states.py                 fit, check on seeds the fit never saw, write playfellow_coop/universal/states/<game>.json
  python bench/fit_states.py --check         only check the files that are there (exit 1 when one is missing or reads too few pictures right)

Labels come from the game's own state while the classifier is being built; the shipped file is only numbers, and at play time the classifier sees pixels.
"""
from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path

os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from bench import arena_run as ar  # noqa: E402
from playfellow_coop.universal.state_fit import FOLDER, collect, fit_game, load_state_classifier, save  # noqa: E402

GAMES = ["snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"]
MIN_PLAY_RECALL = 0.9  # of held-out gameplay pictures, this share must be read as gameplay
MIN_END_RECALL = 0.7  # and this share of held-out end pictures (game over, victory) must be read as an end screen; a game whose end looks like its play cannot be told apart this way, and gets no file


def held_out_score(key: str, model) -> tuple[float, float | None, int, int]:
    examples = collect(lambda seed: ar.load_game(key, seed), range(100, 104), 200)
    play = [e for e in examples if e[1] == "gameplay"]
    ends = [e for e in examples if e[1] != "gameplay"]
    recall = sum(model.classify(f, p)[0] == "gameplay" for f, _, p in play) / max(1, len(play))
    end_recall = sum(model.classify(f, p)[0] == label for f, label, p in ends) / len(ends) if ends else None
    return recall, end_recall, len(play), len(ends)


def good(recall: float, end_recall: float | None) -> bool:
    return recall >= MIN_PLAY_RECALL and end_recall is not None and end_recall >= MIN_END_RECALL


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    args = parser.parse_args(argv)
    bad = []
    for key in GAMES:
        if not args.check:
            fitted = fit_game(lambda seed, key=key: ar.load_game(key, seed), seeds=range(12), steps=200)
            recall, end_recall, plays, ends = held_out_score(key, fitted)
            keep = good(recall, end_recall)
            verdict = "saved" if keep else "NOT saved (the end of this game looks too much like its play)"
            print(f"{key:14} held-out: gameplay {recall:.2f} of {plays}, end screens {end_recall if end_recall is None else round(end_recall, 2)} of {ends} -> {verdict}")
            if keep:
                save(FOLDER / f"{key}.json", fitted)
            continue
        model = load_state_classifier(key)
        if model is None:
            print(f"{key:14} no file (the watch uses only its strict loading rule)")
            continue
        recall, end_recall, plays, ends = held_out_score(key, model)
        print(f"{key:14} held-out: gameplay {recall:.2f} of {plays}, end screens {end_recall} of {ends}")
        if not good(recall, end_recall):
            bad.append(key)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
