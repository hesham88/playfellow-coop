"""Run ADK's own evaluator on an evalset our harness exports (AD3). In the ADK environment (AD1), from the repository folder:

    <adk env>/Scripts/python -m playfellow_coop.adk_app.arena_eval.run --out results/adk
    ... --chooser random          the control: a skill picked among all five must score lower

1. The evalset is written by `harness/adk_compat.py` (our exporter): one case per game and seed, the expected tool call `start_skill` with the game's skill, the
   expected answer "I won <game>.". It is checked against ADK's own `EvalSet` model before anything runs.
2. ADK's `AgentEvaluator` runs `arena_eval/agent.py` on every case with the tool-trajectory criterion (`test_config.json`: tool_trajectory_avg_score 1.0) and
   writes one row per case.
3. We write the summary: per-case scores from ADK's rows, the share that matched, and a Wilson 95 percent interval. Nothing is estimated; no model is called.
brick_breaker is left out by default: its skill needs about twelve minutes of play per win.
"""
from __future__ import annotations

import argparse
import asyncio
import csv
import json
import os
import sys
from datetime import datetime
from pathlib import Path

from playfellow_coop.evalkit.stats import wilson
from playfellow_coop.harness.adk_compat import eval_case, evalset, save_evalset
from playfellow_coop.skills.registry import SKILLS

DEFAULT_GAMES = ("snake", "box_push", "slide_2048", "lane_dash")
AGENT_MODULE = "playfellow_coop.adk_app.arena_eval.agent"


def build_evalset(games, seeds) -> dict:
    cases = [eval_case(f"{game}-seed{seed}", [{"user": f"Play {game}, seed {seed}.", "final": f"I won {game}.",
                                               "tool_uses": [{"name": "start_skill", "args": {"skill": SKILLS[game].name}}]}])
             for game in games for seed in seeds]
    return evalset("arena", "Arena levels played with a local skill", cases, "Exported by playfellow_coop.harness.adk_compat for ADK's own evaluator (AD3).")


def write_inputs(folder: Path, games, seeds) -> Path:
    from google.adk.evaluation.eval_set import EvalSet  # the ADK environment only
    folder.mkdir(parents=True, exist_ok=True)
    data = build_evalset(games, seeds)
    EvalSet.model_validate(data)  # our export must be a valid ADK evalset, or nothing runs
    path = folder / "arena.evalset.json"
    save_evalset(path, data)
    (folder / "test_config.json").write_text(json.dumps({"criteria": {"tool_trajectory_avg_score": 1.0}}, indent=1), encoding="utf-8", newline="\n")
    return path


def read_rows(path: Path) -> list[dict]:
    with open(path, encoding="utf-8", newline="") as handle:
        return list(csv.DictReader(handle))


def summarize(rows: list[dict], chooser: str, games, seeds) -> dict:
    """ADK writes one row per case and metric (`metric_name`, `score`, `eval_status`); the trajectory rows decide, the answers say which games were won."""
    trajectory = [r for r in rows if r.get("metric_name") == "tool_trajectory_avg_score" and r.get("score") not in (None, "")]
    matched = sum(float(r["score"]) >= 1.0 for r in trajectory)
    won = sum(str(r.get("actual_response", "")).startswith("I won") for r in trajectory)
    low, high = wilson(matched, len(trajectory)) if trajectory else (None, None)
    return {"schema": "pf-adk-eval/1", "written": datetime.now().astimezone().isoformat(timespec="seconds"), "evaluator": "google-adk AgentEvaluator",
            "agent": AGENT_MODULE, "chooser": chooser, "criterion": "tool_trajectory_avg_score >= 1.0", "games": list(games), "seeds": list(seeds),
            "cases": len(trajectory), "matched": matched, "share": round(matched / len(trajectory), 4) if trajectory else None,
            "share_95": [round(low, 4), round(high, 4)] if trajectory else None, "games_won": won,
            "per_case": [{"case": r["eval_id"], "score": float(r["score"]), "status": r.get("eval_status"), "answer": r.get("actual_response")} for r in trajectory]}


async def evaluate(folder: Path, chooser: str, games, seeds) -> dict:
    from google.adk.evaluation.agent_evaluator import AgentEvaluator
    os.environ["PF_ADK_CHOOSER"] = chooser
    evalset_path = write_inputs(folder, games, seeds)
    rows_path = folder / f"rows-{chooser}.csv"
    try:
        await AgentEvaluator.evaluate(AGENT_MODULE, str(evalset_path), num_runs=1, print_detailed_results=False, output_file=str(rows_path))
    except AssertionError:
        pass  # ADK raises when a case misses the criterion (its pytest style); the rows still say which, and the control is expected to miss
    return summarize(read_rows(rows_path), chooser, games, seeds)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="ADK's own evaluator on our exported arena evalset (AD3).")
    parser.add_argument("--out", type=Path, required=True)
    parser.add_argument("--chooser", choices=("own", "random"), default="own")
    parser.add_argument("--games", default=",".join(DEFAULT_GAMES))
    parser.add_argument("--seeds", type=int, default=3)
    args = parser.parse_args(argv)
    games = [g for g in args.games.split(",") if g]
    summary = asyncio.run(evaluate(args.out, args.chooser, games, list(range(args.seeds))))
    stamp = datetime.now().strftime("%Y%m%d")
    (args.out / f"arena-eval-{args.chooser}-{stamp}.json").write_text(json.dumps(summary, indent=1), encoding="utf-8", newline="\n")
    print(f"{args.chooser}: {summary['matched']} of {summary['cases']} cases matched the expected tool call (95% {summary['share_95']}); "
          f"{summary['games_won']} games won")
    return 0


if __name__ == "__main__":
    sys.exit(main())
