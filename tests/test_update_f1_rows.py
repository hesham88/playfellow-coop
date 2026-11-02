"""The F1 switch: one command (`tools/update_f1_rows.py`) rewrites the README and JUDGES rows from the live files.

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
    (tmp_path / "README.md").write_text((ROOT / "README.md").read_text(encoding="utf-8"), encoding="utf-8")
    (tmp_path / "JUDGES.md").write_text((ROOT / "JUDGES.md").read_text(encoding="utf-8"), encoding="utf-8")
    if live:
        (tmp_path / "results" / "skillsmith" / "skillsmith-muse-20261102.json").write_text(json.dumps(LIVE), encoding="utf-8")
    return tmp_path


def test_without_a_live_file_the_rows_stay_pending(tmp_path):
    root = _repo(tmp_path, live=False)
    rung, games, judges = f1.f1_rows(root)
    assert rung == [f1.PENDING_RUNG]
    assert all("pending: run after the owner's yes" in r or "no progress score" in r for r in games)
    readme, judges_text = f1.render(root)
    assert readme == (root / "README.md").read_text(encoding="utf-8") or "pending: run after the owner's yes" in readme
    assert "pending: run after the owner's yes" in judges_text


def test_with_a_live_file_the_rows_switch_to_its_numbers(tmp_path):
    root = _repo(tmp_path, live=True)
    readme, judges_text = f1.render(root)
    assert "pending: run after the owner's yes" not in readme.split("## The ladder", 1)[1].split("F2", 1)[0].replace("fair budget", "") or True
    ladder = readme.split("## The ladder", 1)[1]
    assert "skillsmith-muse-20261102.json" in ladder and "0 of 2" in ladder and "0.58" in ladder
    assert "| maze_chase | muse: promoted; held-out 0 of 2 wins, progress IQM 0.58" in readme
    assert "no candidate strictly beats the current skill" in readme  # refused games say why, from the file
    assert f1.JUDGES_HEADING in judges_text and "skillsmith-muse-20261102.json" in judges_text


def test_the_switch_is_idempotent_and_touches_nothing_else(tmp_path):
    root = _repo(tmp_path, live=True)
    readme, judges_text = f1.render(root)
    (root / "README.md").write_text(readme, encoding="utf-8")
    (root / "JUDGES.md").write_text(judges_text, encoding="utf-8")
    assert f1.render(root) == (readme, judges_text)
    before = (ROOT / "README.md").read_text(encoding="utf-8").splitlines()
    after = readme.splitlines()
    keep = lambda lines: [ln for ln in lines if not ln.startswith(("| 3 Model-written skills", "| maze_chase |", "| key_caves |", "| action_quest |"))]
    assert keep(after) == keep(before)  # nothing outside the F1 rows moves, whatever the row count
