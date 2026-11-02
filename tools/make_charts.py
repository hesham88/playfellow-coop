"""Draws the README's charts from the result files: no number on a chart is typed by hand.

    python tools/make_charts.py        # writes docs/img/ladder.svg

The ladder: the same 5 games (the ones with a local skill), each rung adding one thing we built. Bars are mean progress (0 to 1, the game's own
progress score; 1.0 only with the game's own win); the label beside each bar gives wins / episodes and the cost. Episodes that ended on a
service error before the model was asked are counted as episodes, not left out."""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
GAMES = ("snake", "box_push", "slide_2048", "lane_dash", "brick_breaker")
RUNGS = [  # (label, file, kind)
    ("Random keys", "results/fifteen/random-20261102.json", "baseline"),
    ("Muse Spark alone", "results/fifteen/muse-raw-20261102.json", "model alone"),
    ("Muse Spark Open alone (open weights)", "results/fifteen/open-raw-20261102.json", "model alone"),
    ("Muse Spark + SAM 3.1 marks", "results/fifteen/muse-sam-20261102.json", "model alone"),
    ("Muse Spark + local skills", "results/fifteen/muse-skills-20261102.json", "assisted"),
    ("Muse Spark Open + local skills", "results/fifteen/open-skills-20261102.json", "assisted"),
]
INK, INK2, MUTED, GRID, AXIS, SURFACE, BAR = "#f0efec", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#1a1a19", "#3987e5"


def rung_numbers(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    eps = [e for e in doc["episodes"] if e["game"] in GAMES]
    return {"episodes": len(eps), "wins": sum(bool(e["won"]) for e in eps),
            "progress": sum(float(e.get("progress") or 0.0) for e in eps) / len(eps) if eps else 0.0,
            "cost": sum(float(e.get("cost_usd") or 0.0) for e in eps)}


def ladder_svg(rows: list[tuple[str, str, dict]]) -> str:
    width, left, right, top, bar_h, gap = 880, 290, 190, 76, 26, 16
    plot = width - left - right
    height = top + len(rows) * (bar_h + gap) + 54
    out = [f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
           '<title id="t">The ladder: what each part of PlayFellow adds, on the same 5 games</title>',
           '<desc id="d">' + "; ".join(f"{label}: mean progress {n['progress']:.2f}, {n['wins']} of {n['episodes']} won" for label, _, n in rows) + "</desc>",
           f'<rect width="{width}" height="{height}" rx="12" fill="{SURFACE}"/>',
           f'<text x="24" y="34" fill="{INK}" font-size="19" font-weight="600">What each part adds, on the same 5 games</text>',
           f'<text x="24" y="56" fill="{INK2}" font-size="13">Mean progress (0 to 1; 1.0 only with the game\'s own win) · label: wins / episodes, cost of the run</text>']
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + plot * tick
        out.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{height - 40}" stroke="{GRID}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{height - 22}" fill="{MUTED}" font-size="12" text-anchor="middle">{tick:g}</text>')
    for i, (label, kind, n) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(2.0, plot * n["progress"])
        out.append(f'<text x="{left - 14}" y="{y + 12}" fill="{INK}" font-size="14" text-anchor="end">{label}</text>')
        out.append(f'<text x="{left - 14}" y="{y + 27}" fill="{MUTED}" font-size="11.5" text-anchor="end">{kind}</text>')
        out.append(f'<path d="M{left},{y} h{w - 4:.1f} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 h-{w - 4:.1f} z" fill="{BAR}"/>')
        out.append(f'<text x="{left + w + 10:.1f}" y="{y + 18}" fill="{INK}" font-size="13">{n["wins"]}/{n["episodes"]} won · ${n["cost"]:.2f}</text>')
    out.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{height - 40}" stroke="{AXIS}" stroke-width="1"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def main() -> int:
    rows = [(label, kind, rung_numbers(ROOT / path)) for label, path, kind in RUNGS]
    target = ROOT / "docs" / "img" / "ladder.svg"
    target.parent.mkdir(parents=True, exist_ok=True)
    target.write_text(ladder_svg(rows), encoding="utf-8")
    for label, kind, n in rows:
        print(f"{label:34} {kind:12} progress {n['progress']:.3f}  wins {n['wins']}/{n['episodes']}  ${n['cost']:.3f}")
    print("wrote", target)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
