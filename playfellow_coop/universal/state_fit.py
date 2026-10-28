"""Build time only: teach the state classifier what a game's own screens look like, by playing the game and labelling its pictures from the game's state.

Labels (play, lost, won) come from the game while it is BUILT; at play time the classifier sees pixels only. The result is a small JSON file per game, shipped beside the code
(`states/<game>.json`) and loaded by `load_state_classifier`. Like the skills' looks: learned once, read forever.
"""
from __future__ import annotations

import json
from pathlib import Path
from typing import Callable

import numpy as np

from playfellow_coop.universal.state import StateClassifier

FOLDER = Path(__file__).with_name("states")


def collect(make_game: Callable[[int], object], seeds: range, steps: int, play: Callable | None = None) -> list[tuple[np.ndarray, str, np.ndarray | None]]:
    """Play `make_game(seed)` and label each picture: "gameplay" while it runs, then "dead" or "victory" for the last pictures. `play(game, rng)` picks a key (random by default)."""
    examples: list[tuple[np.ndarray, str, np.ndarray | None]] = []
    for seed in seeds:
        game = make_game(seed)
        rng = np.random.default_rng(seed)
        previous = None
        for _ in range(steps):
            frame = np.asarray(game.render().convert("RGB"))
            if game.done:
                examples.append((frame, "victory" if game.is_won() else "dead", previous))
                break
            examples.append((frame, "gameplay", previous))
            previous = frame
            game.step(play(game, rng) if play else rng.choice(list(game.keys)))
    return examples


def fit_game(make_game: Callable[[int], object], seeds: range = range(24), steps: int = 300, play: Callable | None = None, max_play: int = 400) -> StateClassifier:
    """A classifier fitted to one game. Gameplay pictures are thinned (the end screens are rare, and the many play pictures must not drown them)."""
    examples = collect(make_game, seeds, steps, play)
    play_frames = [e for e in examples if e[1] == "gameplay"]
    if len(play_frames) > max_play:
        keep = np.linspace(0, len(play_frames) - 1, max_play).astype(int)
        play_frames = [play_frames[i] for i in keep]
    ends = [e for e in examples if e[1] != "gameplay"]
    return StateClassifier().fit(play_frames + ends)


def save(path: Path, model: StateClassifier) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(model.to_json(), indent=1), encoding="utf-8", newline="\n")


def load_state_classifier(game_key: str, folder: Path | None = None) -> StateClassifier | None:
    """The fitted classifier shipped for this game, or None (the watch then acts only on its one strict rule)."""
    path = (folder or FOLDER) / f"{game_key}.json"
    if not path.is_file():
        return None
    return StateClassifier.from_json(json.loads(path.read_text(encoding="utf-8")))
