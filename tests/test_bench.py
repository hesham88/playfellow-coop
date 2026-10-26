"""The speed bench writes one pf-results/1 file with only measured numbers."""
from __future__ import annotations

import json

import pytest

from meta_playfellow import bench
from meta_playfellow.stage_timer import NOT_MEASURED, STAGES
from tests.test_session_and_handover import Brain, make  # noqa: F401


def _run(tmp_path, brain=None, git=("a" * 40, False), turns=4):
    parts, cfg = make(brain or Brain())
    path = bench.run_bench(parts, cfg, "system", turns, tmp_path, "builtin", "none", git=git, wait=lambda s: False)
    return path, json.loads(path.read_text(encoding="utf-8"))


def test_the_file_has_the_pf_results_shape_and_the_commit(tmp_path):
    path, data = _run(tmp_path)
    assert data["schema"] == "pf-results/1" and data["tool"] == "speed_bench"
    assert data["commit"] == "a" * 40 and data["dirty"] is False and data["metrics"]["label"] == "clean"
    assert data["brain"] == "builtin" and set(data["machine"]) == {"cpu", "ram_gb", "gpu", "os", "load"}
    assert path.name.startswith("speed_bench-") and path.suffix == ".json"
    assert (tmp_path / data["raw"]).is_file()


def test_every_measured_stage_has_p50_p90_p95_and_the_others_say_not_measured(tmp_path):
    _, data = _run(tmp_path)
    stages = data["metrics"]["stages"]
    assert set(stages) == set(STAGES)
    for name in ("capture", "shrink", "request", "parse_and_check", "key_down"):
        assert set(stages[name]) == {"n", "p50", "p90", "p95"} and stages[name]["n"] == 4
        assert 0 < stages[name]["p50"] <= stages[name]["p90"] <= stages[name]["p95"]
    assert stages["encode"] == NOT_MEASURED  # this brain times nothing inside; the file does not invent a number


def test_the_numbers_come_from_the_per_turn_log_and_nothing_else(tmp_path):
    _, data = _run(tmp_path, turns=5)
    raw = [json.loads(line) for line in (tmp_path / data["raw"]).read_text(encoding="utf-8").splitlines()]
    assert len(raw) == 5 == data["metrics"]["turns"]
    request = sorted(turn["request"] for turn in raw)
    assert data["metrics"]["stages"]["request"]["p50"] == request[2]  # nearest rank on 5 samples
    assert data["metrics"]["stages"]["request"]["p95"] == request[4]


def test_a_dirty_tree_is_labelled_a_diagnostic(tmp_path):
    _, data = _run(tmp_path, git=("b" * 40, True))
    assert data["dirty"] is True and data["metrics"]["label"].startswith("diagnostic")


def test_a_slow_brain_shows_up_in_the_request_numbers(tmp_path):
    _, data = _run(tmp_path, brain=Brain(delay=0.1), turns=3)
    assert data["metrics"]["stages"]["request"]["p50"] >= 0.09
    assert data["metrics"]["stages"]["capture"]["p50"] < 0.05


def test_git_state_reads_the_real_repo_or_says_it_cannot(tmp_path):
    commit, dirty = bench.git_state(tmp_path)  # a folder that is not a git repo
    assert commit == NOT_MEASURED and dirty is True
    commit, dirty = bench.git_state()
    assert commit == NOT_MEASURED or len(commit) == 40


def test_the_machine_block_never_claims_a_gpu_or_a_load_it_did_not_read():
    info = bench.machine()
    assert info["gpu"] == NOT_MEASURED and info["load"] == NOT_MEASURED
    assert info["os"]
    with pytest.raises(KeyError):
        info["fps"]
