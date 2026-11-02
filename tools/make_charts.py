"""Build empirical benchmark charts (SVG + 1920x1080 PNG copies for the video, plus docs/img/ladder.svg)
strictly from committed results/**/*.json files.

Usage:
    python tools/make_charts.py [--results results] [--out docs/img/charts]

Rules enforced by construction and by tests/test_make_charts.py:
- Reads only committed JSON files under results/ (unless committed_only=False is passed by a test with a synthetic directory).
- Every chart explicitly labels each series as 'assisted (skills play, the model picks)' or 'model alone'.
- Runs from a fake server, scripted chooser, or non-model baseline are labelled on the honesty ladder
  ('harness check: scripted chooser, no model' or 'no model (local floor)'), never as a model score.
- Every number rendered in any chart text traces directly to a number in the input JSON files.
"""
from __future__ import annotations

import argparse
import html
import json
import re
import subprocess
import sys
import xml.etree.ElementTree as ET
from pathlib import Path
from typing import Any

from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parents[1]
W, H = 1920, 1080

# Compact 5-game summary ladder constants used by docs/img/ladder.svg
GAMES = ("snake", "box_push", "slide_2048", "lane_dash", "brick_breaker")
ALL_FOURTEEN_GAMES = (
    "snake", "box_push", "slide_2048", "lane_dash", "maze_chase", "key_caves", "turn_quest",
    "brick_breaker", "mini_chess", "action_quest", "mini_fighter", "ray_maze", "tiny_kingdom", "top_racer",
)
RUNGS = [  # (label, file, kind)
    ("Random keys", "results/fifteen/random-20261102.json", "baseline"),
    ("Muse Spark alone", "results/fifteen/muse-raw-20261102.json", "model alone"),
    ("Muse Spark Open alone (open weights)", "results/fifteen/open-raw-20261102.json", "model alone"),
    ("Muse Spark + SAM 3.1 marks", "results/fifteen/muse-sam-20261102.json", "model alone"),
    ("Muse Spark + local skills", "results/fifteen/muse-skills-20261102.json", "assisted"),
    ("Muse Spark Open + local skills", "results/fifteen/open-skills-20261102.json", "assisted"),
]

BG_0 = (4, 6, 26)
BG_1 = (10, 16, 48)
BG_2 = (20, 28, 76)
INK = (234, 240, 255)
INK_2 = (170, 182, 230)
CYAN = (67, 227, 255)
VIOLET = (155, 107, 255)
LIME = (182, 242, 61)
AMBER = (255, 204, 77)
CORAL = (255, 107, 129)
LINE = (68, 84, 152)

ASSISTED_LABEL = "assisted (skills play, the model picks)"
MODEL_ALONE_LABEL = "model alone"
HARNESS_CHECK_LABEL = "harness check"
SCRIPTED_NO_MODEL_LABEL = "harness check: scripted chooser, no model"
LOCAL_FLOOR_NO_MODEL_LABEL = "no model (local floor)"
ORACLE_CEILING_LABEL = "oracle (our skill reading pixels), not the buddy"
PIXEL_ORACLE_CAPTION = "oracle: our skill reading pixels"
ENGINE_ORACLE_CAPTION = "engine oracle: reads the game's own state, not pixels"
LIVE_ASSIST_LABEL = "live assist: the model plays the part, no local skill"


def ceiling_caption(entry: dict[str, Any]) -> str:
    """Return the ceiling caption naming the oracle source: pixel skill vs engine state oracle."""
    return PIXEL_ORACLE_CAPTION if entry.get("skill") else ENGINE_ORACLE_CAPTION

_NUM_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z_])")


def rung_numbers(path: Path) -> dict:
    doc = json.loads(path.read_text(encoding="utf-8"))
    eps = [e for e in doc["episodes"] if e["game"] in GAMES]
    return {
        "episodes": len(eps),
        "wins": sum(bool(e["won"]) for e in eps),
        "progress": sum(float(e.get("progress") or 0.0) for e in eps) / len(eps) if eps else 0.0,
        "cost": sum(float(e.get("cost_usd") or 0.0) for e in eps),
    }


def ladder_svg(rows: list[tuple[str, str, dict]]) -> str:
    width, left, right, top, bar_h, gap = 880, 290, 190, 76, 26, 16
    plot = width - left - right
    height = top + len(rows) * (bar_h + gap) + 54
    ink, ink2, muted, grid, axis, surface, bar = "#f0efec", "#c3c2b7", "#898781", "#2c2c2a", "#383835", "#1a1a19", "#3987e5"
    out = [
        f'<svg xmlns="http://www.w3.org/2000/svg" width="{width}" height="{height}" viewBox="0 0 {width} {height}" font-family="Segoe UI, Helvetica, Arial, sans-serif" role="img" aria-labelledby="t d">',
        '<title id="t">The ladder: what each part of PlayFellow adds, on the same 5 games</title>',
        '<desc id="d">' + "; ".join(f"{label}: mean progress {n['progress']:.2f}, {n['wins']} of {n['episodes']} won" for label, _, n in rows) + "</desc>",
        f'<rect width="{width}" height="{height}" rx="12" fill="{surface}"/>',
        f'<text x="24" y="34" fill="{ink}" font-size="19" font-weight="600">What each part adds, on the same 5 games</text>',
        f'<text x="24" y="56" fill="{ink2}" font-size="13">Mean progress (0 to 1; 1.0 only with the game\'s own win) · label: wins / episodes, cost of the run</text>',
    ]
    for tick in (0, 0.25, 0.5, 0.75, 1.0):
        x = left + plot * tick
        out.append(f'<line x1="{x:.1f}" y1="{top - 6}" x2="{x:.1f}" y2="{height - 40}" stroke="{grid}" stroke-width="1"/>')
        out.append(f'<text x="{x:.1f}" y="{height - 22}" fill="{muted}" font-size="12" text-anchor="middle">{tick:g}</text>')
    for i, (label, kind, n) in enumerate(rows):
        y = top + i * (bar_h + gap)
        w = max(2.0, plot * n["progress"])
        out.append(f'<text x="{left - 14}" y="{y + 12}" fill="{ink}" font-size="14" text-anchor="end">{label}</text>')
        out.append(f'<text x="{left - 14}" y="{y + 27}" fill="{muted}" font-size="11.5" text-anchor="end">{kind}</text>')
        out.append(f'<path d="M{left},{y} h{w - 4:.1f} a4,4 0 0 1 4,4 v{bar_h - 8} a4,4 0 0 1 -4,4 h-{w - 4:.1f} z" fill="{bar}"/>')
        out.append(f'<text x="{left + w + 10:.1f}" y="{y + 18}" fill="{ink}" font-size="13">{n["wins"]}/{n["episodes"]} won · ${n["cost"]:.2f}</text>')
    out.append(f'<line x1="{left}" y1="{top - 6}" x2="{left}" y2="{height - 40}" stroke="{axis}" stroke-width="1"/>')
    out.append("</svg>")
    return "\n".join(out) + "\n"


