"""Tests for tools/make_charts.py: every chart is built from committed results/**/*.json files only,
every chart states whether a row is 'assisted (skills play, the model picks)' or 'model alone',
fake/scripted runs are drawn as 'harness check' (never as a model score), every SVG has a matching
PNG copy for the video, and no chart displays a number that does not trace to a result file."""
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


def test_fake_server_and_scripted_results_are_drawn_as_harness_check_never_model_score(tmp_path):
    fake_results = tmp_path / "results"
    (fake_results / "glass").mkdir(parents=True)
    (fake_results / "cache").mkdir(parents=True)
    sample = json.loads((ROOT / "results" / "glass" / "muse-skills-20261029.json").read_text(encoding="utf-8"))
    fake_run = dict(sample, brain="fake", model="fake-server", condition="fake-none", note="fake server pipeline check")
    (fake_results / "glass" / "muse-skills-20261029.json").write_text(json.dumps(sample), encoding="utf-8")
    (fake_results / "glass" / "fake-run.json").write_text(json.dumps(fake_run), encoding="utf-8")
    (fake_results / "glass" / "scripted-20261029.json").write_text(
        (ROOT / "results" / "glass" / "scripted-20261029.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    (fake_results / "unseen").mkdir(parents=True)
    for name in ("muse-raw-20261027.json", "open-raw-20261027.json"):
        (fake_results / "unseen" / name).write_text(
            (ROOT / "results" / "unseen" / name).read_text(encoding="utf-8"), encoding="utf-8"
        )
    (fake_results / "cache" / "cache-ratio-20261030.json").write_text(
        (ROOT / "results" / "cache" / "cache-ratio-20261030.json").read_text(encoding="utf-8"), encoding="utf-8"
    )
    out = tmp_path / "charts"
    written = make_charts.build_all(results_dir=fake_results, out_dir=out, committed_only=False)
    arena_text = make_charts.visible_text(written["arena-wins-and-cost"]["svg"]).lower()
    assert "harness check" in arena_text
    assert "model score" not in arena_text
    for line in make_charts.visible_lines(written["arena-wins-and-cost"]["svg"]):
        low = line.lower()
        if "fake" in low or "scripted" in low:
            assert "harness check" in low, line
        if "muse-spark" in low:
            assert "harness check" not in low, line
