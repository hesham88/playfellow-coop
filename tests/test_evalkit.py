"""Evaluation done honestly: known-value checks for the statistics, attribution labels, the ladder, the LSIAP measures, the cost model and the receipt."""
from __future__ import annotations

import math

import numpy as np
import pytest

from playfellow_coop.evalkit import attribution, costmodel, ladder, lsiap, receipt, stats


# ---- rliable-style statistics -------------------------------------------------------------------------------------------------------
def test_iqm_is_the_mean_of_the_middle_half_and_resists_outliers():
    assert stats.iqm([1, 2, 3, 4, 5, 6, 7, 8]) == pytest.approx(4.5)
    assert stats.iqm([1, 2, 3, 4, 5]) == pytest.approx(3.0)
    assert stats.iqm([1, 1, 1, 1, 1, 1, 1, 1000]) == pytest.approx(1.0) and np.mean([1, 1, 1, 1, 1, 1, 1, 1000]) > 100
    with pytest.raises(ValueError):
        stats.iqm([])


def test_human_normalised_score_gap_and_probability_of_improvement():
    assert stats.human_normalized(50, 10, 90) == pytest.approx(0.5) and stats.human_normalized(5, 5, 5) == 0.0 and stats.human_normalized(100, 10, 90) > 1
    assert stats.optimality_gap([0.5, 1.5, 2.0]) == pytest.approx(0.5 / 3)
    assert stats.probability_of_improvement([3, 4], [1, 2]) == 1.0 and stats.probability_of_improvement([1, 2], [3, 4]) == 0.0
    assert stats.probability_of_improvement([1, 2], [1, 2]) == pytest.approx(0.5)


def test_stratified_bootstrap_is_deterministic_contains_the_point_and_narrows_with_more_runs():
    few = {"a": [0.1, 0.9, 0.5], "b": [0.4, 0.6, 0.5]}
    many = {"a": [0.1, 0.9, 0.5] * 10, "b": [0.4, 0.6, 0.5] * 10}
    p1, lo1, hi1 = stats.stratified_bootstrap(few, reps=500, seed=1)
    assert (p1, lo1, hi1) == stats.stratified_bootstrap(few, reps=500, seed=1)
    p2, lo2, hi2 = stats.stratified_bootstrap(many, reps=500, seed=1)
    assert lo1 <= p1 <= hi1 and lo2 <= p2 <= hi2 and (hi2 - lo2) < (hi1 - lo1)
    with pytest.raises(ValueError):
        stats.stratified_bootstrap({"a": []})


def test_glass_delta_harness_lift_budgeted_success_and_wilson():
    assert stats.glass_delta([0.9, 0.8, 1.0], [0.1, 0.0, 0.2]) == pytest.approx((0.9 - 0.1) / 0.1)
    assert stats.glass_delta([1, 1], [0, 0]) == math.inf and stats.glass_delta([0, 0], [1, 1]) == -math.inf and stats.glass_delta([1, 1], [1, 1]) == 0.0
    assert stats.harness_lift(0.7, 0.1) == pytest.approx(0.6)
    episodes = [{"won": True, "cost_usd": 0.05}, {"won": True, "cost_usd": 0.5}, {"won": False, "cost_usd": 0.01}]
    assert stats.budgeted_success_rate(episodes, 0.20) == pytest.approx(1 / 3) and stats.budgeted_success_rate([], 1.0) == 0.0
    low, high = stats.wilson(8, 10)
    assert 0.49 < low < 0.5 and 0.94 < high < 0.96 and stats.wilson(0, 0) == (0.0, 1.0)


