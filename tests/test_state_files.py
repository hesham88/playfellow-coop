"""UH4: the screen-state files shipped for the five skill games, one per look, fitted on pictures of the size the screen watch reads; a classic one reads a real
classic game through the screen watch itself (the code that uses it in play)."""
import numpy as np
import pytest
from PIL import Image

from playfellow_coop.universal import state_fit
from playfellow_coop.universal.state import FEATURES, INKS
from playfellow_coop.universal.watch import WATCH_SIDE, ScreenWatch

GAMES = ["snake", "box_push", "slide_2048", "lane_dash", "brick_breaker"]


@pytest.mark.parametrize("look", ["classic", "glass"])
@pytest.mark.parametrize("game", GAMES)
def test_every_skill_game_ships_a_fitted_file_for_each_look(game, look):
    model = state_fit.load_state_classifier(game, look=look)
    assert model is not None and model.fitted and len(model.regions) == 2
    assert "gameplay" in model.centres and {"dead", "victory"} & set(model.centres)
    dims = len(FEATURES) + len(INKS) * len(model.regions)
    assert len(model.scale) == dims and all(len(centre) == dims for centre in model.centres.values())


def test_every_state_file_is_package_data_so_an_installed_copy_has_it():
    """setuptools ships package data by glob under the package folder, where * stops at a folder: a file no pattern reaches is missing from an installed copy."""
    import glob
    import tomllib
    from pathlib import Path
    root = Path(state_fit.__file__).resolve().parents[1]
    patterns = tomllib.loads((root.parent / "pyproject.toml").read_text(encoding="utf-8"))["tool"]["setuptools"]["package-data"]["playfellow_coop"]
    shipped = {Path(found).as_posix() for pattern in patterns for found in glob.glob(pattern, root_dir=root)}
    files = {path.relative_to(root).as_posix() for path in (root / "universal" / "states").rglob("*.json")}
    assert files and files <= shipped, sorted(files - shipped)


def test_collect_keeps_pictures_at_the_size_the_watch_reads():
    class Big:
        keys = ("a",)

        def __init__(self, seed):
            self.t, self.done = 0, False

        def render(self):
            return Image.new("RGB", (480, 360), (self.t * 40, 0, 0))

        def step(self, key):
            self.t += 1
            self.done = self.t >= 3

        def is_won(self):
            return True

    rows = state_fit.collect(Big, range(1), 10, frozen_ends=1)
    assert rows and all(max(frame.shape[:2]) == WATCH_SIDE for frame, _, _ in rows)
    assert [label for _, label, _ in rows] == ["gameplay"] * 3 + ["victory"] * 2


def test_a_classic_file_reads_a_real_game_through_the_screen_watch():
    from bench import arena_run as ar
    if state_fit.engine_look() != "classic":
        pytest.skip("the engine on the path draws another look")
    game, rng = ar.load_game("snake", 5), np.random.default_rng(5)
    watch = ScreenWatch(state_fit.load_state_classifier("snake"))
    seen = []
    while not game.done and len(seen) < 400:
        seen.append(watch.look(game.render()).state)
        game.step(rng.choice(list(game.keys)))
    assert game.done and game.is_lost() and len(seen) >= 3
    assert sum(state == "gameplay" for state in seen) / len(seen) >= 0.9  # the bar the files were fitted to
    standing = [watch.look(game.render()) for _ in range(2)]  # the game-over screen, standing still
    assert standing[-1].state == "dead" and "game-over" in standing[-1].note
