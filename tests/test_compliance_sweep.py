"""Compliance sweep: the event's topic rules in this repo, re-checked as one gate.

Covers what `test_repo_rules.py` does not: the excluded ball game is never counted or shown, no game map is
copied into the code (walls and items are read from pixels), and the video material names no restricted game.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import assemble_video  # noqa: E402

EXCLUDED_SLUG = "mini_" + "foot" + "ball"  # the engine's 15th built-in game, left out under the topic rules


def test_the_excluded_game_is_in_no_result_file_and_no_game_table_counts_fifteen():
    result_files = [p for p in (ROOT / "results").rglob("*.json")]
    assert result_files, "no result files found"
    for path in result_files:
        assert EXCLUDED_SLUG not in path.read_text(encoding="utf-8", errors="ignore"), path
    fifteen = json.loads((ROOT / "results" / "fifteen" / "muse-raw-20261102.json").read_text(encoding="utf-8"))
    assert len(fifteen["by_game"]) == 14  # the engine has 15 built-in games; this repo measures 14
    proof = (ROOT / "docs" / "accessibility-proof.md").read_text(encoding="utf-8")
    assert "left out of this repository under the" in proof  # the exclusion is stated, not silent


def test_no_copied_maps_walls_and_items_come_from_pixels():
    obs = (ROOT / "playfellow_coop" / "gym" / "obs.py").read_text(encoding="utf-8")
    assert "PixelObserver" in obs and "class PixelObserver" in obs
    offenders = []
    for path in (ROOT / "playfellow_coop" / "gym").glob("*.py"):
        text = path.read_text(encoding="utf-8")
        if "copied" in text.lower() and "without copied" not in text.lower() and "no copied" not in text.lower():
            offenders.append(path.name)
        for token in ("WALL_MAP", "LEVEL_MAP", "MAP_GRID", "TILE_MAP"):
            if token in text:
                offenders.append(f"{path.name}: {token}")
    assert offenders == []
    assert not list((ROOT / "playfellow_coop").rglob("*map*.json")), "a map data file would be a copied map"


def test_the_video_material_names_no_restricted_game():
    for name in ("docs/video-script.md", "docs/video-shotlist.yaml"):
        assemble_video.check_restricted_names((ROOT / name).read_text(encoding="utf-8"))  # raises on any hit
    script = (ROOT / "docs" / "video-script.md").read_text(encoding="utf-8")
    assert "3:00" in script and "video-shotlist.yaml" in script
    shotlist = (ROOT / "docs" / "video-shotlist.yaml").read_text(encoding="utf-8")
    assert "caption_en" in shotlist and "caption_ar" in shotlist