# ---- attribution --------------------------------------------------------------------------------------------------------------------
def test_origin_shares_drive_the_label_and_a_row_never_shows_a_win_rate_without_who_played():
    shares = attribution.origin_share(["human_skill"] * 92 + ["model_chunk"] * 6 + ["fallback"] * 2)
    assert shares.human_skill == pytest.approx(0.92) and attribution.label(shares) == "[Assisted: Human Local Skill]"
    auto = attribution.origin_share(["model_skill"] * 9 + ["model_chunk"])
    assert attribution.label(auto) == "[Autonomous: Model-Synthesized Skill]"
    assert attribution.label(attribution.origin_share(["model_chunk"] * 5)) == "[Model Alone]" and attribution.origin_share([]).human_skill == 0.0
    with pytest.raises(ValueError):
        attribution.origin_share(["mystery"])
    line = attribution.row("snake", 0.81, shares)
    assert "81%" in line and "[Assisted: Human Local Skill]" in line and "92% human skill" in line


def test_lifts_live_clock_penalty_and_action_age_percentiles():
    assert attribution.marginal_model_lift(0.8, 0.5) == pytest.approx(0.3) and attribution.autonomous_skill_lift(0.6, 0.1) == pytest.approx(0.5)
    assert attribution.live_clock_penalty(0.5, 0.1) == pytest.approx(0.8) and attribution.live_clock_penalty(0.0, 0.1) == 0.0
    p50, p99 = attribution.action_age_ms([0.0] * 100, [i / 1000 for i in range(100)])
    assert 45 <= p50 <= 55 and p99 >= 97 and attribution.action_age_ms([], []) == (0.0, 0.0)


# ---- the ladder ---------------------------------------------------------------------------------------------------------------------
def test_each_run_lands_on_exactly_one_rung_and_mixed_help_takes_the_stricter_label():
    assert ladder.rung_for(False, True, False, "live").key == "local_floor"
    assert ladder.rung_for(True, False, False, "live").key == "raw_live" and ladder.rung_for(True, False, False, "paused").key == "raw_paused"
    assert ladder.rung_for(True, False, True, "live").key == "model_skills" and ladder.rung_for(True, True, True, "live").key == "human_skills"
    assert [r.number for r in ladder.RUNGS] == [0, 1, 2, 3, 4] and ladder.table().count("\n") == 6


# ---- LSIAP --------------------------------------------------------------------------------------------------------------------------
def test_level_progression_is_pulled_down_by_one_missing_milestone():
    assert lsiap.level_progression([100, 100, 100]) == pytest.approx(100.0)
    assert lsiap.level_progression([100, 100, 0]) < lsiap.level_progression([60, 60, 60]) + 40
    assert lsiap.level_progression([0, 0]) == 0.0 and lsiap.level_progression([100, 100, 0]) == pytest.approx((101 * 101) ** (1 / 3) - 1)


def test_dependency_weights_make_foundations_count_more_than_leaves():
    graph = {"wood": [], "plank": ["wood"], "table": ["plank"], "pickaxe": ["table"]}
    counts = lsiap.downstream_counts(graph)
    assert counts == {"wood": 3, "plank": 2, "table": 1, "pickaxe": 0}
    done = {"wood": 0.0, "plank": 1.0, "table": 1.0, "pickaxe": 1.0}
    flat = np.mean(list(done.values()))
    weighted = lsiap.dependency_weighted_score(done, graph)
    assert weighted < flat  # failing the foundation costs more than failing a leaf
    assert lsiap.dependency_weighted_score(done, graph, invariant_pass_rate=0.5) == pytest.approx(weighted * 0.5)
    leaf_missing = lsiap.dependency_weighted_score({"wood": 1.0, "plank": 1.0, "table": 1.0, "pickaxe": 0.0}, graph)
    assert leaf_missing > weighted


