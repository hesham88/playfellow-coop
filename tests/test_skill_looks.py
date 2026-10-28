"""A skill reads a game through a look, so the same skill reads the same game drawn another way: calibrate a look from labelled frames, then play from pixels only."""
from __future__ import annotations

import os
from pathlib import Path

import numpy as np

from bench import arena_run as ar
from playfellow_coop.skills import run_skill
from playfellow_coop.skills.book import SkillBook
from playfellow_coop.skills.calibration import calibrate_look
from playfellow_coop.skills.looks import exact_look, load_looks, role_mask
from playfellow_coop.skills.looks_build import calibrate, save_looks

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


def test_a_look_names_the_nearest_role_inside_its_radius_and_nothing_outside_it():
    look = exact_look("t", {"red": (200, 30, 30), "blue": (30, 30, 200)}, radius=40)
    assert look.classify((205, 35, 28)) == "red" and look.classify((25, 30, 190)) == "blue" and look.classify((120, 120, 120)) is None


def test_calibration_keeps_up_to_four_spread_prototypes_per_role_and_a_radius_that_keeps_roles_apart():
    rng = np.random.default_rng(0)
    samples = {"wall": [(60 + int(rng.integers(-3, 3)), 60, 90) for _ in range(30)] + [(120, 120, 150)] * 5, "coin": [(250, 210, 60)] * 10, "road": [(30, 30, 50)] * 10}
    look = calibrate("x", samples)
    assert len(look.protos["wall"]) >= 2 and look.radius >= 12
    assert look.classify((60, 60, 90)) == "wall" and look.classify((120, 120, 150)) == "wall" and look.classify((250, 210, 60)) == "coin"


def test_looks_save_and_load_and_a_broken_file_loads_as_no_looks(tmp_path):
    look = exact_look("glass", {"head": (10, 20, 30)})
    save_looks(tmp_path / "l.json", [look])
    again = load_looks(tmp_path / "l.json")
    assert again[0].name == "glass" and again[0].classify((11, 21, 29)) == "head"
    (tmp_path / "bad.json").write_text("{nope", encoding="utf-8")
    assert load_looks(tmp_path / "bad.json") == [] and load_looks(tmp_path / "missing.json") == []


def test_a_role_mask_marks_the_pixels_near_a_prototype_and_hides_the_score_bar():
    frame = np.zeros((20, 20, 3), np.uint8)
    frame[5:8, 5:8] = (200, 100, 50)
    frame[0:2, 0:2] = (200, 100, 50)
    mask = role_mask(frame, exact_look("t", {"x": (200, 100, 50)}, radius=10), "x", top=3)
    assert mask[6, 6] and not mask[0, 0] and mask.sum() == 9


def recolour(monkeypatch, module, **names):
    for name, value in names.items():
        monkeypatch.setattr(module, name, value)


def test_snake_is_read_in_a_recoloured_look_after_calibration_and_not_before(monkeypatch):
    from arena_pack import snake as module
    recolour(monkeypatch, module, HEAD=(250, 120, 30), BODY=(40, 130, 200), FOOD=(230, 230, 40), FLOOR=(10, 40, 30), FLOOR_LINE=(14, 50, 36))
    module._floor.cache_clear()
    assert SkillBook("snake").readable(ar.load_game("snake", 0).render()) is False  # the plain look does not fit this one
    look = calibrate_look("snake", "orange", lambda seed: ar.load_game("snake", seed))
    book = SkillBook("snake", looks=[look])
    assert book.readable(ar.load_game("snake", 1).render()) is True and book.look_name == "orange"
    game = ar.load_game("snake", 1)
    run_skill(book.skill, game.render, lambda k: game.step(k), lambda: game.done, set(game.keys))
    assert game.is_won()
    module._floor.cache_clear()


