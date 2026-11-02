"""Build empirical benchmark charts (SVG + 1920x1080 PNG copies for the video) strictly from committed results/**/*.json files.

Usage:
    python tools/make_charts.py [--results results] [--out docs/img/charts]

Rules enforced by construction and by tests/test_make_charts.py:
- Reads only committed JSON files under results/ (unless committed_only=False is passed by a test with a synthetic directory).
- Every chart explicitly labels each series as 'assisted (skills play, the model picks)' or 'model alone'.
- Runs from a fake server, scripted chooser, or non-model baseline are labelled 'harness check', never as a model score.
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

_NUM_RE = re.compile(r"(?<![A-Za-z_])[-+]?\d+(?:,\d{3})*(?:\.\d+)?(?![A-Za-z_])")


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
    overall = source.get("overall", source)
    helped = int(overall.get("local_help_episodes") or 0) > 0 or "skills=true" in str(source.get("note") or "").lower()
    base = ASSISTED_LABEL if helped else MODEL_ALONE_LABEL
    if is_harness_check(source):
        return f"{HARNESS_CHECK_LABEL} · {base}"
    return base


def _collect_json_numbers(obj: Any, raw_values: set[float], formatted: set[str]) -> None:
    if isinstance(obj, bool) or obj is None:
        return
    if isinstance(obj, (int, float)):
        val = float(obj)
        raw_values.add(val)
        return
    if isinstance(obj, str):
        for m in _NUM_RE.findall(obj):
            clean = m.replace(",", "")
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
        data = json.loads(path.read_text(encoding="utf-8"))
        _collect_json_numbers(data, raw_values, formatted)
    for val in list(raw_values):
        _add_forms(val, formatted)
    return {s.replace(",", "") for s in formatted}


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


def _build_arena_wins_and_cost(arena_rows: list[tuple[str, dict[str, Any]]], out_dir: Path) -> dict[str, Path]:
    c = Canvas()
    c.rect(48, 36, W - 96, H - 72, BG_1, stroke=LINE, radius=18, stroke_width=2)
    c.text(96, 98, "Arena Win Rate and Spend by Operating Mode", size=38, fill=INK, bold=True)
    c.text(
        96,
        142,
        f"Every row states {ASSISTED_LABEL} or {MODEL_ALONE_LABEL}; non-model runs are marked {HARNESS_CHECK_LABEL}.",
        size=22,
        fill=INK_2,
    )

    ordered: list[tuple[str, dict[str, Any]]] = []
    priority = [
        "muse-skills-20261029.json",
        "muse-raw-20261027.json",
        "open-raw-20261027.json",
        "scripted-20261029.json",
        "builtin-20261029.json",
        "random-20261029.json",
    ]
    by_name = {name: data for name, data in arena_rows}
    for name in priority:
        if name in by_name:
            ordered.append((name, by_name.pop(name)))
    for name in sorted(by_name):
        ordered.append((name, by_name[name]))

    top_y = 200
    row_h = min(132, max(88, (H - 310) // max(1, len(ordered))))
    bar_x = 740
    bar_w = 430
    cost_x = 1470

    c.text(96, top_y - 18, "Model / Brain & Attribution Mode", size=20, fill=INK_2, bold=True)
    c.text(bar_x, top_y - 18, "Episodes Won (Win Share)", size=20, fill=INK_2, bold=True)
    c.text(cost_x, top_y - 18, "Recorded Spend & Token Load", size=20, fill=INK_2, bold=True)
    c.line(88, top_y - 4, W - 88, top_y - 4, LINE, width=1)

    for idx, (filename, data) in enumerate(ordered):
        y = top_y + idx * row_h
        c.rect(84, y + 8, W - 168, row_h - 14, BG_2, stroke=LINE, radius=12, stroke_width=1)
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
        suite = data.get("suite") or ""
        suite_tag = f", {suite}" if suite else ""
        model_title = f"{data.get('model')} ({data.get('brain')}{suite_tag})"
        if harness:
            model_title = f"{model_title} — {HARNESS_CHECK_LABEL}"

        c.text(104, y + 44, model_title, size=22, fill=INK, bold=True)
        c.text(104, y + 78, mode, size=18, fill=accent, bold=True)

        c.rect(bar_x, y + 26, bar_w, 32, BG_0, stroke=LINE, radius=8, stroke_width=1)
        fill_w = max(8 if win_rate > 0 else 0, round(bar_w * win_rate))
        if fill_w > 0:
            c.rect(bar_x, y + 26, fill_w, 32, accent, radius=8)
        c.text(
            bar_x + bar_w + 18,
            y + 50,
            f"{wins} / {episodes} ({win_rate * 100:.1f}%)",
            size=21,
            fill=INK,
            bold=True,
        )
        c.text(
            bar_x,
            y + 82,
            f"Mean progress: {progress * 100:.1f}%   Mean turns: {overall['mean_turns']}",
            size=17,
            fill=INK_2,
        )

        c.text(cost_x, y + 48, f"Spend: ${cost_usd:.4f}", size=22, fill=LIME if cost_usd > 0 and wins > 0 else INK, bold=True)
        usd_per_win = overall.get("usd_per_win")
        sub = f"Per win: ${usd_per_win:.5f}" if isinstance(usd_per_win, (int, float)) and wins > 0 else f"Tokens in: {int(overall['tokens_in']):,}"
        c.text(cost_x, y + 80, sub, size=17, fill=INK_2)

    return c.save(out_dir / "arena-wins-and-cost.svg", out_dir / "arena-wins-and-cost.png")


def _build_prompt_cache_savings(cache_data: dict[str, Any], arena_lookup: dict[str, dict[str, Any]], out_dir: Path) -> dict[str, Path]:
    c = Canvas()
    c.rect(48, 36, W - 96, H - 72, BG_1, stroke=LINE, radius=18, stroke_width=2)
    c.text(96, 98, "Prompt Cache Reuse and Spend Reduction Across Paid Runs", size=38, fill=INK, bold=True)
    c.text(
        96,
        142,
        f"Measured from saved result files ({ASSISTED_LABEL} vs {MODEL_ALONE_LABEL}).",
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
                f"Documented price: ${charged:.6f} charged vs ${without_cache:.6f} uncached",
                size=20,
                fill=INK,
            )
            c.text(
                bar_x,
                y + 180,
                f"Saved by prompt cache: ${saved:.6f}   (budget cap ledger: ${recorded_usd:.6f})",
                size=20,
                fill=LIME,
                bold=True,
            )
        else:
            c.text(
                bar_x,
                y + 156,
                f"Recorded spend in budget ledger: ${recorded_usd:.5f}",
                size=20,
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

    out: dict[str, dict[str, Path]] = {}
    out["arena-wins-and-cost"] = _build_arena_wins_and_cost(arena_rows, out_dir)
    if cache_data is not None:
        out["prompt-cache-savings"] = _build_prompt_cache_savings(cache_data, arena_lookup, out_dir)
    assisted = arena_lookup.get("muse-skills-20261029.json")
    raw = arena_lookup.get("muse-raw-20261027.json")
    if assisted is not None and raw is not None:
        out["assisted-per-game-breakdown"] = _build_per_game_breakdown(assisted, raw, out_dir)
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
