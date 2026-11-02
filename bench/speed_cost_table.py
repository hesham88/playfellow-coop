"""The speed and cost table, built only from committed result files ($0, no run of any game).

  python -m bench.speed_cost_table --out results/speed/speed-cost-20261102.json

Every value names its source file. A value no file measures is "not measured", never 0. Stage times pool the per-episode stage summaries (`extra.stages`): the table's p50 is the median of the per-episode p50s, its p90 the median of the per-episode p90s.
"""
from __future__ import annotations

import argparse
import json
import math
import statistics
import subprocess
import sys
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

SCHEMA = "pf-speed-cost/1"
NOT_MEASURED = "not measured"
STAGES = ("capture", "shrink", "mark", "encode", "request", "parse_and_check", "key_down", "skill")


def committed_result_files(root: Path) -> list[Path]:
    """Committed files under results/ (git's own list), so an uncommitted file can never enter the table."""
    try:
        out = subprocess.run(["git", "-C", str(root), "ls-files", "--", "results"],
                             capture_output=True, text=True, timeout=30, check=True).stdout
        files = [root / line.strip() for line in out.splitlines() if line.strip().endswith(".json")]
        if files:
            return sorted(files)
    except (OSError, subprocess.SubprocessError):
        pass
    return sorted((root / "results").rglob("*.json"))


def _load(path: Path) -> dict | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None
    return data if isinstance(data, dict) else None


def stage_table(doc: dict, source: str) -> dict:
    episodes = doc.get("episodes") or []
    table: dict = {}
    for stage in STAGES:
        p50s = [e["extra"]["stages"][stage]["p50"] for e in episodes
                if isinstance((e.get("extra") or {}).get("stages", {}).get(stage), dict)]
        p90s = [e["extra"]["stages"][stage]["p90"] for e in episodes
                if isinstance((e.get("extra") or {}).get("stages", {}).get(stage), dict)]
        table[stage] = ({"p50_s": round(statistics.median(p50s), 6), "p90_s": round(statistics.median(p90s), 6),
                         "episodes_measured": len(p50s), "source": source} if p50s else NOT_MEASURED)
    return table


def rung_of(doc: dict) -> tuple[str, str]:
    honesty = doc.get("honesty") or {}
    if (honesty.get("rung") or {}).get("key"):
        return honesty["rung"]["key"], honesty.get("label") or ""
    brain = doc.get("brain", "")
    skilled = any((e.get("extra") or {}).get("skill_steps", 0) > 0 for e in doc.get("episodes") or [])
    if brain in ("muse", "open"):
        return ("human_skills", "[Assisted: Human Local Skill]") if skilled else ("raw_paused", "[Model Alone]")
    return "local_floor", "[Local floor: no model]"


def per_rung_rows(arena_docs: list[tuple[str, dict]]) -> list[dict]:
    rows = []
    for source, doc in arena_docs:
        if doc.get("void") or (doc.get("honesty") or {}).get("label", "").startswith("[Void"):
            continue  # a void file is not a result and never enters a rung row
        overall = doc.get("overall") or {}
        rung, label = rung_of(doc)
        wins = overall.get("wins") or 0
        tokens_in = overall.get("tokens_in") or 0
        rows.append({"source": source, "brain": doc.get("brain"), "model": doc.get("model"), "rung": rung, "label": label,
                     "episodes": overall.get("episodes"), "wins": wins,
                     "usd_per_win": overall.get("usd_per_win") if wins else "not measured (no wins)",
                     "tokens_per_win": overall.get("tokens_per_win") if wins else "not measured (no wins)",
                     "cache_share": round((overall.get("tokens_cached") or 0) / tokens_in, 4) if tokens_in else NOT_MEASURED})
    return rows


def build_table(root: Path) -> dict:
    files = committed_result_files(root)
    arena: list[tuple[str, dict]] = []
    cache_rows: list[dict] = []
    fastpath: dict = {"public_figure": NOT_MEASURED}
    sources: list[str] = []
    for path in files:
        relative = path.relative_to(root).as_posix()
        doc = _load(path)
        if doc is None:
            continue
        if doc.get("schema") == "pf-arena-run/1":
            arena.append((relative, doc))
            sources.append(relative)
        elif doc.get("schema") == "pf-cache-ratio/1":
            sources.append(relative)
            for row in doc.get("rows") or []:
                cache_rows.append({"source": relative, "file": row.get("file"), "cached_share": row.get("cached_share"),
                                   "cached_share_95": row.get("cached_share_95")})
        elif doc.get("tool") == "fastpath_bench":
            sources.append(relative)
            speeds = [row["speedup_x"] for row in (doc.get("metrics") or {}).get("astar") or [] if "speedup_x" in row]
            if speeds:
                figure = f"{math.floor(min(speeds))}–{math.ceil(max(speeds))}x"
                fastpath = {"public_figure": figure, "measured_speedup_x": speeds, "source": relative,
                            "note": "the public figure brackets the measured medians; it is never a single best run"}
    stages = {source: stage_table(doc, source) for source, doc in arena
              if any(isinstance((e.get("extra") or {}).get("stages"), dict) for e in doc.get("episodes") or [])}
    # Local skill step time against one model call, from the same files that timed both.
    local_vs_model: dict = {"local_skill_ms_per_step": NOT_MEASURED, "model_call_ms": NOT_MEASURED}
    for source, doc in arena:
        per_step = []
        for episode in doc.get("episodes") or []:
            stage = (episode.get("extra") or {}).get("stages", {}).get("skill")
            steps = (episode.get("extra") or {}).get("skill_steps", 0)
            if isinstance(stage, dict) and steps:
                per_step.append(stage["p50"] * 1000.0 / steps)
        if per_step and local_vs_model["local_skill_ms_per_step"] == NOT_MEASURED:
            local_vs_model["local_skill_ms_per_step"] = {"ms": round(statistics.median(per_step), 3), "source": source,
                                                         "note": "skill stage p50 divided by the episode's skill steps, median over episodes"}
        request = stages.get(source, {}).get("request")
        if doc.get("brain") in ("muse", "open") and isinstance(request, dict) and local_vs_model["model_call_ms"] == NOT_MEASURED:
            local_vs_model["model_call_ms"] = {"ms": round(request["p50_s"] * 1000.0, 1), "source": source,
                                               "note": "request stage p50 of the paid run in that file"}
        if local_vs_model["local_skill_ms_per_step"] != NOT_MEASURED and local_vs_model["model_call_ms"] != NOT_MEASURED:
            break
    return {"schema": SCHEMA, "written": datetime.now().astimezone().isoformat(timespec="seconds"),
            "note": "Built only from committed result files; every value names its source. Not measured is said, never zero.",
            "sources": sources, "stages_per_turn": stages, "per_rung": per_rung_rows(arena),
            "cache": cache_rows, "fastpath": fastpath, "local_vs_model": local_vs_model}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=ROOT)
    parser.add_argument("--out", type=Path, default=ROOT / "results" / "speed" / "speed-cost-20261102.json")
    args = parser.parse_args(argv)
    table = build_table(args.root)
    args.out.parent.mkdir(parents=True, exist_ok=True)
    with open(args.out, "w", encoding="utf-8", newline="\n") as handle:
        json.dump(table, handle, indent=1)
    print(f"wrote {args.out}: {len(table['per_rung'])} rung rows, fastpath {table['fastpath'].get('public_figure')}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