def test_speed_intelligence_and_accuracy_measures():
    assert lsiap.real_time_gap(1.6, 0.48) == pytest.approx(0.7) and lsiap.real_time_gap(0.0, 0.5) == 0.0
    assert lsiap.budget_overruns([10, 20, 40, 50], 33.3) == 0.5 and lsiap.budget_overruns([], 10) == 0.0
    assert lsiap.relative_human_action_efficiency(60, 100) == pytest.approx(0.6) and lsiap.relative_human_action_efficiency(5, 0) == math.inf
    scores = lsiap.capability_scores({"a": 1.0, "b": 0.0}, {"a": {"planning": 3, "reasoning": 1}, "b": {"planning": 1}})
    assert scores["planning"] == pytest.approx(0.75) and scores["reasoning"] == pytest.approx(1.0)
    assert lsiap.subproblem_f1({1, 2}, {2, 3}) == pytest.approx(0.5) and lsiap.subproblem_f1(set(), set()) == 1.0 and lsiap.subproblem_f1({1}, {2}) == 0.0
    assert lsiap.action_compliance(["up", "space", "up"], {"up", "down"}) == pytest.approx(2 / 3) and lsiap.action_compliance([], {"up"}) == 1.0
    assert lsiap.iou((0, 0, 10, 10), (5, 5, 15, 15)) == pytest.approx(25 / 175) and lsiap.iou((0, 0, 1, 1), (2, 2, 3, 3)) == 0.0
    assert lsiap.seam_smoothness([[[0.0, 0.0], [0.1, 0.0]], [[0.15, 0.0], [0.2, 0.0]]]) == pytest.approx(0.05) and lsiap.seam_smoothness([]) == 0.0


def test_glicko2_matches_the_worked_example_from_the_published_paper():
    rating, rd, vol = lsiap.glicko2_update(1500.0, 200.0, 0.06, [(1400.0, 30.0, 1.0), (1550.0, 100.0, 0.0), (1700.0, 300.0, 0.0)], tau=0.5)
    assert rating == pytest.approx(1464.06, abs=0.05) and rd == pytest.approx(151.52, abs=0.05) and vol == pytest.approx(0.05999, abs=0.0001)
    quiet_rating, quiet_rd, _ = lsiap.glicko2_update(1500.0, 200.0, 0.06, [])
    assert quiet_rating == 1500.0 and quiet_rd > 200.0  # a player who did not play becomes less certain


# ---- cost model ---------------------------------------------------------------------------------------------------------------------
def test_the_cost_model_reproduces_the_per_call_and_per_episode_numbers_of_the_research():
    assert costmodel.call_cost() == pytest.approx(0.0244) and costmodel.call_cost(cached=True) == pytest.approx(0.0092)
    base, cached, _, macro, spec, hybrid = costmodel.TIERS
    assert base.episode_cost() == pytest.approx(5.856) and base.cost_per_win() == pytest.approx(48.8) and base.heavy_calls_per_win() == pytest.approx(2000.0)
    assert cached.episode_cost() == pytest.approx(2.208) and macro.episode_cost() == pytest.approx(0.4232)
    assert spec.episode_cost() == pytest.approx(0.8828, abs=1e-4) and hybrid.episode_cost() == pytest.approx(0.0643, abs=1e-4)
    assert hybrid.heavy_calls_per_win() == pytest.approx(6 / 0.81) and hybrid.cost_per_win() < macro.cost_per_win() < cached.cost_per_win() < base.cost_per_win()
    assert costmodel.macro_calls(240, 6, early_stop=0.8) == pytest.approx(240 / 5.2) and costmodel.cache_hit_calls(240, 0.68) == pytest.approx(76.8)
    assert costmodel.table().count("\n") == 7


# ---- receipt ------------------------------------------------------------------------------------------------------------------------
def test_a_receipt_says_what_is_missing_and_hashes_stably(tmp_path):
    full = receipt.Receipt("snake", "glass-1", 3, "none", "muse-spark-1.3", "minimal", "model_skills", "live", skills_sha256="ab" * 32)
    assert receipt.check(full) == [] and full.digest() == full.digest() and len(full.digest()) == 64
    bare = receipt.Receipt("snake", "glass-1", 3, "none", "muse-spark-1.3", "minimal", "model_skills", "live")
    assert any("skills_sha256" in m for m in receipt.check(bare))
    assert "model" in receipt.check(receipt.Receipt("snake", "v", 0, "", "", "minimal", "raw_live", "live"))
    path = tmp_path / "r.json"
    path.write_text("{}", encoding="utf-8")
    assert receipt.file_sha256(path) == receipt.file_sha256(path) and len(receipt.file_sha256(path)) == 64
