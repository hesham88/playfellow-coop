"""INF1: how much of each paid run's prompt the provider served from its cache, and what that was worth, from the saved result files only ($0, no network).

    python tools/cache_ratio.py                                  every result file under results/ (pf-arena-run/1, pf-results/1) that has token counts
    python tools/cache_ratio.py results/unseen/muse-raw-20261027.json --md docs/cache-ratio.md --json results/cache/cache-ratio.json

Per file: episodes, calls, input / cached / output tokens, the cached share of the input (sum of cached over sum of input, with a 95 percent interval from a
paired bootstrap over episodes, seed fixed), the share of calls that came after an episode's first call (only those can reuse that episode's own prefix), and,
for muse-spark rows, the dollars at the documented prices: what the provider charges (cached input $0.15, input $1.25, output $4.25 per million, Standard
mode, dev.meta.ai pricing page) against what our budget recorded (it prices every input token at the full rate, so it never under-counts before the cap).
Every number comes from the files; nothing is estimated.
"""
from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parents[1]
PRICES = {"muse-spark": {"input": 1.25e-6, "cached": 0.15e-6, "output": 4.25e-6}}  # dollars per token, Standard mode (documented)
SCHEMAS = ("pf-arena-run/1", "pf-results/1")  # the arena runner's files and the speed bench's: both carry per-episode token counts


def price_table(model: str | None) -> dict | None:
    """The documented prices for a model id ("muse-spark-1.3" -> the muse-spark row), or None when we have no documented price."""
    for family, table in PRICES.items():
        if model and (model == family or model.startswith(family + "-")):
            return table
    return None


def episodes_with_tokens(data: dict) -> list[dict]:
    return [e for e in data.get("episodes", []) if isinstance(e.get("tokens_in"), int) and isinstance(e.get("tokens_cached"), int) and e.get("calls")]


def bootstrap_share(cached: list[int], prompt: list[int], reps: int = 2000, seed: int = 7) -> tuple[float, float]:
    """95 percent interval of sum(cached) / sum(prompt), resampling whole episodes (a pair stays together)."""
    c, p = np.asarray(cached, dtype=float), np.asarray(prompt, dtype=float)
    rng = np.random.default_rng(seed)
    picks = rng.integers(0, len(c), size=(reps, len(c)))
    shares = c[picks].sum(axis=1) / np.maximum(p[picks].sum(axis=1), 1.0)
    low, high = np.percentile(shares, [2.5, 97.5])
    return round(float(low), 4), round(float(high), 4)


def summarize(path: Path) -> dict | None:
    data = json.loads(Path(path).read_text(encoding="utf-8"))
    if data.get("schema") not in SCHEMAS:
        return None
    eps = episodes_with_tokens(data)
    if not eps:
        return None
    t_in, t_cached, t_out = (sum(e[k] for e in eps) for k in ("tokens_in", "tokens_cached", "tokens_out"))
    if t_in == 0:
        return None  # a brain that sends no prompt (built-in, scripted, random) has nothing a cache could serve
    calls = sum(e["calls"] for e in eps)
    row = {"file": Path(path).relative_to(ROOT).as_posix() if Path(path).is_relative_to(ROOT) else str(path), "condition": data.get("condition"),
           "brain": data.get("brain"), "model": data.get("model"), "episodes": len(eps), "calls": calls,
           "tokens": {"in": t_in, "cached": t_cached, "out": t_out}, "cached_share": round(t_cached / t_in, 4) if t_in else None,
           "cached_share_95": bootstrap_share([e["tokens_cached"] for e in eps], [e["tokens_in"] for e in eps]),
           "calls_after_first": round((calls - len(eps)) / calls, 4), "episodes_with_any_cache_hit": sum(e["tokens_cached"] > 0 for e in eps),
           "recorded_usd": round(sum(float(e.get("cost_usd") or 0.0) for e in eps), 6)}
    table = price_table(data.get("model"))
    if table:
        charged = (t_in - t_cached) * table["input"] + t_cached * table["cached"] + t_out * table["output"]
        no_cache = t_in * table["input"] + t_out * table["output"]
        row["usd_at_documented_prices"] = {"charged": round(charged, 6), "without_cache": round(no_cache, 6), "saved_by_cache": round(no_cache - charged, 6)}
    else:
        row["usd_at_documented_prices"] = None  # no documented price for this model: shares only
    return row


def markdown(rows: list[dict]) -> str:
    lines = ["# Prompt cache: how much each paid run reused (INF1)", "",
             "Measured from the saved result files by `tools/cache_ratio.py` ($0, no network). Cached share = cached input tokens / all input tokens, with a 95 percent "
             "interval from a paired bootstrap over episodes. Dollars at the documented muse-spark Standard prices (cached input $0.15, input $1.25, output $4.25 per "
             "million); no documented price, no dollar figure.", "",
             "| file | brain / model | episodes | calls | calls after an episode's first | input tokens | cached | cached share (95%) | recorded by our budget | at documented prices | saved by the cache |",
             "|---|---|---|---|---|---|---|---|---|---|---|"]
    for r in rows:
        usd = r["usd_at_documented_prices"]
        low, high = r["cached_share_95"]
        lines.append(f"| `{r['file']}` | {r['brain']} / {r['model']} | {r['episodes']} | {r['calls']} | {r['calls_after_first']:.0%} | {r['tokens']['in']:,} | "
                     f"{r['tokens']['cached']:,} | {r['cached_share']:.1%} ({low:.1%} to {high:.1%}) | ${r['recorded_usd']:.4f} | "
                     + (f"${usd['charged']:.4f} | ${usd['saved_by_cache']:.4f} |" if usd else "no documented price | n/a |"))
    lines += ["", "Reading it:",
              "- Only calls after an episode's first one can reuse that episode's prompt prefix; a run of one call per episode can hit the cache only across episodes.",
              "- Our budget prices every input token at the full rate, so its recorded dollars are an upper bound whenever the cache hit (safe for the spending cap, "
              "too high as a cost report); the documented-price column is what the provider's own price list gives for the same tokens.", ""]
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Prompt-cache share of saved paid runs (INF1).")
    parser.add_argument("files", nargs="*", type=Path)
    parser.add_argument("--md", type=Path, default=None)
    parser.add_argument("--json", type=Path, default=None)
    args = parser.parse_args(argv)
    files = args.files or sorted((ROOT / "results").rglob("*.json"))
    rows = [row for row in (summarize(f) for f in files) if row]
    if not rows:
        print("no result file with token counts")
        return 1
    text = markdown(rows)
    print(text)
    if args.md:
        args.md.parent.mkdir(parents=True, exist_ok=True)
        args.md.write_text(text, encoding="utf-8", newline="\n")
    if args.json:
        args.json.parent.mkdir(parents=True, exist_ok=True)
        args.json.write_text(json.dumps({"schema": "pf-cache-ratio/1", "rows": rows}, indent=1), encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    sys.exit(main())
