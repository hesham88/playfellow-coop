"""Build time only: teach the state classifier what a game's own screens look like, by playing the game and labelling its pictures from the game's state.

Labels (play, lost, won) come from the game while it is BUILT; at play time the classifier sees pixels only. The result is a small JSON file per game and per look, shipped beside the
code (`states/<game>.json` for the classic look, `states/<look>/<game>.json` for a re-skin such as `glass`) and loaded by `load_state_classifier`. Like the skills' looks: learned once,
read forever.
"""
from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from typing import Callable

import numpy as np

from playfellow_coop.universal.frames import normalize
from playfellow_coop.universal.state import StateClassifier
from playfellow_coop.universal.watch import WATCH_SIDE

FOLDER = Path(__file__).with_name("states")
Policy = Callable[[object, np.random.Generator, np.ndarray], str]


def collect(make_game: Callable[[int], object], seeds: range, steps: int, play: Callable | None = None, policy: Callable[[int], Policy] | None = None,
            keep: int | None = None, frozen_ends: int = 0, side: int | None = WATCH_SIDE) -> list[tuple[np.ndarray, str, np.ndarray | None]]:
    """Play `make_game(seed)` and label each picture: "gameplay" while it runs, then "dead" or "victory" for the last picture.

    `play(game, rng)` picks a key (random by default); `policy(seed)` instead gives a per-episode player that is also handed the picture (an oracle that reads pixels, such as a
    skill). `keep` bounds the play pictures kept per episode (an even sample over the whole episode, so a long winning game does not fill the memory), and `frozen_ends` adds the
    end picture that many more times as seen after itself: once a round is over the screen stands still, and that is what the watch sees from then on.
    Pictures are kept as the screen watch reads them, shrunk to `side` (the watch's own size): a classifier must be fitted on what it will be shown."""
    examples: list[tuple[np.ndarray, str, np.ndarray | None]] = []
    for seed in seeds:
        game = make_game(seed)
        rng = np.random.default_rng(seed)
        player = policy(seed) if policy else None
        plays: list[tuple[np.ndarray, str, np.ndarray | None]] = []
        seen = 0
        previous = None
        for _ in range(steps):
            full = np.asarray(game.render().convert("RGB"))
            frame = normalize(full, max_side=side) if side else full
            if game.done:
                examples.extend(_thin(plays, keep))
                examples.append((frame, "victory" if game.is_won() else "dead", previous))
                examples.extend((frame, "victory" if game.is_won() else "dead", frame) for _ in range(frozen_ends))
                break
            seen += 1
            if keep is None or len(plays) < keep:
                plays.append((frame, "gameplay", previous))
            else:  # reservoir sampling: every play picture of the episode had the same chance to be kept
                slot = int(rng.integers(0, seen))
                if slot < keep:
                    plays[slot] = (frame, "gameplay", previous)
            previous = frame
            key = player(game, rng, full) if player else (play(game, rng) if play else rng.choice(list(game.keys)))  # a player reads the full picture
            game.step(key)
        else:
            examples.extend(_thin(plays, keep))
    return examples


def _thin(plays: list, keep: int | None) -> list:
    return plays if keep is None else plays[:keep]


def fit_game(make_game: Callable[[int], object], seeds: range = range(24), steps: int = 300, play: Callable | None = None, max_play: int = 400,
             policy: Callable[[int], Policy] | None = None, keep: int | None = None, frozen_ends: int = 0, regions: int = 0) -> StateClassifier:
    """A classifier fitted to one game. Gameplay pictures are thinned (the end screens are rare, and the many play pictures must not drown them)."""
    examples = collect(make_game, seeds, steps, play, policy=policy, keep=keep, frozen_ends=frozen_ends)
    play_frames = [e for e in examples if e[1] == "gameplay"]
    if len(play_frames) > max_play:
        chosen = np.linspace(0, len(play_frames) - 1, max_play).astype(int)
        play_frames = [play_frames[i] for i in chosen]
    ends = [e for e in examples if e[1] != "gameplay"]
    return StateClassifier().fit(play_frames + ends, regions=regions)


def engine_look() -> str:
    """The look of the arena games on the path: "glass" when the engine draws its games with skins (the revamped look), else "classic"."""
    try:
        return "glass" if importlib.util.find_spec("arena_pack") and importlib.util.find_spec("arena_pack.skins") else "classic"
    except (ImportError, ValueError):
        return "classic"


def folder_for(look: str) -> Path:
    return FOLDER if look == "classic" else FOLDER / look


def save(path: Path, model: StateClassifier) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.to_json(), indent=1), encoding="utf-8", newline="\n")


def load_state_classifier(game_key: str, folder: Path | None = None, look: str | None = None) -> StateClassifier | None:
    """The fitted classifier shipped for this game and look (the running engine's look when none is given), or None (the watch then acts only on its one strict rule)."""
    base = folder if folder is not None else FOLDER
    look = look or engine_look()
    path = (base if look == "classic" else base / look) / f"{game_key}.json"
    if not path.is_file():
        return None
    return StateClassifier.from_json(json.loads(path.read_text(encoding="utf-8")))
