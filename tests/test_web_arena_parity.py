"""D-2: the web arena twin. Its levels, lines and winning keys are MADE from the Python Practice Arena, so the two cannot drift; the browser code
is tested in Node against them. Skipped (not failed) only when Node is missing."""
import json
import os
import shutil
import subprocess
from pathlib import Path

import pytest

WEB = Path(__file__).resolve().parents[1] / "demo" / "web"


def _load():
    import importlib.util
    spec = importlib.util.spec_from_file_location("make_levels_under_test", WEB / "make_levels.py")
    module = importlib.util.module_from_spec(spec)
    import sys
    sys.modules[spec.name] = module
    spec.loader.exec_module(module)
    return module


ml = _load()
from practice_arena.game import ArenaGame  # noqa: E402


def test_the_files_on_disk_are_what_the_python_arena_gives_now():
    assert ml.main(["--check"]) == 0


def test_every_level_is_solvable_and_the_stored_keys_win_it_in_the_python_arena():
    expected = json.loads((WEB / "expected.json").read_text(encoding="utf-8"))["levels"]
    levels = json.loads((WEB / "levels.json").read_text(encoding="utf-8"))["levels"]
    assert [l["id"] for l in levels] == list(expected) == ["garden", "winding", "short"]
    for level in levels:
        game = ArenaGame(tuple(level["rows"]))
        coins = game.coins_left
        for key in expected[level["id"]]["keys"]:
            game.press(key)
        assert game.won and game.coins_left == 0 and game.bumps == 0
        assert expected[level["id"]]["coins"] == coins and expected[level["id"]]["steps"] == len(expected[level["id"]]["keys"]) == game.moves


def test_the_first_level_is_the_python_arenas_own_level():
    from practice_arena.game import LEVEL
    assert json.loads((WEB / "levels.json").read_text(encoding="utf-8"))["levels"][0]["rows"] == list(LEVEL)


def test_the_lines_are_the_python_arenas():
    from practice_arena.game import TEXTS
    assert json.loads((WEB / "texts.json").read_text(encoding="utf-8"))["texts"] == {k: dict(v) for k, v in TEXTS.items()}


def test_a_search_gives_the_same_keys_every_time():
    rows = json.loads((WEB / "levels.json").read_text(encoding="utf-8"))["levels"][1]["rows"]
    assert ml.winning_keys(rows) == ml.winning_keys(rows)


def test_a_level_with_an_unreachable_target_is_refused(monkeypatch):
    monkeypatch.setattr(ml, "LEVELS", [{"id": "bad", "title": {"english": "x", "arabic": "x"}, "rows": ["#######", "#Pc#k.#", "#####D#", "#######"]}])
    monkeypatch.setattr(ml, "ArenaGame", ArenaGame)
    with pytest.raises(AssertionError):
        ml.build()


def test_the_page_module_data_never_carries_the_answer():
    text = (WEB / "data.mjs").read_text(encoding="utf-8")
    assert "final_score" not in text and '"keys"' not in text


@pytest.mark.skipif(shutil.which("node") is None and not os.environ.get("PF_REQUIRE_NODE"), reason="Node is not installed (CI sets PF_REQUIRE_NODE=1, which makes this a failure instead of a skip)")
def test_the_browser_code_passes_its_own_tests_in_node():
    done = subprocess.run(["node", "--test", "arena.test.mjs"], cwd=WEB, capture_output=True, text=True, timeout=120)
    assert done.returncode == 0, done.stdout[-1500:] + done.stderr[-500:]


def test_no_web_file_is_a_dashboard_or_names_a_restricted_thing():
    import re
    names = re.compile(r"nvidia|deepmind|\bsima\b|nitrogen|streamlit|dashboard", re.IGNORECASE)
    for path in WEB.iterdir():
        if path.suffix in (".mjs", ".html", ".py", ".json"):
            assert not names.search(path.read_text(encoding="utf-8")), path.name
