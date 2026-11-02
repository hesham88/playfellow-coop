"""Tests for tools/make_charts.py: every chart is built from committed results/**/*.json files only,
every chart states whether a model row is 'assisted (skills play, the model picks)' or 'model alone',
non-model runs are labelled 'harness check: scripted chooser, no model' or 'no model (local floor)',
every SVG has a matching PNG copy for the video, and no chart displays a number that does not trace to a result file."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

import pytest
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import make_charts  # noqa: E402


def test_make_charts_writes_svg_and_png_pairs_from_committed_results(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    assert len(written) >= 3
    for stem, paths in written.items():
        svg_path, png_path = paths["svg"], paths["png"]
        assert svg_path.is_file() and svg_path.suffix == ".svg"
        assert png_path.is_file() and png_path.suffix == ".png"
        ET.fromstring(svg_path.read_text(encoding="utf-8"))
        with Image.open(png_path) as im:
            assert im.size == (1920, 1080) and im.mode in ("RGB", "RGBA")


def test_every_chart_labels_assisted_or_model_alone(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    for stem, paths in written.items():
        text = make_charts.visible_text(paths["svg"]).lower()
        assert "assisted (skills play, the model picks)" in text or "model alone" in text, stem


def test_every_number_in_every_chart_traces_to_committed_result_files(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    allowed = make_charts.allowed_numbers(ROOT / "results")
    for stem, paths in written.items():
        unmatched = make_charts.unmatched_numbers(paths["svg"], allowed)
        assert unmatched == [], f"{stem} contains numbers not in results/**/*.json: {unmatched}"


def test_number_provenance_check_fails_when_a_chart_shows_an_invented_number(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    allowed = make_charts.allowed_numbers(ROOT / "results")
    first_svg = next(iter(written.values()))["svg"]
    tampered = tmp_path / "tampered.svg"
    tampered.write_text(
        first_svg.read_text(encoding="utf-8").replace("</svg>", "<text x='10' y='10'>84.73%</text></svg>"),
        encoding="utf-8",
    )
    assert "84.73" in make_charts.unmatched_numbers(tampered, allowed)


def test_non_model_rows_use_honesty_ladder_labels_and_never_claim_a_model(tmp_path):
    scripted = json.loads((ROOT / "results" / "glass" / "scripted-20261029.json").read_text(encoding="utf-8"))
    builtin = json.loads((ROOT / "results" / "glass" / "builtin-20261029.json").read_text(encoding="utf-8"))
    rnd = json.loads((ROOT / "results" / "glass" / "random-20261029.json").read_text(encoding="utf-8"))

    assert make_charts.mode_label(scripted) == "harness check: scripted chooser, no model"
    assert make_charts.mode_label(builtin) == "no model (local floor)"
    assert make_charts.mode_label(rnd) == "no model (local floor)"

    for row in (scripted, builtin, rnd, {"brain": "none", "model": "none", "overall": {}}):
        label = make_charts.mode_label(row).lower()
        assert "model" not in label.replace("no model", ""), label

    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    arena_svg = written["arena-wins-and-cost"]["svg"]
    arena_text = make_charts.visible_text(arena_svg).lower()
    assert "harness check: scripted chooser, no model" in arena_text
    assert "no model (local floor)" in arena_text
    for line in make_charts.visible_lines(arena_svg):
        low = line.lower()
        if any(tag in low for tag in ("scripted-chooser", "builtin-nav", "none (random)")):
            assert "model" not in low.replace("no model", ""), line


def test_every_arena_row_names_its_test_set_and_result_file(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    arena_text = make_charts.visible_text(written["arena-wins-and-cost"]["svg"])
    assert "glass look, 5 skill games, 29 Oct" in arena_text
    assert "unseen games, 27 Oct" in arena_text
    for fname in (
        "muse-skills-20261029.json",
        "scripted-20261029.json",
        "builtin-20261029.json",
        "random-20261029.json",
        "muse-raw-20261027.json",
        "open-raw-20261027.json",
        "builtin-free-20261027.json",
        "random-20261027.json",
    ):
        assert fname in arena_text, fname
