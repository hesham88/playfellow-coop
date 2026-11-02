"""AD3: ADK's own evaluator on an evalset our harness exports. The export and the reading of ADK's rows are checked anywhere; one real evaluation runs in the
ADK environment (AD1)."""
import importlib.util

import pytest

from playfellow_coop.adk_app.arena_eval.run import build_evalset, summarize
from playfellow_coop.harness.adk_compat import expected_calls


def test_the_export_has_one_case_per_game_and_seed_with_the_skill_as_the_expected_tool_call():
    data = build_evalset(["snake", "lane_dash"], [0, 1])
    cases = data["eval_cases"]
    assert [c["eval_id"] for c in cases] == ["snake-seed0", "snake-seed1", "lane_dash-seed0", "lane_dash-seed1"]
    assert expected_calls(cases[2]) == [{"name": "start_skill", "args": {"skill": "run_lanes"}}]
    assert cases[0]["conversation"][0]["user_content"]["parts"][0]["text"] == "Play snake, seed 0."


def test_output_file_is_passed_only_when_the_installed_adk_accepts_it(tmp_path):
    from playfellow_coop.adk_app.arena_eval.run import _evaluate_kwargs

    rows = tmp_path / "rows.csv"

    async def old_style(agent_module, eval_dataset_file_path_or_dir, num_runs=2, print_detailed_results=True):
        pass

    async def new_style(agent_module, eval_dataset_file_path_or_dir, num_runs=2, print_detailed_results=True, output_file=None):
        pass

    async def any_style(agent_module, eval_dataset_file_path_or_dir, **kwargs):
        pass

    assert _evaluate_kwargs(old_style, rows) == {}  # google-adk 2.0: no such argument, never pass it
    assert _evaluate_kwargs(new_style, rows) == {"output_file": str(rows)}  # google-adk 2.13: the rows go where we read them
    assert _evaluate_kwargs(any_style, rows) == {"output_file": str(rows)}


def test_adks_rows_are_read_one_per_case_and_metric():
    rows = [{"eval_id": "snake-seed0", "metric_name": "tool_trajectory_avg_score", "score": "1.0", "eval_status": "PASSED", "actual_response": "I won snake."},
            {"eval_id": "snake-seed0", "metric_name": "tool_call_count_v1", "score": "1.0", "eval_status": "INFORMATIONAL", "actual_response": "I won snake."},
            {"eval_id": "snake-seed1", "metric_name": "tool_trajectory_avg_score", "score": "0.0", "eval_status": "FAILED", "actual_response": "I lost snake."}]
    summary = summarize(rows, "random", ["snake"], [0, 1])
    assert summary["cases"] == 2 and summary["matched"] == 1 and summary["games_won"] == 1  # the informational row is not a case
    low, high = summary["share_95"]
    assert low < 0.5 < high and summary["per_case"][1] == {"case": "snake-seed1", "score": 0.0, "status": "FAILED", "answer": "I lost snake."}
    assert summarize([], "own", [], [])["share_95"] is None


def _has_adk() -> bool:
    try:
        return importlib.util.find_spec("google.adk") is not None and importlib.util.find_spec("vertexai") is not None  # the eval extras too
    except ModuleNotFoundError:
        return False


@pytest.mark.skipif(not _has_adk(), reason="ADK lives in its own environment (AD1): run with the python of `tools/adk_env.py --venv <folder>`")
def test_a_missing_engine_raises_instead_of_reporting_a_loss(monkeypatch):
    import playfellow_coop.gym.oracle as oracle

    from playfellow_coop.adk_app.arena_eval.agent import play
    from playfellow_coop.skills.registry import SKILLS

    def no_engine(env, skill, steps):
        raise ModuleNotFoundError("No module named 'practice_arena'")

    monkeypatch.setattr(oracle, "run_oracle", no_engine)
    with pytest.raises(ModuleNotFoundError):
        play("snake", 0, SKILLS["snake"].name)  # a setup failure must never come back as "I lost snake."


@pytest.mark.skipif(not _has_adk(), reason="ADK lives in its own environment (AD1): run with the python of `tools/adk_env.py --venv <folder>`")
@pytest.mark.filterwarnings("ignore:.*EXPERIMENTAL.*:UserWarning")  # ADK announces its evaluator's user simulator as experimental
@pytest.mark.filterwarnings("ignore:The `plugins` argument is deprecated:DeprecationWarning")  # ADK's evaluator passes it to ADK's own runner; nothing else is ignored
def test_adks_evaluator_scores_a_real_case_from_our_export(tmp_path):
    import asyncio
    from google.adk.evaluation.eval_set import EvalSet
    from playfellow_coop.adk_app.arena_eval.run import evaluate
    EvalSet.model_validate(build_evalset(["snake", "box_push"], [0, 1, 2]))  # the whole default shape is a valid ADK evalset
    summary = asyncio.run(evaluate(tmp_path, "own", ["snake"], [0]))
    assert summary["cases"] == 1 and summary["matched"] == 1
    # Newer ADK writes per-case rows (the answers prove the win); older ADK (2.0) writes none, so a win is matched but not answer-proven there.
    assert summary["games_won"] == (1 if (tmp_path / "rows-own.csv").is_file() else 0)
    assert (tmp_path / "arena.evalset.json").is_file() and (tmp_path / "test_config.json").is_file()