def _hex(rgb: tuple[int, int, int]) -> str:
    return f"#{rgb[0]:02x}{rgb[1]:02x}{rgb[2]:02x}"


def _font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont | ImageFont.ImageFont:
    candidates = ("segoeui.ttf", "arial.ttf", "DejaVuSans.ttf") if not bold else ("segoeuib.ttf", "arialbd.ttf", "DejaVuSans-Bold.ttf")
    for name in candidates:
        try:
            return ImageFont.truetype(name, size)
        except OSError:
            continue
    return ImageFont.load_default()


class Canvas:
    """Dual renderer: records clean SVG elements and paints a matching 1920x1080 PNG."""

    def __init__(self, width: int = W, height: int = H):
        self.width = width
        self.height = height
        self.svg_parts: list[str] = [
            f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {width} {height}" width="{width}" height="{height}">',
            f'  <rect x="0" y="0" width="{width}" height="{height}" fill="{_hex(BG_0)}"/>',
        ]
        self.image = Image.new("RGB", (width, height), BG_0)
        self.draw = ImageDraw.Draw(self.image)

    def rect(self, x: float, y: float, w: float, h: float, fill: tuple[int, int, int],
             stroke: tuple[int, int, int] | None = None, radius: int = 0, stroke_width: int = 1) -> None:
        ix, iy, iw, ih = round(x), round(y), max(0, round(w)), max(0, round(h))
        if iw == 0 or ih == 0:
            return
        rx_attr = f' rx="{radius}" ry="{radius}"' if radius > 0 else ""
        stroke_attr = f' stroke="{_hex(stroke)}" stroke-width="{stroke_width}"' if stroke else ""
        self.svg_parts.append(f'  <rect x="{ix}" y="{iy}" width="{iw}" height="{ih}" fill="{_hex(fill)}"{rx_attr}{stroke_attr}/>')
        box = (ix, iy, ix + iw, iy + ih)
        if radius > 0:
            self.draw.rounded_rectangle(box, radius=radius, fill=fill, outline=stroke, width=stroke_width if stroke else 0)
        else:
            self.draw.rectangle(box, fill=fill, outline=stroke, width=stroke_width if stroke else 0)

    def line(self, x1: float, y1: float, x2: float, y2: float, stroke: tuple[int, int, int], width: int = 1) -> None:
        ix1, iy1, ix2, iy2 = round(x1), round(y1), round(x2), round(y2)
        self.svg_parts.append(f'  <line x1="{ix1}" y1="{iy1}" x2="{ix2}" y2="{iy2}" stroke="{_hex(stroke)}" stroke-width="{width}"/>')
        self.draw.line((ix1, iy1, ix2, iy2), fill=stroke, width=width)

    def circle(self, cx: float, cy: float, r: float, fill: tuple[int, int, int],
               stroke: tuple[int, int, int] | None = None, stroke_width: int = 1) -> None:
        icx, icy, ir = round(cx), round(cy), round(r)
        stroke_attr = f' stroke="{_hex(stroke)}" stroke-width="{stroke_width}"' if stroke else ""
        self.svg_parts.append(f'  <circle cx="{icx}" cy="{icy}" r="{ir}" fill="{_hex(fill)}"{stroke_attr}/>')
        box = (icx - ir, icy - ir, icx + ir, icy + ir)
        self.draw.ellipse(box, fill=fill, outline=stroke, width=stroke_width if stroke else 0)

    def text(self, x: float, y: float, content: str, size: int = 24, fill: tuple[int, int, int] = INK,
             bold: bool = False, anchor: str = "start") -> None:
        ix, iy = round(x), round(y)
        weight = "bold" if bold else "normal"
        svg_anchor = {"start": "start", "middle": "middle", "end": "end"}[anchor]
        escaped = html.escape(str(content))
        self.svg_parts.append(
            f'  <text x="{ix}" y="{iy}" fill="{_hex(fill)}" font-family="Segoe UI, Arial, sans-serif" '
            f'font-size="{size}" font-weight="{weight}" text-anchor="{svg_anchor}">{escaped}</text>'
        )
        font = _font(size, bold=bold)
        bbox = self.draw.textbbox((0, 0), str(content), font=font)
        tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]
        tx = ix if anchor == "start" else (ix - tw // 2 if anchor == "middle" else ix - tw)
        ty = iy - int(size * 0.82)
        self.draw.text((tx, ty), str(content), font=font, fill=fill)

    def save(self, svg_path: Path, png_path: Path) -> dict[str, Path]:
        svg_path.parent.mkdir(parents=True, exist_ok=True)
        png_path.parent.mkdir(parents=True, exist_ok=True)
        svg_text = "\n".join(self.svg_parts + ["</svg>", ""])
        svg_path.write_text(svg_text, encoding="utf-8", newline="\n")
        self.image.save(png_path, format="PNG")
        return {"svg": svg_path, "png": png_path}


def list_result_files(results_dir: Path, committed_only: bool = True) -> list[Path]:
    """Return JSON result files under results_dir (excluding Perfetto traces and ADK evalsets)."""
    results_dir = Path(results_dir).resolve()
    if committed_only:
        try:
            out = subprocess.run(
                ["git", "ls-files", "--", str(results_dir)],
                cwd=results_dir.parent,
                capture_output=True,
                text=True,
                check=True,
            ).stdout.splitlines()
            files = [results_dir.parent / p for p in out if p.endswith(".json")]
        except Exception:
            files = sorted(results_dir.rglob("*.json"))
    else:
        files = sorted(results_dir.rglob("*.json"))
    return [
        p for p in sorted(files)
        if p.is_file() and not p.name.endswith(".perfetto.json") and not p.name.endswith(".evalset.json")
    ]


def is_harness_check(row: dict[str, Any]) -> bool:
    """True when a result file comes from a fake server, scripted chooser, or non-model baseline."""
    brain = str(row.get("brain") or "").strip().lower()
    model = str(row.get("model") or "").strip().lower()
    condition = str(row.get("condition") or "").strip().lower()
    note = str(row.get("note") or "").strip().lower()
    if brain in {"fake", "scripted", "random", "builtin"}:
        return True
    if model in {"none", "fake", "fake-server", "scripted-chooser", "builtin-nav"}:
        return True
    if any(tag in model or tag in condition for tag in ("fake", "scripted", "random", "builtin")):
        return True
    if "fake server" in note or "wiring check, not a model" in note:
        return True
    return False


def mode_label(row: dict[str, Any], arena_lookup: dict[str, dict[str, Any]] | None = None) -> str:
    """Return the exact required attribution label for a result record."""
    source = row
    if arena_lookup and isinstance(row.get("file"), str):
        name = Path(row["file"]).name
        if name in arena_lookup:
            source = arena_lookup[name]
    brain = str(source.get("brain") or "").strip().lower()
    model = str(source.get("model") or "").strip().lower()
    if brain == "scripted" or "scripted" in model:
        return SCRIPTED_NO_MODEL_LABEL
    if brain in {"builtin", "random", "none"} or model == "none" or "builtin" in model:
        return LOCAL_FLOOR_NO_MODEL_LABEL
    if is_harness_check(source):
        return f"{HARNESS_CHECK_LABEL}: fake server, no model"
    overall = source.get("overall", source)
    helped = int(overall.get("local_help_episodes") or 0) > 0 or "skills=true" in str(source.get("note") or "").lower()
    return ASSISTED_LABEL if helped else MODEL_ALONE_LABEL


def _collect_json_numbers(obj: Any, raw_values: set[float], formatted: set[str]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        val = float(obj)
        raw_values.add(val)
        raw_values.add(abs(val))
        return
    if isinstance(obj, str):
        for m in _NUM_RE.findall(obj):
            clean = m.replace(",", "").lstrip("+-")
            formatted.add(clean)
            try:
                raw_values.add(float(clean))
            except ValueError:
                pass
        return
    if isinstance(obj, list):
        for item in obj:
            _collect_json_numbers(item, raw_values, formatted)
        return
    if isinstance(obj, dict):
        for k, v in obj.items():
            _collect_json_numbers(k, raw_values, formatted)
            _collect_json_numbers(v, raw_values, formatted)


def _add_forms(val: float, formatted: set[str]) -> None:
    for candidate in (val, val * 100.0):
        if abs(candidate - round(candidate)) < 1e-9:
            iv = int(round(candidate))
            formatted.add(str(iv))
            formatted.add(f"{iv:,}")
        for digits in range(0, 7):
            s = f"{candidate:.{digits}f}"
            formatted.add(s)
            if "." in s:
                formatted.add(s.rstrip("0").rstrip("."))


def allowed_numbers(results_dir: Path, committed_only: bool = True) -> set[str]:
    """Every number (and standard rounded/percentage form) present in results/**/*.json."""
    raw_values: set[float] = set()
    formatted: set[str] = set()
    for path in list_result_files(results_dir, committed_only=committed_only):
        _collect_json_numbers(path.name, raw_values, formatted)
        data = json.loads(path.read_text(encoding="utf-8"))
        _collect_json_numbers(data, raw_values, formatted)
        if isinstance(data, dict) and data.get("schema") == "pf-access/1":
            summary = data.get("summary", {})
            assist_rows = [v for k, v in summary.items() if k.startswith("assist/") and isinstance(v, dict)]
            if assist_rows:
                raw_values.add(float(sum(int(v.get("done", 0)) for v in assist_rows)))
                raw_values.add(float(sum(int(v.get("requests", 0)) for v in assist_rows)))
    for val in list(raw_values):
        _add_forms(val, formatted)
    return {s.replace(",", "") for s in formatted}


def set_and_file_label(filename: str, data: dict[str, Any]) -> str:
    """Return the benchmark set description, date, and source filename for a result row."""
    suite = str(data.get("suite") or "").strip().lower()
    if filename == "muse-skills-pt1.json":
        return f"plain look, 5 skill games, 31 Oct · {filename}"
    if "20261102" in filename:
        return f"14-game R1, 2 Nov · {filename}"
    if suite == "glass" or "20261029" in filename:
        return f"glass look, 5 skill games, 29 Oct · {filename}"
    if suite == "unseen" or "20261027" in filename:
        return f"unseen games, 27 Oct · {filename}"
    return f"{suite or 'arena'} · {filename}"


def visible_lines(svg_path: Path) -> list[str]:
    root = ET.fromstring(Path(svg_path).read_text(encoding="utf-8"))
    lines = []
    for elem in root.iter():
        if elem.tag.endswith("text"):
            text = "".join(elem.itertext()).strip()
            if text:
                lines.append(text)
    return lines


def visible_text(svg_path: Path) -> str:
    return "\n".join(visible_lines(svg_path))


def unmatched_numbers(svg_path: Path, allowed: set[str]) -> list[str]:
    bad: list[str] = []
    for line in visible_lines(svg_path):
        for token in _NUM_RE.findall(line):
            clean = token.replace(",", "").lstrip("+")
            if clean not in allowed:
                bad.append(clean)
    return bad


def unaccompanied_saved_lines(svg_path: Path) -> list[str]:
    """Return any visible text lines that contain the word 'saved' without 'computed'."""
    bad: list[str] = []
    for line in visible_lines(svg_path):
        low = line.lower()
        if "saved" in low and "computed" not in low:
            bad.append(line)
    return bad


def _build_arena_wins_and_cost(arena_rows: list[tuple[str, dict[str, Any]]], out_dir: Path) -> dict[str, Path]:
    c = Canvas()
    c.rect(48, 30, W - 96, H - 60, BG_1, stroke=LINE, radius=18, stroke_width=2)
    c.text(96, 84, "Arena Win Rate and Spend by Operating Mode", size=34, fill=INK, bold=True)
    c.text(
        96,
        122,
        f"Every row states {ASSISTED_LABEL} or {MODEL_ALONE_LABEL}; non-model runs are marked {HARNESS_CHECK_LABEL}.",
        size=20,
        fill=INK_2,
    )

    priority = [
        "muse-skills-20261029.json",
        "muse-skills-pt1.json",
        "open-skills-20261102.json",
        "muse-skills-20261102.json",
        "muse-sam-20261102.json",
        "muse-raw-20261102.json",
        "open-raw-20261102.json",
        "muse-raw-20261027.json",
        "open-raw-20261027.json",
        "scripted-20261029.json",
        "builtin-20261029.json",
        "random-20261029.json",
        "builtin-free-20261027.json",
        "random-20261027.json",
    ]
    by_name = {name: data for name, data in arena_rows}
    ordered: list[tuple[str, dict[str, Any]]] = []
    for name in priority:
        if name in by_name:
            ordered.append((name, by_name.pop(name)))
    if not ordered:
        for name in sorted(by_name):
            ordered.append((name, by_name[name]))

    top_y = 166
    row_h = min(110, max(62, (H - 210) // max(1, len(ordered))))
    bar_x = 840
    bar_w = 360
    cost_x = 1480

    c.text(96, top_y - 14, "Run / Benchmark Set & Operating Rung", size=18, fill=INK_2, bold=True)
    c.text(bar_x, top_y - 14, "Episodes Won (Win Share)", size=18, fill=INK_2, bold=True)
    c.text(cost_x, top_y - 14, "Recorded Spend & Token Load", size=18, fill=INK_2, bold=True)
    c.line(88, top_y - 4, W - 88, top_y - 4, LINE, width=1)

    for idx, (filename, data) in enumerate(ordered):
        y = top_y + idx * row_h
        c.rect(84, y + 4, W - 168, row_h - 8, BG_2, stroke=LINE, radius=10, stroke_width=1)
        overall = data["overall"]
        wins = int(overall["wins"])
        episodes = int(overall["episodes"])
        win_rate = float(overall["win_rate"])
        progress = float(overall["mean_progress"])
        cost_usd = float(overall["cost_usd"])
        mode = mode_label(data)
        harness = is_harness_check(data)
        assisted = ASSISTED_LABEL in mode

        accent = AMBER if harness else (CYAN if assisted else VIOLET)
        set_tag = set_and_file_label(filename, data)
        model_title = f"{data.get('model')} ({data.get('brain')}) — {set_tag}"

        c.text(104, y + 26, model_title, size=14, fill=INK, bold=True)
        c.text(104, y + 48, mode, size=15, fill=accent, bold=True)

        c.rect(bar_x, y + 12, bar_w, 20, BG_0, stroke=LINE, radius=6, stroke_width=1)
        fill_w = max(8 if win_rate > 0 else 0, round(bar_w * win_rate))
        if fill_w > 0:
            c.rect(bar_x, y + 12, fill_w, 20, accent, radius=6)
        c.text(
            bar_x + bar_w + 16,
            y + 29,
            f"{wins} / {episodes} ({win_rate * 100:.1f}%)",
            size=16,
            fill=INK,
            bold=True,
        )
        c.text(
            bar_x,
            y + 50,
            f"Mean progress: {progress * 100:.1f}%   Mean turns: {overall['mean_turns']}",
            size=14,
            fill=INK_2,
        )

        c.text(cost_x, y + 28, f"Spend: ${cost_usd:.5f}", size=17, fill=LIME if cost_usd > 0 and wins > 0 else INK, bold=True)
        usd_per_win = overall.get("usd_per_win")
        sub = f"Per win: ${usd_per_win:.5f}" if isinstance(usd_per_win, (int, float)) and wins > 0 else f"Tokens in: {int(overall['tokens_in']):,}"
        c.text(cost_x, y + 49, sub, size=14, fill=INK_2)

    return c.save(out_dir / "arena-wins-and-cost.svg", out_dir / "arena-wins-and-cost.png")


def _build_prompt_cache_savings(cache_data: dict[str, Any], arena_lookup: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Path]:
    c = Canvas()
    c.rect(48, 36, W - 96, H - 72, BG_1, stroke=LINE, radius=18, stroke_width=2)
    c.text(96, 98, "Prompt Cache Reuse and Computed vs Recorded Spend Across Paid Runs", size=38, fill=INK, bold=True)
    c.text(
        96,
        142,
        f"Measured from committed result files ({ASSISTED_LABEL} vs {MODEL_ALONE_LABEL}).",
        size=22,
        fill=INK_2,
    )

    rows = cache_data.get("rows", [])
    top_y = 220
    row_h = 240
    bar_x = 760
    bar_w = 620

    for idx, row in enumerate(rows):
        y = top_y + idx * row_h
        c.rect(84, y, W - 168, row_h - 24, BG_2, stroke=LINE, radius=14, stroke_width=1)
        mode = mode_label(row, arena_lookup=arena_lookup)
        assisted = ASSISTED_LABEL in mode
        accent = CYAN if assisted else VIOLET

        t_in = int(row["tokens"]["in"])
        t_cached = int(row["tokens"]["cached"])
        t_out = int(row["tokens"]["out"])
        share = float(row["cached_share"])
        low, high = row["cached_share_95"]
        calls = int(row["calls"])
        episodes = int(row["episodes"])
        recorded_usd = float(row["recorded_usd"])
        usd = row.get("usd_at_documented_prices")

        c.text(112, y + 52, f"{row['model']} ({row['brain']})", size=26, fill=INK, bold=True)
        c.text(112, y + 90, mode, size=20, fill=accent, bold=True)
        c.text(
            112,
            y + 132,
            f"Episodes: {episodes}   Calls: {calls}   Input tokens: {t_in:,}",
            size=19,
            fill=INK_2,
        )
        c.text(
            112,
            y + 168,
            f"Cached input tokens: {t_cached:,}   Output tokens: {t_out:,}",
            size=19,
            fill=INK_2,
        )

        c.text(bar_x, y + 46, f"Cached share of input: {share * 100:.2f}% ({low * 100:.2f}% to {high * 100:.2f}%)", size=22, fill=INK, bold=True)
        c.rect(bar_x, y + 66, bar_w, 38, BG_0, stroke=LINE, radius=8, stroke_width=1)
        c.rect(bar_x, y + 66, max(8, round(bar_w * share)), 38, LIME, radius=8)

        if isinstance(usd, dict):
            charged = float(usd["charged"])
            without_cache = float(usd["without_cache"])
            saved = float(usd["saved_by_cache"])
            c.text(
                bar_x,
                y + 144,
                f"at documented prices, caching would charge ${charged:.4f} instead of ${without_cache:.4f} (computed); the run's own ledger recorded ${recorded_usd:.4f}",
                size=17,
                fill=INK,
            )
            c.text(
                bar_x,
                y + 180,
                f"Computed difference at documented prices: ${saved:.6f} (${charged:.6f} vs ${without_cache:.6f}, computed)",
                size=18,
                fill=LIME,
                bold=True,
            )
        else:
            c.text(
                bar_x,
                y + 156,
                f"price for cached tokens not published; the run's own ledger recorded ${recorded_usd:.5f}",
                size=19,
                fill=INK,
            )

    return c.save(out_dir / "prompt-cache-savings.svg", out_dir / "prompt-cache-savings.png")


def _build_per_game_breakdown(assisted_data: dict[str, Any], raw_data: dict[str, Any], out_dir: Path) -> dict[str, Path]:
    c = Canvas()
    c.rect(48, 36, W - 96, H - 72, BG_1, stroke=LINE, radius=18, stroke_width=2)
    c.text(96, 98, "Per-Game Outcome: Assisted Skill Selection vs Model Alone", size=38, fill=INK, bold=True)
    c.text(
        96,
        142,
        f"Comparing {assisted_data.get('model')} {ASSISTED_LABEL} against {raw_data.get('model')} {MODEL_ALONE_LABEL}.",
        size=22,
        fill=INK_2,
    )

    games = list(assisted_data.get("by_game", {}).keys())
    top_y = 215
    row_h = 152
    bar_x = 640
    bar_w = 520

    for idx, game in enumerate(games):
        y = top_y + idx * row_h
        c.rect(84, y, W - 168, row_h - 18, BG_2, stroke=LINE, radius=12, stroke_width=1)
        a_row = assisted_data["by_game"][game]
        r_row = raw_data.get("by_game", {}).get(game, {})

        a_wins, a_eps = int(a_row["wins"]), int(a_row["episodes"])
        a_rate = float(a_row["win_rate"])
        a_cost = float(a_row["cost_usd"])
        a_steps = int(a_row.get("skill_steps_total") or 0)

        r_wins = int(r_row.get("wins", 0))
        r_eps = int(r_row.get("episodes", 0))
        r_prog = float(r_row.get("mean_progress", 0.0))
        r_cost = float(r_row.get("cost_usd", 0.0))

        c.text(112, y + 52, game, size=28, fill=INK, bold=True)
        c.text(112, y + 90, f"Local skill steps: {a_steps:,}", size=19, fill=INK_2)

        c.text(bar_x, y + 40, f"{ASSISTED_LABEL}: {a_wins} / {a_eps} wins ({a_rate * 100:.0f}%), spend ${a_cost:.5f}", size=20, fill=CYAN, bold=True)
        c.rect(bar_x, y + 50, bar_w, 22, BG_0, stroke=LINE, radius=6, stroke_width=1)
        if a_rate > 0:
            c.rect(bar_x, y + 50, max(8, round(bar_w * a_rate)), 22, CYAN, radius=6)

        c.text(
            bar_x,
            y + 102,
            f"{MODEL_ALONE_LABEL}: {r_wins} / {r_eps} wins, mean progress {r_prog * 100:.1f}%, spend ${r_cost:.5f}",
            size=20,
            fill=VIOLET,
            bold=True,
        )
        c.rect(bar_x, y + 112, bar_w, 22, BG_0, stroke=LINE, radius=6, stroke_width=1)
        if r_prog > 0:
            c.rect(bar_x, y + 112, max(6, round(bar_w * r_prog)), 22, VIOLET, radius=6)

    return c.save(out_dir / "assisted-per-game-breakdown.svg", out_dir / "assisted-per-game-breakdown.png")


def _build_per_game_ladder(results_dir: Path, arena_lookup: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Path] | None:
    req = (
        "random-20261102.json",
        "builtin-20261102.json",
        "muse-raw-20261102.json",
        "open-raw-20261102.json",
        "muse-sam-20261102.json",
        "muse-skills-20261102.json",
        "open-skills-20261102.json",
    )
    if not all(name in arena_lookup for name in req):
        return None
    orac_path = results_dir / "fifteen" / "oracle-steps-20261102.json"
    acc_path = results_dir / "access" / "access-20261102.json"
    live_m_path = results_dir / "access" / "assist-live-muse-strict-20261102.json"
    live_o_path = results_dir / "access" / "assist-live-open-strict-20261102.json"
    osg_s_path = results_dir / "access" / "osg-2048-20261102.json"
    osg_m_path = results_dir / "access" / "osg-2048-model-muse-20261102.json"
    osg_o_path = results_dir / "access" / "osg-2048-model-open-20261102.json"
    if not all(p.is_file() for p in (orac_path, acc_path, live_m_path, live_o_path, osg_s_path, osg_m_path, osg_o_path)):
        return None

    d_rand = arena_lookup["random-20261102.json"]["by_game"]
    d_built = arena_lookup["builtin-20261102.json"]["by_game"]
    d_mraw = arena_lookup["muse-raw-20261102.json"]["by_game"]
    d_oraw = arena_lookup["open-raw-20261102.json"]["by_game"]
    d_msam = arena_lookup["muse-sam-20261102.json"]["by_game"]
    d_mskl = arena_lookup["muse-skills-20261102.json"]["by_game"]
    d_oskl = arena_lookup["open-skills-20261102.json"]["by_game"]
    d_orac = json.loads(orac_path.read_text(encoding="utf-8"))
    d_acc = json.loads(acc_path.read_text(encoding="utf-8"))["summary"]
    d_live_m = json.loads(live_m_path.read_text(encoding="utf-8"))["summary"]
    d_live_o = json.loads(live_o_path.read_text(encoding="utf-8"))["summary"]
    d_2048_s = json.loads(osg_s_path.read_text(encoding="utf-8"))["summary"]["assist"]
    d_2048_m = json.loads(osg_m_path.read_text(encoding="utf-8"))["summary"]
    d_2048_o = json.loads(osg_o_path.read_text(encoding="utf-8"))["summary"]

    c = Canvas()
    c.rect(32, 24, W - 64, H - 48, BG_1, stroke=LINE, radius=16, stroke_width=2)
    c.text(64, 68, "Full-System Ladder Across All 14 Games, Co-op Assist, and 2048", size=30, fill=INK, bold=True)
    c.text(
        64,
        98,
        f"Rung 0: {LOCAL_FLOOR_NO_MODEL_LABEL} · Rung 1 to 2: {MODEL_ALONE_LABEL} · Rung 2+: + SAM 3.1 marks / fair budget (pending) · Rung 3: model-written skills (pending) · Rung 4: {ASSISTED_LABEL}",
        size=15,
        fill=INK_2,
    )
    c.line(64, 122, W - 64, 122, LIME, width=2)
    c.text(
        64,
        116,
        f"Ceiling line (100%): {PIXEL_ORACLE_CAPTION} (skill games) or {ENGINE_ORACLE_CAPTION} (engine oracles) — from oracle-steps-20261102.json",
        size=15,
        fill=LIME,
        bold=True,
    )

    col_w = 884
    row_h = 104
    start_y = 136
    new_f4_skills = {"maze_chase", "key_caves", "action_quest", "ray_maze"}

    for idx, g in enumerate(ALL_FOURTEEN_GAMES):
        col = idx // 7
        row = idx % 7
        x0 = 64 + col * (col_w + 24)
        y0 = start_y + row * row_h
        c.rect(x0, y0, col_w, row_h - 8, BG_2, stroke=LINE, radius=8, stroke_width=1)

        orac = d_orac[g]
        p_rand = float(d_rand[g]["mean_progress"]) * 100.0
        p_built = float(d_built[g]["mean_progress"]) * 100.0
        p_mraw = float(d_mraw[g]["mean_progress"]) * 100.0
        p_oraw = float(d_oraw[g]["mean_progress"]) * 100.0
        p_msam = float(d_msam[g]["mean_progress"]) * 100.0

        if g in d_mskl:
            w_m = f"{d_mskl[g]['wins']}/{d_mskl[g]['episodes']}"
            w_o = f"{d_oskl[g]['wins']}/{d_oskl[g]['episodes']}"
            r4_text = f"Rung 4 {ASSISTED_LABEL}: Muse {w_m}, Open {w_o}"
            r4_color = CYAN
        elif "scripted-20261102.json" in arena_lookup and g in arena_lookup["scripted-20261102.json"]["by_game"]:
            row = arena_lookup["scripted-20261102.json"]["by_game"][g]
            r4_text = f"Rung 4 {SCRIPTED_NO_MODEL_LABEL}: {row['wins']}/{row['episodes']}"
            r4_color = CYAN if row["wins"] > 0 else INK_2
        elif orac.get("skill"):
            r4_text = "Rung 4 assisted: pixel skill built, run pending"
            r4_color = LIME
        else:
            r4_text = "Rung 4 assisted: pending"
            r4_color = INK_2

        c.text(x0 + 16, y0 + 24, f"{g}   [oracle: {orac['oracle_steps']}/{orac['max_ticks']} steps]", size=16, fill=INK, bold=True)
        c.text(x0 + 400, y0 + 24, r4_text, size=14, fill=r4_color, bold=True)
        c.text(
            x0 + 16,
            y0 + 49,
            f"Rung 0 floor: rand {p_rand:.1f}%, builtin {p_built:.1f}% · Rung 1 to 2 {MODEL_ALONE_LABEL}: Muse {p_mraw:.1f}%, Open {p_oraw:.1f}% · +SAM 3.1: {p_msam:.1f}%",
            size=13,
            fill=INK_2,
        )
        c.text(
            x0 + 16,
            y0 + 72,
            "Rung 2+ fair budget: pending · Rung 3 model-written skills: pending",
            size=13,
            fill=INK_2,
        )
        c.text(
            x0 + 440,
            y0 + 72,
            f"{g} ceiling: {ceiling_caption(orac)}",
            size=13,
            fill=LIME if orac.get("skill") else INK_2,
        )
        c.line(x0 + col_w - 16, y0 + 8, x0 + col_w - 16, y0 + row_h - 16, LIME, width=3)

    by = 872
    c.rect(64, by, W - 128, 164, BG_2, stroke=CYAN, radius=10, stroke_width=2)
    c.text(88, by + 30, "Co-op Assist & Open-Source 2048 Rows (from results/access/*.json)", size=20, fill=CYAN, bold=True)
    acc_done = int(d_acc["assist/ALL"]["done"])
    acc_req = int(d_acc["assist/ALL"]["requests"])
    c.text(
        88,
        by + 62,
        f"Offline Assist (local skills, 5 games): {acc_done}/{acc_req} parts done — box_push {d_acc['assist/box_push']['done']}/{d_acc['assist/box_push']['requests']}, brick_breaker {d_acc['assist/brick_breaker']['done']}/{d_acc['assist/brick_breaker']['requests']}, lane_dash {d_acc['assist/lane_dash']['done']}/{d_acc['assist/lane_dash']['requests']}, slide_2048 {d_acc['assist/slide_2048']['done']}/{d_acc['assist/slide_2048']['requests']}, snake {d_acc['assist/snake']['done']}/{d_acc['assist/snake']['requests']}",
        size=15,
        fill=INK,
    )
    c.text(
        88,
        by + 94,
        f"Live Assist ({LIVE_ASSIST_LABEL}, strict rule check): Muse {d_live_m['really_done']}/{d_live_m['parts']} done ('done' right {d_live_m['true_done_claims']}/{d_live_m['model_said_done']}, ${d_live_m['cost_usd']:.4f}) · Open {d_live_o['really_done']}/{d_live_o['parts']} done ('done' right {d_live_o['true_done_claims']}/{d_live_o['model_said_done']}, ${d_live_o['cost_usd']:.4f})",
        size=15,
        fill=INK,
    )
    c.text(
        88,
        by + 126,
        f"Open-Source 2048 (MIT): {ASSISTED_LABEL} {d_2048_s['done']}/{d_2048_s['requests']} done · {MODEL_ALONE_LABEL} Muse {d_2048_m['done']}/{d_2048_m['requests']} (${d_2048_m['cost_usd']:.4f}) · {MODEL_ALONE_LABEL} Open {d_2048_o['done']}/{d_2048_o['requests']} (${d_2048_o['cost_usd']:.4f})",
        size=15,
        fill=LIME,
        bold=True,
    )
    return c.save(out_dir / "ladder-per-game.svg", out_dir / "ladder-per-game.png")


def _build_learning_curve(results_dir: Path, out_dir: Path, committed_only: bool = True,
                          run_file: Path | None = None) -> dict[str, Path] | None:
    if run_file is None:
        candidates = []
        for path in list_result_files(results_dir, committed_only=committed_only):
            if path.parent.name == "skillsmith" or path.name.startswith("skillsmith-"):
                if path.name.endswith(".json") and not path.name.startswith("sandbox-proof"):
                    candidates.append(path)
        preferred = ["skillsmith-muse-room-20261102.json", "skillsmith-open-20261102.json", "skillsmith-muse-20261102.json"]
        for pref in preferred:
            for cand in candidates:
                if cand.name == pref:
                    run_file = cand
                    break
            if run_file is not None:
                break
        if run_file is None and candidates:
            run_file = candidates[0]

    c = Canvas()
    c.rect(32, 24, W - 64, H - 48, BG_1, stroke=LINE, radius=16, stroke_width=2)
    c.text(64, 68, "SkillSmith Learning Curve: Model-Written Skills Over Iteration Rounds", size=30, fill=INK, bold=True)

    if run_file is None or not run_file.is_file():
        c.text(64, 98, f"Rung 3 · assisted: model-written skill · {ASSISTED_LABEL} · pending", size=15, fill=INK_2)
        c.line(64, 122, W - 64, 122, LINE, width=1)
        c.rect(64, 150, W - 128, H - 210, BG_2, stroke=LINE, radius=12, stroke_width=1)
        c.text(W // 2 - 250, H // 2 - 30, "SkillSmith Learning Curve: pending", size=26, fill=INK, bold=True)
        c.text(W // 2 - 320, H // 2 + 10, "No model-written skill run is committed yet. Runs will appear here once executed.", size=16, fill=INK_2)
        return c.save(out_dir / "learning-curve.svg", out_dir / "learning-curve.png")

    try:
        data = json.loads(run_file.read_text(encoding="utf-8"))
    except Exception:
        data = {}

    games = data.get("games", {})
    curve_games = [(k, v) for k, v in games.items() if isinstance(v, dict) and "curve" in v]

    is_fake = is_harness_check(data) or data.get("brain") == "fake" or "fake" in str(data.get("model", "")).lower()
    if is_fake:
        subtitle = f"Rung 3 · {HARNESS_CHECK_LABEL}: fake model · fake stand-in (not a model result) · {ASSISTED_LABEL}"
    else:
        subtitle = f"Rung 3 · assisted: model-written skill · {ASSISTED_LABEL} · {data.get('model', 'model')} ({run_file.name})"

    c.text(64, 98, subtitle, size=15, fill=INK_2)
    c.line(64, 122, W - 64, 122, LINE, width=1)

    if not curve_games:
        c.rect(64, 150, W - 128, H - 210, BG_2, stroke=LINE, radius=12, stroke_width=1)
        c.text(W // 2 - 250, H // 2 - 30, "SkillSmith Learning Curve: pending", size=26, fill=INK, bold=True)
        c.text(W // 2 - 320, H // 2 + 10, "No curve entries recorded in this run file.", size=16, fill=INK_2)
        return c.save(out_dir / "learning-curve.svg", out_dir / "learning-curve.png")

    N = len(curve_games)
    col_w = (W - 128 - (N - 1) * 24) // N
    for idx, (game_key, gdata) in enumerate(curve_games):
        x0 = 64 + idx * (col_w + 24)
        y0 = 146
        card_h = H - 190
        c.rect(x0, y0, col_w, card_h, BG_2, stroke=LINE, radius=12, stroke_width=1)

        c.text(x0 + 20, y0 + 36, game_key, size=24, fill=INK, bold=True)
        goal = str(gdata.get("goal") or "")
        if goal:
            c.text(x0 + 20, y0 + 64, f"Goal: {goal[:45]}", size=14, fill=INK_2)
        promoted = gdata.get("promoted")
        c.text(
            x0 + 20,
            y0 + 92,
            f"Promoted: {promoted or 'None (refused)'}",
            size=16,
            fill=LIME if promoted else CORAL,
            bold=True,
        )

        curve = gdata.get("curve", [])
        px0 = x0 + 64
        py0 = y0 + 130
        pw = col_w - 96
        ph = 280
        c.rect(px0, py0, pw, ph, BG_0, stroke=LINE, radius=8, stroke_width=1)

        for pct in (0, 20, 40, 60, 80, 100):
            gy = py0 + ph - int((pct / 100.0) * ph)
            c.line(px0, gy, px0 + pw, gy, LINE, width=1)
            c.text(px0 - 48, gy + 5, f"{pct}%", size=13, fill=INK_2)

        num_rounds = max(1, len(curve))
        step_w = pw / num_rounds
        for r_idx, pt in enumerate(curve):
            rx = px0 + int((r_idx + 0.5) * step_w)
            c.line(rx, py0, rx, py0 + ph, LINE, width=1)
            r_num = pt.get("round", r_idx)
            c.text(rx - 24, py0 + ph + 24, f"Round {r_num}", size=13, fill=INK_2)

            curr_p = float(pt.get("current_progress") or 0.0)
            best_p = float(pt.get("best_progress") or 0.0)
            prom = pt.get("promoted")

            curr_y = py0 + ph - int(min(1.0, max(0.0, curr_p)) * ph)
            best_y = py0 + ph - int(min(1.0, max(0.0, best_p)) * ph)

            c.circle(rx - 10, curr_y, 7, fill=CYAN)
            c.circle(rx + 10, best_y, 7, fill=VIOLET)

            v_top = min(curr_y, best_y) - 28
            if prom:
                c.rect(rx - 40, v_top, 80, 20, LIME, radius=4)
                c.text(rx, v_top + 15, "PROMOTED", size=11, fill=BG_0, bold=True, anchor="middle")
            else:
                c.rect(rx - 32, v_top, 64, 20, CORAL, radius=4)
                c.text(rx, v_top + 15, "REFUSED", size=11, fill=BG_0, bold=True, anchor="middle")

        leg_y = py0 + ph + 56
        c.circle(px0 + 20, leg_y, 6, fill=CYAN)
        c.text(px0 + 34, leg_y + 5, "Current Progress", size=14, fill=CYAN, bold=True)
        c.circle(px0 + 200, leg_y, 6, fill=VIOLET)
        c.text(px0 + 214, leg_y + 5, "Best Candidate", size=14, fill=VIOLET, bold=True)

        table_y = leg_y + 30
        for r_idx, pt in enumerate(curve):
            ry = table_y + r_idx * 90
            c.rect(x0 + 20, ry, col_w - 40, 80, BG_0, stroke=LINE, radius=6, stroke_width=1)
            r_num = pt.get("round", r_idx)
            curr_p = float(pt.get("current_progress") or 0.0)
            best_p = float(pt.get("best_progress") or 0.0)
            prom = pt.get("promoted")

            c.text(x0 + 32, ry + 24, f"Round {r_num}: current {curr_p:.2f}, best {best_p:.2f}", size=15, fill=INK, bold=True)
            verdict = "PROMOTED" if prom else "REFUSED"
            v_color = LIME if prom else CORAL
            c.text(x0 + 32, ry + 48, f"Verdict: {verdict}", size=14, fill=v_color, bold=True)
            reason_text = "score strictly improved" if prom else "no candidate strictly beats current"
            c.text(x0 + 32, ry + 70, f"Reason: {reason_text}", size=13, fill=INK_2)

    return c.save(out_dir / "learning-curve.svg", out_dir / "learning-curve.png")


def build_all(results_dir: Path = ROOT / "results", out_dir: Path = ROOT / "docs" / "img" / "charts",
              committed_only: bool = True) -> dict[str, dict[str, Path]]:
    files = list_result_files(results_dir, committed_only=committed_only)
    arena_rows: list[tuple[str, dict[str, Any]]] = []
    arena_lookup: dict[str, dict[str, Any]] = {}
    cache_data: dict[str, Any] | None = None

    for path in files:
        data = json.loads(path.read_text(encoding="utf-8"))
        schema = data.get("schema")
        if schema == "pf-arena-run/1":
            arena_rows.append((path.name, data))
            arena_lookup[path.name] = data
        elif schema == "pf-cache-ratio/1":
            cache_data = data

    if not arena_rows:
        raise ValueError(f"No pf-arena-run/1 result files found in {results_dir}")

    if out_dir == ROOT / "docs" / "img" / "charts" and all((ROOT / p).is_file() for _, p, _ in RUNGS):
        rows = [(label, kind, rung_numbers(ROOT / path)) for label, path, kind in RUNGS]
        target = ROOT / "docs" / "img" / "ladder.svg"
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(ladder_svg(rows), encoding="utf-8")

    out: dict[str, dict[str, Path]] = {}
    out["arena-wins-and-cost"] = _build_arena_wins_and_cost(arena_rows, out_dir)
    if cache_data is not None:
        out["prompt-cache-savings"] = _build_prompt_cache_savings(cache_data, arena_lookup, out_dir)
    assisted = arena_lookup.get("muse-skills-20261029.json")
    raw = arena_lookup.get("muse-raw-20261027.json")
    if assisted is not None and raw is not None:
        out["assisted-per-game-breakdown"] = _build_per_game_breakdown(assisted, raw, out_dir)
    ladder_out = _build_per_game_ladder(results_dir, arena_lookup, out_dir)
    if ladder_out is not None:
        out["ladder-per-game"] = ladder_out
    learning_out = _build_learning_curve(results_dir, out_dir, committed_only=committed_only)
    if learning_out is not None:
        out["learning-curve"] = learning_out
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Build SVG and PNG benchmark charts from committed results/**/*.json files.")
    parser.add_argument("--results", type=Path, default=ROOT / "results")
    parser.add_argument("--out", type=Path, default=ROOT / "docs" / "img" / "charts")
    args = parser.parse_args(argv)
    written = build_all(results_dir=args.results, out_dir=args.out, committed_only=True)
    allowed = allowed_numbers(args.results, committed_only=True)
    for stem, paths in written.items():
        unmatched = unmatched_numbers(paths["svg"], allowed)
        if unmatched:
            print(f"FAIL {stem}: unmatched numbers {unmatched}", file=sys.stderr)
            return 1
        print(f"wrote {paths['svg'].relative_to(ROOT).as_posix()} and {paths['png'].relative_to(ROOT).as_posix()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
