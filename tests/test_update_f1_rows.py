"""The SkillSmith switch: one command (`tools/update_f1_rows.py`) rewrites the docs/metrics.md and JUDGES rows from the live files.

With no live file the rows stay pending; with one, they carry its held-out wins, progress and cost, and no other
line moves. The switch is exercised on copies in a temp folder, never on the real docs.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import update_f1_rows as f1  # noqa: E402

LIVE = {"games": {
    "maze_chase": {"supported": True, "promoted": "cand1", "writing": {"cost_usd": 0.16},
                   "held_out": {"played": True, "wins": 0, "progress_iqm": 0.58,
                                "episodes": [{"won": False}, {"won": False}]}},
    "key_caves": {"supported": True, "promoted": None, "writing": {"cost_usd": 0.25},
                  "held_out": {"played": False, "reason": "no candidate strictly beats the current skill on validation"}},
    "action_quest": {"supported": True, "promoted": None, "writing": {"cost_usd": 0.33},
                     "held_out": {"played": False, "reason": "no candidate strictly beats the current skill on validation"}},
}}


def _repo(tmp_path: Path, live: bool) -> Path:
    (tmp_path / "results" / "skillsmith").mkdir(parents=True)
    (tmp_path / "docs").mkdir()
    (tmp_path / "docs" / "metrics.md").write_text((ROOT / "docs" / "metrics.md").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "JUDGES.md").write_text((ROOT / "JUDGES.md").read_text(encoding="utf-8"), encoding="utf-8")
    if live:
        (tmp_path / "results" / "skillsmith" / "skillsmith-muse-20261102.json").write_text(json.dumps(LIVE), encoding="utf-8")
    return tmp_path


def test_without_a_live_file_the_rows_stay_pending(tmp_path):
    root = _repo(tmp_path, live=False)
    rung, games, judges = f1.f1_rows(root)
    assert rung == [f1.PENDING_RUNG]
    assert all(f1.PENDING in r or "no progress score" in r for r in games)
    readme, judges_text = f1.render(root)
    assert f1.PENDING in readme and f1.PENDING in judges_text


def test_with_a_live_file_the_rows_switch_to_its_numbers(tmp_path):
    root = _repo(tmp_path, live=True)
    readme, judges_text = f1.render(root)
    ladder = readme.split("## The ladder", 1)[1]
    assert f1.PENDING not in ladder
    assert "skillsmith-muse-20261102.json" in ladder and "0 of 2" in ladder and "0.58" in ladder
    assert "| maze_chase | muse: promoted; held-out 0 of 2 wins, progress IQM 0.58" in readme
    assert "no candidate strictly beats the current skill" in readme  # refused games say why, from the file
    assert f1.JUDGES_HEADING in judges_text and "skillsmith-muse-20261102.json" in judges_text


def test_the_switch_is_idempotent_and_touches_nothing_else(tmp_path):
    root = _repo(tmp_path, live=True)
    readme, judges_text = f1.render(root)
    (root / "docs" / "metrics.md").write_text(readme, encoding="utf-8")
    (root / "JUDGES.md").write_text(judges_text, encoding="utf-8")
    assert f1.render(root) == (readme, judges_text)
    before = (ROOT / "docs" / "metrics.md").read_text(encoding="utf-8").splitlines()
    after = readme.splitlines()
    keep = lambda lines: [ln for ln in lines if not ln.startswith(("| 3 Model-written skills", "| maze_chase |", "| key_caves |", "| action_quest |", "| osg_2048 |"))]
    assert keep(after) == keep(before)  # nothing outside the F1 rows moves, whatever the row count


def test_each_game_takes_the_newest_file_that_ran_it_so_a_later_single_game_run_never_hides_the_others(tmp_path):
    """3 Nov: the open brain had a 3-game file (2 Nov) and a 2048 file (3 Nov); "newest file per brain" kept only 2048 and dropped
    the three games, and for Muse the alphabetical last ("muse-room") hid the newer 2048 file. Time order, per game, fixes both."""
    root = _repo(tmp_path, live=False)
    folder = root / "results" / "skillsmith"

    def doc(written, games):
        return json.dumps({"written": written, "games": {g: LIVE["games"]["maze_chase"] if g != "osg_2048" else {
            "supported": True, "promoted": "c2", "writing": {"cost_usd": 0.04},
            "held_out": {"played": True, "wins": 0, "progress_iqm": 0.65, "episodes": [{"won": False}, {"won": False}]}} for g in games}})

    three = ("maze_chase", "key_caves", "action_quest")
    (folder / "skillsmith-open-20261102.json").write_text(doc("2026-11-02T15:40:00+02:00", three), encoding="utf-8")
    (folder / "skillsmith-open-2048-20261103.json").write_text(doc("2026-11-03T00:30:00+02:00", ("osg_2048",)), encoding="utf-8")
    (folder / "skillsmith-muse-2048-20261103.json").write_text(doc("2026-11-03T00:20:00+02:00", ("osg_2048",)), encoding="utf-8")
    (folder / "skillsmith-muse-room-20261102.json").write_text(doc("2026-11-02T16:30:00+02:00", three), encoding="utf-8")
    picked = f1.live_files(root)
    assert picked["open"]["maze_chase"].name == "skillsmith-open-20261102.json"
    assert picked["open"]["osg_2048"].name == "skillsmith-open-2048-20261103.json"
    assert picked["muse"]["osg_2048"].name == "skillsmith-muse-2048-20261103.json"
    assert picked["muse"]["key_caves"].name == "skillsmith-muse-room-20261102.json"
    rung, games, judges = f1.f1_rows(root)
    assert any(r.startswith("| osg_2048 |") and "0.65" in r for r in games)
    assert any(r.startswith("| maze_chase |") and "open: promoted" in r and "muse: promoted" in r for r in games)
    open_rung = next(r for r in rung if "Open writes" in r)
    assert "0 of 8" in open_rung  # 4 games x 2 held-out episodes, from both files
    assert len(judges) == 8


def test_with_no_live_file_each_game_keeps_its_own_pending_row(tmp_path):
    _, games, _ = f1.f1_rows(_repo(tmp_path, live=False))
    assert next(r for r in games if r.startswith("| action_quest |")).count("cannot be scored") == 1
    assert next(r for r in games if r.startswith("| osg_2048 |")).startswith("| osg_2048 | pending")
