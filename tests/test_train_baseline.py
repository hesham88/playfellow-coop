"""The built-in navigator's score on the held-out split (the "base baseline" row): offline, a fresh navigator per row, cold and warm kept apart,
the bake-off's raw format so the accuracy tool can score it, and no number typed in."""
import json
import os
from pathlib import Path

import pytest

from train import baseline as bl
from train import dataset as ds
from practice_arena.game import ArenaGame

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def data(tmp_path_factory):
    folder = tmp_path_factory.mktemp("data")
    ds.write_dataset(folder, 12, 12)
    return folder


class Fixed:
    """A stand-in brain that always presses the same key; it records how often it was asked."""

    def __init__(self, key):
        self.key, self.asked, self._last = key, 0, None

    def ask(self, system, text, images):
        self.asked += 1
        return json.dumps({"thought": "x", "say": "", "actions": [self.key] if self.key else [], "mission_update": {"type": "none"}, "hud": {}, "facts": []})


def test_toward_moves_agree_with_a_walk_by_hand():
    game = ArenaGame()
    best, here, after = bl.toward_moves(game)
    assert best and here > 0 and all(after[k] < here for k in best)
    for key in best:
        probe = ArenaGame()
        probe.press(key.lower())
        assert bl.toward_moves(probe)[1] == here - 1 or probe.coins != game.coins or probe.has_key


def test_a_key_into_a_wall_leaves_the_distance_unchanged():
    best, here, after = bl.toward_moves(ArenaGame())
    assert after["UP"] == here and "UP" not in best  # the first level starts in a corner under the top wall


def test_the_scorer_marks_a_right_and_a_wrong_key(data):
    rows = bl.load_heldout(data)
    labelled = next(r for r in rows if bl.toward_moves(bl.replay(r["frame"]["walk"]))[0])
    good = bl.toward_moves(bl.replay(labelled["frame"]["walk"]))[0][0]
    bad = next(k for k in bl.KEYS if k not in bl.toward_moves(bl.replay(labelled["frame"]["walk"]))[0])
    assert bl.score_rows([labelled], lambda: Fixed(good), False)[0]["toward"] is True
    assert bl.score_rows([labelled], lambda: Fixed(bad), False)[0]["toward"] is False
    assert bl.score_rows([labelled], lambda: Fixed(""), False)[0]["valid"] is False


def test_a_fresh_brain_is_made_for_every_row(data):
    made = []

    def factory():
        made.append(Fixed("UP"))
        return made[-1]

    rows = bl.load_heldout(data)
    bl.score_rows(rows, factory, False)
    assert len(made) == len(rows) and all(b.asked == 1 for b in made)


def test_cold_asks_once_and_warm_first_watches_the_walk(data):
    row = next(r for r in bl.load_heldout(data) if len(r["frame"]["walk"]) > 2)
    cold, warm = Fixed("UP"), Fixed("UP")
    bl.decide(row, lambda: cold, False)
    bl.decide(row, lambda: warm, True)
    assert cold.asked == 1 and warm.asked == len(row["frame"]["walk"]) + 1


def test_the_warm_brain_is_told_the_key_the_walk_pressed():
    seen = []

    class Spy(Fixed):
        def ask(self, system, text, images):
            seen.append(self._last)
            return super().ask(system, text, images)

    row = {"frame": {"walk": ["right", "down"]}}
    bl.decide(row, lambda: Spy("UP"), True)
    assert seen == [None, "RIGHT", "DOWN"]


def test_the_raw_rows_have_the_bake_off_fields_and_the_extra_ones(data):
    rows = bl.score_rows(bl.load_heldout(data)[:4], lambda: Fixed("UP"), False)
    for row in rows:
        assert {"file", "seed", "valid", "label", "action", "distance_before", "distance_after", "toward", "seconds", "error"} <= set(row)
        assert {"intent", "language", "plan_label", "follows_plan"} <= set(row)


def test_only_held_out_rows_are_accepted(tmp_path, data):
    train_only = tmp_path / "d"
    train_only.mkdir()
    (train_only / "heldout.jsonl").write_text((data / "train.jsonl").read_text(encoding="utf-8"), encoding="utf-8")
    with pytest.raises(ValueError):
        bl.load_heldout(train_only)


