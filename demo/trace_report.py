"""Summarise pf-trace/1 files (written by `python -m playfellow_coop --trace <name>`).

    python demo/trace_report.py <trace.jsonl> [more files] [--json]

It prints, per file: how many requests per stage, the parse-valid share of the planner's answers, tokens in / cached / out and the cache
hit share, latency p50 and p95 per stage (nearest rank, the same rule as the stage timer), the cost in total, per turn and per win, tokens
per win, and whether the system-prompt prefix stayed the same on every request (it must, for the provider's prompt cache to hit).
It only reads: a trace holds numbers and hashes, so there is nothing private to print."""
from __future__ import annotations

import json
import math
import sys
from pathlib import Path

SCHEMA = "pf-trace/1"


class NotATrace(Exception):
    """The file is not a pf-trace/1 file."""


def read(path) -> tuple[dict, list[dict], list[dict]]:
    """(header, requests, turns)."""
    try:
        records = [json.loads(line) for line in Path(path).read_text(encoding="utf-8").splitlines() if line.strip()]
    except (OSError, ValueError):
        raise NotATrace("the file cannot be read as JSON lines") from None
    if not records or not isinstance(records[0], dict) or records[0].get("type") != "header" or records[0].get("schema") != SCHEMA:
        raise NotATrace("the first line is not a pf-trace/1 header")
    header, rest = records[0], [r for r in records[1:] if isinstance(r, dict)]
    return header, [r for r in rest if r.get("type") == "request"], [r for r in rest if r.get("type") == "turn"]


def percentile(values: list[float], fraction: float) -> float | None:
    """Nearest rank: the smallest value that at least `fraction` of the values are at or below."""
    if not values:
        return None
    ordered = sorted(values)
    return ordered[max(0, math.ceil(fraction * len(ordered)) - 1)]


def _share(part: int, whole: int) -> float | None:
    return part / whole if whole else None


def summarize(header: dict, requests: list[dict], turns: list[dict]) -> dict:
    stages: dict[str, int] = {}
    for request in requests:
        stages[request.get("stage", "?")] = stages.get(request.get("stage", "?"), 0) + 1
    errors: dict[str, int] = {}
    for request in requests:
        if request.get("error"):
            errors[request["stage"]] = errors.get(request["stage"], 0) + 1
    plans = [r for r in requests if r.get("stage") == "plan"]
    parsed = [r["parse"] for r in plans if isinstance(r.get("parse"), dict) and "valid" in r["parse"]]
    tokens = [r["tokens"] for r in requests if isinstance(r.get("tokens"), dict)]
    token_in = sum(t["in"] for t in tokens if t.get("in") is not None)
    token_out = sum(t["out"] for t in tokens if t.get("out") is not None)
    reported = [t for t in tokens if t.get("cached") is not None and t.get("in") is not None]
    cached = sum(t["cached"] for t in reported) if reported else None
    hit_share = _share(cached, sum(t["in"] for t in reported)) if reported else None
    latency: dict[str, dict] = {}
    for stage in stages:
        values = [r["latency_ms"]["request"] for r in requests if r.get("stage") == stage and "request" in r.get("latency_ms", {})]
        if values:
            latency[stage] = {"n": len(values), "p50": percentile(values, 0.50), "p95": percentile(values, 0.95)}
    total = sum(r.get("cost_usd", 0.0) for r in requests)
    wins = sum(1 for t in turns if t.get("won") is True)
    prefixes = {r["prefix_hash"] for r in plans if "prefix_hash" in r}
    return {
        "trial": header.get("trial"), "requests": stages, "errors": errors, "turns": len(turns),
        "plan": {"n": len(plans), "parse_valid_share": _share(sum(1 for p in parsed if p["valid"]), len(parsed)),
                 "card_valid_share": _share(sum(1 for p in parsed if p["valid"] and p.get("dropped", 0) == 0), len(parsed)),
                 "dropped_actions": sum(p.get("dropped", 0) for p in parsed)},
        "tokens": {"in": token_in, "cached": cached, "out": token_out, "cache_hit_share": hit_share,
                   "per_win": (token_in + token_out) // wins if wins else None},
        "latency_ms": latency,
        "cost_usd": {"total": total, "per_turn": total / len(turns) if turns else None, "per_win": total / wins if wins else None},
        "wins": wins, "prefix": {"distinct": len(prefixes), "stable": len(prefixes) <= 1},
    }


def _pct(value: float | None) -> str:
    return "not reported" if value is None else f"{value * 100:.1f}%"


def render(s: dict) -> list[str]:
    if not s["requests"]:
        return [f"trial {s['trial']}: no requests in this trace"]
    out = [f"trial {s['trial']}: " + ", ".join(f"{stage} {n}" for stage, n in s["requests"].items()) + f"; {s['turns']} turns"
           + ("; errors: " + ", ".join(f"{k} {v}" for k, v in s["errors"].items()) if s["errors"] else "")]
    plan = s["plan"]
    out.append(f"parse valid: {_pct(plan['parse_valid_share'])} of plan answers; card valid (no dropped action): {_pct(plan['card_valid_share'])}; "
               f"dropped actions: {plan['dropped_actions']}")
    t = s["tokens"]
    cached = "not reported" if t["cached"] is None else str(t["cached"])
    out.append(f"tokens: in {t['in']}, cached {cached}, out {t['out']}; cache hit share: {_pct(t['cache_hit_share'])}")
    for stage, lat in s["latency_ms"].items():
        out.append(f"latency {stage}: p50 {lat['p50']:.0f} ms, p95 {lat['p95']:.0f} ms ({lat['n']} requests)")
    c = s["cost_usd"]
    per_turn = "n/a" if c["per_turn"] is None else f"${c['per_turn']:.5f}"
    out.append(f"cost: total ${c['total']:.5f}; cost per turn {per_turn}")
    if s["wins"]:
        out.append(f"wins: {s['wins']}; cost per win ${c['per_win']:.5f}; tokens per win {t['per_win']}")
    else:
        out.append("wins: no win recorded, so no cost per win")
    out.append("prefix: the same on every plan request (cache-eligible)" if s["prefix"]["stable"]
               else f"prefix: NOT stable ({s['prefix']['distinct']} different system prompts): the provider's cache cannot hit")
    return out


def main(argv: list[str] | None = None) -> int:
    args = list(sys.argv[1:] if argv is None else argv)
    as_json = "--json" in args
    paths = [a for a in args if a != "--json"]
    if not paths:
        print("usage: python demo/trace_report.py <trace.jsonl> [more files] [--json]")
        return 2
    worst = 0
    for path in paths:
        try:
            summary = summarize(*read(path))
        except NotATrace as error:
            print(f"{Path(path).name}: not a pf-trace/1 file ({error})")
            worst = 2
            continue
        print(json.dumps(summary, indent=2) if as_json else "\n".join(render(summary)))
    return worst


if __name__ == "__main__":
    sys.exit(main())
