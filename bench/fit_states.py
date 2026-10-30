"""Build time: fit the screen-state classifier for each arena game that has a skill and save it beside the code, with a held-out check.

  python bench/fit_states.py                 fit for the look of the engine on the path, check on seeds the fit never saw, write playfellow_coop/universal/states/[<look>/]<game>.json
  python bench/fit_states.py --check         only check the files that are there (exit 1 when one is missing or reads too few pictures right)
  python bench/fit_states.py --games snake   only these games

Labels come from the game's own state while the classifier is being built; the shipped file is only numbers, and at play time the classifier sees pixels.
Even seeds are played by the game's skill (the oracle, which reads pixels: the fit sees real victory screens), odd seeds by random keys (real defeats). A re-skinned look needs
its colours for the skill: `--looks DIR`, by default the engine's own `playfellow_looks` folder when it has one. brick_breaker is the one exception: its oracle wins from pixels
but needs about twelve minutes a game, so after 300 oracle steps the fit clears the last level's bricks through the game's state and lets the game's own code declare and draw the
win (build time only; the picture is the game's own victory screen).
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
from playfellow_coop.skills.base import Done  # noqa: E402
from playfellow_coop.skills.looks import load_looks  # noqa: E402
from playfellow_coop.skills.registry import SKILLS  # noqa: E402
from playfellow_coop.universal.state import StateClassifier  # noqa: E402
from playfellow_coop.universal.state_fit import collect, engine_look, folder_for, load_state_classifier, save  # noqa: E402

GAMES = ["snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"]
FIT_SEEDS, HELD_OUT_SEEDS = range(12), range(100, 106)
KEEP = 25  # play pictures kept per episode (an even sample of the whole episode)
FROZEN_ENDS = 2  # the end picture also counted as the watch sees it once the round is over: standing still
REGIONS = 2
RANDOM_STEPS = 1200  # a random episode that has not ended by then (box_push cannot be lost) stops there
FINISH_AFTER = 300  # brick_breaker only, see the module note
MIN_PLAY_RECALL = 0.9  # of held-out gameplay pictures, this share must be read as gameplay
MIN_END_RECALL = 0.7  # and this share of held-out end pictures (game over, victory) must be read as the right end screen; a game whose end looks like its play gets no file


def finish_bricks(game) -> None:
    game.level_no = int(game.progress()["levels"]) - 1  # the last level, with no bricks left: the game's own next tick declares the win
    game.bricks = {}


FINISH = {"brick_breaker": finish_bricks}


def oracle_policy(key: str, looks_dir: Path | None):
    path = looks_dir / f"{key}.json" if looks_dir else None
    looks = load_looks(path) if path and path.is_file() else []

    def per_seed(seed: int):
        if seed % 2:
            return None  # odd seeds: random keys
        skill = SKILLS[key](looks[0]) if looks else SKILLS[key]()
        skill.reset()
        steps = [0]

        def play(game, rng, frame):
            steps[0] += 1
            if key in FINISH and steps[0] == FINISH_AFTER:
                FINISH[key](game)
            try:
                return skill.next_key(frame)
            except Done:
                return rng.choice(list(game.keys))
        return play
    return per_seed


def examples(key: str, seeds: range, looks_dir: Path | None) -> list:
    def make(seed):
        return ar.load_game(key, seed)
    oracle_seeds = [s for s in seeds if s % 2 == 0]
    random_seeds = [s for s in seeds if s % 2]
    longest = int(make(0).max_ticks) + 1
    rows = collect(make, oracle_seeds, longest, policy=oracle_policy(key, looks_dir), keep=KEEP, frozen_ends=FROZEN_ENDS)
    rows += collect(make, random_seeds, RANDOM_STEPS, keep=KEEP, frozen_ends=FROZEN_ENDS)
    return rows


def score(model: StateClassifier, rows: list) -> tuple[float, float | None, int, int]:
    play = [r for r in rows if r[1] == "gameplay"]
    ends = [r for r in rows if r[1] != "gameplay"]
    recall = sum(model.classify(f, p)[0] == "gameplay" for f, _, p in play) / max(1, len(play))
    end_recall = sum(model.classify(f, p)[0] == label for f, label, p in ends) / len(ends) if ends else None
    return recall, end_recall, len(play), len(ends)


def good(recall: float, end_recall: float | None) -> bool:
    return recall >= MIN_PLAY_RECALL and end_recall is not None and end_recall >= MIN_END_RECALL


def default_looks() -> Path | None:
    engine = os.environ.get("PLAYFELLOW_ENGINE")
    folder = Path(engine) / "playfellow_looks" if engine else None
    return folder if folder and folder.is_dir() else None


def main(argv: list[str]) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--games", default=",".join(GAMES))
    parser.add_argument("--looks", type=Path, default=None, help="the skills' looks for this engine's look (default: the engine's playfellow_looks folder, if any)")
    args = parser.parse_args(argv)
    look = engine_look()
    looks_dir = args.looks or (default_looks() if look != "classic" else None)
    games = [g for g in args.games.split(",") if g]
    print(f"look: {look}; files: {folder_for(look)}; skill looks: {looks_dir or 'built in'}")
    bad = []
    for key in games:
        if args.check:
            model = load_state_classifier(key, look=look)
            if model is None:
                print(f"{key:14} no file (the watch uses only its strict loading rule)")
                bad.append(key)
                continue
        else:
            rows = examples(key, FIT_SEEDS, looks_dir)
            model = StateClassifier().fit(rows, regions=REGIONS)
            del rows
        recall, end_recall, plays, ends = score(model, examples(key, HELD_OUT_SEEDS, looks_dir))
        keep = good(recall, end_recall)
        shown = "none" if end_recall is None else f"{end_recall:.2f}"
        verdict = ("ok" if keep else "TOO FEW RIGHT") if args.check else ("saved" if keep else "NOT saved (its end screens cannot be told from its play)")
        print(f"{key:14} held-out: gameplay {recall:.2f} of {plays}, end screens {shown} of {ends}, regions {model.regions} -> {verdict}")
        if not keep:
            bad.append(key)
        elif not args.check:
            save(folder_for(look) / f"{key}.json", model)
    return 1 if bad else 0


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))