def test_the_summary_counts_come_from_the_rows(data):
    scored = bl.score_rows(bl.load_heldout(data), lambda: Fixed("UP"), False)
    s = bl.summarize(scored)
    assert s["n"] == len(scored) == 12
    assert s["toward_a_target"]["count"] == sum(r["toward"] for r in scored if r["label"])
    assert s["follows_the_plan"]["of"] == sum(1 for r in scored if r["plan_label"])
    assert sum(v["of"] for v in s["follows_the_plan_by_intent"].values()) == s["follows_the_plan"]["of"]


def test_the_summary_says_what_blind_guessing_would_score_and_how_much_of_one_key_was_pressed(data):
    scored = bl.score_rows(bl.load_heldout(data), lambda: Fixed("UP"), False)
    s = bl.summarize(scored)
    assert s["most_common_key_share"] == 1.0  # a brain that only ever presses UP is a habit, and the summary shows it
    expected = sum(len(r["label"]) for r in scored if r["label"]) / (4 * sum(1 for r in scored if r["label"]))
    assert s["chance_toward"] == round(expected, 4) and 0 < s["chance_toward"] < 1


def test_the_file_names_its_setting_hash_and_the_data_it_was_made_from(tmp_path, data):
    result = bl.run(data, tmp_path / "out", False, factory=lambda: Fixed("UP"), commit="abc1234")
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    m = result["metrics"]
    assert (result["schema"], result["tool"], result["brain"], result["commit"]) == ("pf-results/2", "train_baseline", "builtin", "abc1234")
    assert m["setting"] == "cold" and m["heldout_sha256"] == manifest["heldout_sha256"] and len(m["raw_sha256"]) == 64
    assert (tmp_path / "out" / "baseline-builtin-cold.json").is_file() and (tmp_path / "out" / "baseline-builtin-cold.raw.jsonl").is_file()
    assert result["levels"] == {}  # the letters are written by accuracy_bench, never here


def test_cold_and_warm_are_written_to_separate_files(tmp_path, data):
    bl.run(data, tmp_path / "out", False, factory=lambda: Fixed("UP"))
    bl.run(data, tmp_path / "out", True, factory=lambda: Fixed("UP"))
    assert {p.name for p in (tmp_path / "out").glob("*.json")} == {"baseline-builtin-cold.json", "baseline-builtin-warm.json"}


def test_with_the_real_builtin_navigator_every_row_gets_an_answer_without_a_network(tmp_path, data, monkeypatch):
    import socket

    def refuse(*a, **k):
        raise AssertionError("the navigator must not touch the network")

    monkeypatch.setattr(socket.socket, "connect", refuse)
    for warm in (False, True):
        rows = bl.score_rows(bl.load_heldout(data)[:5], bl.default_factory, warm)
        assert len(rows) == 5 and all(isinstance(r["action"], str) for r in rows)


def test_the_command_line_prints_the_counts(tmp_path, data, capsys):
    assert bl.main(["--data", str(data), "--out", str(tmp_path / "o")]) == 0
    out = capsys.readouterr().out
    assert out.startswith("cold: toward a target ") and "follows the plan" in out


def test_the_baseline_names_no_model_and_reaches_no_network():
    import ast, re
    text = (ROOT / "train" / "baseline.py").read_text(encoding="utf-8")
    imported = set()
    for node in ast.walk(ast.parse(text)):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"urllib", "http", "httpx", "requests", "socket", "websockets", "subprocess", "keyring"}
    assert not re.search(r"\b(muse|gemini|claude|openai|glimmer)\b", text, re.IGNORECASE)


def test_an_unset_engine_variable_falls_back_to_the_installed_engine(monkeypatch):
    from train import baseline

    monkeypatch.delenv("PLAYFELLOW_ENGINE", raising=False)
    assert (baseline.engine_dir() / "controls" / "practice_arena.yaml").is_file()
    assert baseline.default_factory() is not None