def test_slide_2048_is_read_in_a_recoloured_look_after_calibration(monkeypatch):
    from arena_pack import slide_2048 as module
    shifted = {k: (v[2], v[0], v[1]) for k, v in module.COLOURS.items()}  # every tile colour rotated: nothing matches the plain look
    recolour(monkeypatch, module, COLOURS=shifted)
    assert SkillBook("slide_2048").readable(ar.load_game("slide_2048", 0).render()) is False
    look = calibrate_look("slide_2048", "rotated", lambda seed: ar.load_game("slide_2048", seed), steps=150)
    book = SkillBook("slide_2048", looks=[look])
    game = ar.load_game("slide_2048", 2)
    assert book.readable(game.render())
    run_skill(book.skill, game.render, lambda k: game.step(k), lambda: game.done, set(game.keys))
    assert game.is_won()


def test_box_push_is_read_in_a_recoloured_look_after_calibration(monkeypatch):
    from arena_pack import box_push as module
    recolour(monkeypatch, module, WALL=(120, 40, 40), FLOOR=(30, 60, 30), GOAL=(240, 240, 60), BOX=(60, 200, 220), BOX_DONE=(200, 60, 200), PLAYER=(250, 140, 20))
    assert SkillBook("box_push").readable(ar.load_game("box_push", 0).render()) is False
    look = calibrate_look("box_push", "autumn", lambda seed: ar.load_game("box_push", seed), steps=120)
    book = SkillBook("box_push", looks=[look])
    game = ar.load_game("box_push", 0)
    assert book.readable(game.render())
    run_skill(book.skill, game.render, lambda k: game.step(k), lambda: game.done, set(game.keys))
    assert game.is_won()


def test_the_lane_runner_reads_a_recoloured_look_after_calibration(monkeypatch):
    from arena_pack import lane_dash as ld
    recolour(monkeypatch, ld, COLOURS={"train": (40, 200, 90), "low": (200, 40, 160), "high": (240, 240, 240), "coin": (20, 120, 250)}, ROAD=(60, 30, 20), PLAYER=(250, 250, 50))
    assert SkillBook("lane_dash").readable(ar.load_game("lane_dash", 0).render()) is False
    look = calibrate_look("lane_dash", "river", lambda seed: ar.load_game("lane_dash", seed), seeds=range(40), steps=60)
    book = SkillBook("lane_dash", looks=[look])
    game = ar.load_game("lane_dash", 3)
    assert book.readable(game.render())
    run_skill(book.skill, game.render, lambda k: game.step(k), lambda: game.done, set(game.keys), max_steps=250)
    assert game.progress()["seconds"] >= 20 and not game.is_lost()  # it survived the first twenty seconds reading the new look


def test_the_paddle_reads_a_recoloured_look_after_calibration(monkeypatch):
    from arena_pack import brick_breaker as bb
    recolour(monkeypatch, bb, COLOURS={1: (250, 80, 80), 2: (80, 250, 80)}, BACK=(10, 30, 10), PADDLE=(255, 200, 0), BALL=(0, 255, 255))
    assert SkillBook("brick_breaker").readable(ar.load_game("brick_breaker", 0).render()) is False
    look = calibrate_look("brick_breaker", "green", lambda seed: ar.load_game("brick_breaker", seed), seeds=range(3), steps=60)
    book = SkillBook("brick_breaker", looks=[look])
    game = ar.load_game("brick_breaker", 0)
    assert book.readable(game.render())
    run_skill(book.skill, game.render, lambda k: game.step(k), lambda: game.done, set(game.keys), max_steps=600)
    assert game.progress()["launched"] and game.progress()["bricks_left"] < 32 and game.progress()["lives"] == 3


def test_a_calibrated_brick_look_knows_every_brick_strength_not_only_those_of_the_first_level():
    from bench import arena_run as ar
    look = calibrate_look("brick_breaker", "plain", lambda seed: ar.load_game("brick_breaker", seed), seeds=range(2), steps=30)
    colours = {tuple(round(c / 10) for c in p) for p in look.protos["brick"]}
    assert len(look.protos["brick"]) >= 2 and len(colours) >= 2  # a second brick colour (the stronger bricks of later levels) is in the look
