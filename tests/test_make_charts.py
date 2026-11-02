"""Tests for tools/make_charts.py: every chart is built from committed results/**/*.json files only,
every chart states whether a model row is 'assisted (skills play, the model picks)' or 'model alone',
non-model runs are labelled 'harness check: scripted chooser, no model' or 'no model (local floor)',
every SVG has a matching PNG copy for the video, the per-game ladder chart shows all 14 games + Assist + 2048
with the oracle ceiling line labelled 'oracle (our skill reading pixels), not the buddy' and unrun rungs marked
'pending', and no chart displays a number that does not trace to a result file."""
from __future__ import annotations

import json
import sys
import xml.etree.ElementTree as ET
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import make_charts  # noqa: E402


def test_make_charts_writes_svg_and_png_pairs_from_committed_results(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    assert len(written) >= 4
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
        first_svg.read_text(encoding="utf-8").replace("</svg>", "<text x='10' y='10'>84.7391%</text></svg>"),
        encoding="utf-8",
    )
    assert "84.7391" in make_charts.unmatched_numbers(tampered, allowed)


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


def test_every_arena_row_names_its_test_set_date_and_result_file(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    arena_text = make_charts.visible_text(written["arena-wins-and-cost"]["svg"])
    assert "glass look, 5 skill games, 29 Oct · muse-skills-20261029.json" in arena_text
    assert "plain look, 5 skill games, 31 Oct · muse-skills-pt1.json" in arena_text
    assert "14-game R1, 2 Nov · muse-sam-20261102.json" in arena_text
    assert "unseen games, 27 Oct" in arena_text
    for fname in (
        "muse-skills-20261029.json",
        "muse-skills-pt1.json",
        "open-skills-20261102.json",
        "muse-skills-20261102.json",
        "muse-sam-20261102.json",
        "scripted-20261029.json",
        "builtin-20261029.json",
        "random-20261029.json",
        "muse-raw-20261027.json",
        "open-raw-20261027.json",
        "builtin-free-20261027.json",
        "random-20261027.json",
    ):
        assert fname in arena_text, fname


def test_cache_chart_states_computed_documented_prices_and_rejects_saved_without_computed(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    cache_svg = written["prompt-cache-savings"]["svg"]
    cache_text = make_charts.visible_text(cache_svg)
    assert "at documented prices, caching would charge $0.8737 instead of $1.1877 (computed); the run's own ledger recorded $1.1877" in cache_text
    assert "price for cached tokens not published" in cache_text
    for stem, paths in written.items():
        assert make_charts.unaccompanied_saved_lines(paths["svg"]) == [], stem
    tampered = tmp_path / "bad_cache.svg"
    tampered.write_text(
        cache_svg.read_text(encoding="utf-8").replace("</svg>", "<text x='10' y='10'>Saved by prompt cache: $0.314</text></svg>"),
        encoding="utf-8",
    )
    assert make_charts.unaccompanied_saved_lines(tampered) != []


def test_per_game_ladder_chart_shows_oracle_ceiling_pending_rungs_r1_assist_and_2048(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    assert "ladder-per-game" in written
    ladder_svg = written["ladder-per-game"]["svg"]
    ladder_text = make_charts.visible_text(ladder_svg)
    assert "oracle: our skill reading pixels" in ladder_text
    assert "engine oracle: reads the game's own state, not pixels" in ladder_text
    assert "pending" in ladder_text
    for game_key in make_charts.ALL_FOURTEEN_GAMES:
        assert game_key in ladder_text, game_key
    assert "65/66" in ladder_text
    assert "4/10" in ladder_text
    assert "20/20" in ladder_text
    assert "4/4" in ladder_text


def test_oracle_file_names_a_source_per_game_pixel_skill_or_engine_state_oracle():
    from playfellow_coop.skills import SKILLS

    doc = json.loads((ROOT / "results" / "fifteen" / "oracle-steps-20261102.json").read_text(encoding="utf-8"))
    for game, entry in doc.items():
        source = entry["source"]
        if entry["skill"]:
            assert game in SKILLS and source.startswith("pixel skill (") and source.endswith(".py)"), (game, source)
            assert (ROOT / "playfellow_coop" / "skills" / source[len("pixel skill ("):-1]).is_file(), source
        else:
            assert source.startswith("engine state oracle (") and "policy_" in source and "pixel" not in source, (game, source)


def test_ladder_ceiling_caption_names_its_source_and_a_game_without_skill_never_carries_the_pixel_caption(tmp_path):
    written = make_charts.build_all(results_dir=ROOT / "results", out_dir=tmp_path)
    doc = json.loads((ROOT / "results" / "fifteen" / "oracle-steps-20261102.json").read_text(encoding="utf-8"))
    lines = make_charts.visible_lines(written["ladder-per-game"]["svg"])
    for game, entry in doc.items():
        game_lines = [ln for ln in lines if ln.startswith(f"{game} ") or ln.startswith(f"{game}\u00a0")]
        assert game_lines, game
        caption = [ln for ln in lines if ln.startswith(f"{game} ceiling:")]
        assert len(caption) == 1, (game, caption)
        if entry["skill"]:
            assert make_charts.PIXEL_ORACLE_CAPTION in caption[0], caption
        else:
            assert make_charts.ENGINE_ORACLE_CAPTION in caption[0] and "pixels" not in caption[0].replace("not pixels", ""), caption
    assert "oracle (our skill reading pixels), not the buddy" not in "\n".join(lines)
    assert make_charts.ceiling_caption({"skill": False}) == make_charts.ENGINE_ORACLE_CAPTION
    assert make_charts.ceiling_caption({"skill": True}) == make_charts.PIXEL_ORACLE_CAPTION
