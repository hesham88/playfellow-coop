"""Rung-4 human pixel skills and gym oracle checks for maze_chase, key_caves, action_quest, and ray_maze."""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import numpy as np
from PIL import Image
import pytest

from bench import arena_run as ar
from playfellow_coop.gym import check_game
from playfellow_coop.skills import SKILLS, run_skill, skill_for_game
from playfellow_coop.skills.book import SkillBook

ROOT = Path(__file__).resolve().parents[1]
F4_GAMES = ("maze_chase", "key_caves", "action_quest", "ray_maze")


def _skinned_engine_dir() -> Path | None:
    candidate = ROOT.parent.parent / "worktrees" / "main-agent-arena" / "software"
    if (candidate / "arena_pack" / "skins" / "assets").is_dir():
        return candidate
    return None


@pytest.mark.parametrize("game_key", F4_GAMES)
def test_f4_skill_is_registered_and_oracle_wins_every_seed_with_complete_reward(game_key: str):
    assert game_key in SKILLS
    report = check_game(game_key, lambda seed, g=game_key: ar.load_game(g, seed), seeds=range(3))
    assert report.complete, (game_key, report.problems)
    assert report.wins == 3
    assert all(abs(r - 1.0) < 1e-9 for r in report.returns)


@pytest.mark.parametrize("game_key", F4_GAMES)
def test_f4_skill_reads_unskinned_and_refuses_blank_pictures(game_key: str):
    game = ar.load_game(game_key, 0)
    frame = np.asarray(game.render().convert("RGB"))
    skill = skill_for_game(game_key)
    skill.reset()
    assert skill.detect_look(frame) == "arena"
    book = SkillBook(game_key)
    assert book.readable(game.render()) is True
    blank = Image.new("RGB", game.pixel_size, (30, 30, 60))
    assert book.readable(blank) is False


@pytest.mark.parametrize("game_key", F4_GAMES)
def test_f4_skill_reads_and_wins_on_skinned_look_when_skin_worktree_present(game_key: str, monkeypatch: pytest.MonkeyPatch):
    skinned_dir = _skinned_engine_dir()
    if skinned_dir is None:
        pytest.skip("skinned arena worktree not present alongside checkout")
    monkeypatch.setenv("PF_SKIN_DIR", str(skinned_dir / "arena_pack" / "skins" / "assets"))
    monkeypatch.syspath_prepend(str(skinned_dir))
    for mod in [m for m in list(sys.modules) if m == "arena_pack" or m.startswith("arena_pack.")]:
        sys.modules.pop(mod, None)
    skins = importlib.import_module("arena_pack.skins")
    skins.clear_caches()
    try:
        game = ar.load_game(game_key, 0)
        frame = np.asarray(game.render().convert("RGB"))
        skill = skill_for_game(game_key)
        skill.reset()
        assert skill.detect_look(frame) == "skinned"
        result = run_skill(skill, game.render, lambda key: game.step(key), lambda: game.done, set(game.keys))
        assert game.is_won(), (game_key, result.stopped, game.progress())
    finally:
        for mod in [m for m in list(sys.modules) if m == "arena_pack" or m.startswith("arena_pack.")]:
            sys.modules.pop(mod, None)


def test_f4_skills_react_to_pixel_changes_on_the_board():
    # 1. maze_chase: moving the player from (1,1) to (3,1) changes the chosen step
    mc = ar.load_game("maze_chase", 0)
    s_mc = skill_for_game("maze_chase")
    s_mc.reset()
    f1 = np.asarray(mc.render().convert("RGB"))
    k1 = s_mc.next_key(f1)
    mc.player = (2, 1)
    mc.coins = {(1, 1)}
    f2 = np.asarray(mc.render().convert("RGB"))
    s_mc.reset()
    k2 = s_mc.next_key(f2)
    assert k1 == "down" and k2 == "left"

    # 2. key_caves: standing before spikes at (20, 8) jumps ("space"), while open ground at (4, 8) walks ("right")
    kc = ar.load_game("key_caves", 0)
    s_kc = skill_for_game("key_caves")
    s_kc.reset()
    assert s_kc.next_key(np.asarray(kc.render().convert("RGB"))) == "right"
    kc.x, kc.y = 20, 8
    s_kc.reset()
    assert s_kc.next_key(np.asarray(kc.render().convert("RGB"))) == "space"

    # 3. action_quest: danger square under the hero makes the skill step away instead of attacking
    aq = ar.load_game("action_quest", 0)
    s_aq = skill_for_game("action_quest")
    aq.hero["x"], aq.hero["y"] = 8, 4
    aq.boss["x"], aq.boss["y"] = 9, 4
    aq.boss["danger"] = []
    s_aq.reset()
    assert s_aq.next_key(np.asarray(aq.render().convert("RGB"))) == "j"
    aq.boss["danger"] = [(8, 4), (8, 3), (8, 5)]
    s_aq.reset()
    assert s_aq.next_key(np.asarray(aq.render().convert("RGB"))) == "a"

    # 4. ray_maze: facing a red target shoots ("space"), after target is gone it moves/turns
    rm = ar.load_game("ray_maze", 0)
    s_rm = skill_for_game("ray_maze")
    rm.x, rm.y, rm.facing = 1, 3, 2  # facing target at (1, 4)
    s_rm.reset()
    assert s_rm.next_key(np.asarray(rm.render().convert("RGB"))) == "space"
    rm.targets.remove((1, 4))
    s_rm.reset()
    assert s_rm.next_key(np.asarray(rm.render().convert("RGB"))) != "space"


def test_oracle_steps_file_covers_all_fourteen_games():
    import json

    path = ROOT / "results" / "fifteen" / "oracle-steps-20261102.json"
    doc = json.loads(path.read_text(encoding="utf-8"))
    assert set(doc) == set(ar.GAMES) and len(doc) == 14
    for game_key, entry in doc.items():
        assert entry["max_ticks"] > 0
        assert entry["oracle_won"] is True
        assert entry["oracle_steps"] > 0 and entry["oracle_steps"] <= entry["max_ticks"]
        assert entry["skill"] is (game_key in SKILLS)
        assert isinstance(entry["steps_per_seed"], dict) and entry["steps_per_seed"]["0"] == entry["oracle_steps"]

