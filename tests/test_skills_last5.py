"""Tests for the rung-4 pixel skills for the last five games:
turn_quest, tiny_kingdom, mini_chess, top_racer, mini_fighter.
"""
from __future__ import annotations

import importlib
import os
import sys
from pathlib import Path

import numpy as np
import pytest

from bench import arena_run as ar
from playfellow_coop.gym import check_game
from playfellow_coop.skills import SKILLS
from playfellow_coop.skills.registry import skill_for_game

ROOT = Path(__file__).resolve().parents[1]
INITIAL_TWO = ["turn_quest", "tiny_kingdom"]


def _skinned_engine_dir() -> Path | None:
    candidate = ROOT.parent.parent / "worktrees" / "main-agent-arena" / "software"
    if (candidate / "arena_pack" / "skins" / "assets").is_dir():
        return candidate
    return None


@pytest.mark.parametrize("game_key", INITIAL_TWO)
def test_skill_is_registered_and_oracle_wins_every_seed_with_complete_reward(game_key: str):
    assert game_key in SKILLS
    report = check_game(game_key, lambda seed, g=game_key: ar.load_game(g, seed), seeds=range(3))
    assert report.complete, report.problems
    assert report.wins == 3
    assert all(abs(r - 1.0) < 1e-9 for r in report.returns)


@pytest.mark.parametrize("game_key", INITIAL_TWO)
def test_skill_reads_unskinned_and_refuses_blank_pictures(game_key: str):
    game = ar.load_game(game_key, 0)
    frame = np.asarray(game.render().convert("RGB"))
    skill = skill_for_game(game_key)
    assert skill.detect_look(frame) == "arena"

    blank = np.zeros_like(frame)
    assert skill.detect_look(blank) is None


@pytest.mark.parametrize("game_key", INITIAL_TWO)
def test_skill_reads_and_wins_on_skinned_look_when_skin_worktree_present(game_key: str, monkeypatch: pytest.MonkeyPatch):
    skinned_dir = _skinned_engine_dir()
    if skinned_dir is None:
        pytest.skip("skinned arena worktree not present alongside checkout")
    monkeypatch.setenv("PF_SKIN_DIR", str(skinned_dir / "arena_pack" / "skins" / "assets"))
    monkeypatch.syspath_prepend(str(skinned_dir))
    for mod in [m for m in list(sys.modules) if m == "arena_pack" or m.startswith("arena_pack.")]:
        sys.modules.pop(mod, None)
    try:
        game = ar.load_game(game_key, 0)
        frame = np.asarray(game.render().convert("RGB"))
        skill = skill_for_game(game_key)
        assert skill.detect_look(frame) == "skinned"
        report = check_game(game_key, lambda seed, g=game_key: ar.load_game(g, seed), seeds=range(3))
        assert report.complete, report.problems
        assert report.wins == 3
    finally:
        for mod in [m for m in list(sys.modules) if m == "arena_pack" or m.startswith("arena_pack.")]:
            sys.modules.pop(mod, None)
