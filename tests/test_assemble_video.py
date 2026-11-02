"""Tests for tools/assemble_video.py: builds an MP4 cut from a YAML shot list with ffmpeg,
writes and muxes English and Arabic captions as separate tracks, refuses Rayman, Xonotic,
or Unvanquished files, and caps the video at 3:00 (180 seconds)."""
from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest
import yaml
from PIL import Image

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from tools import assemble_video  # noqa: E402


def _make_test_clip(path: Path, duration: float = 1.0, color: tuple[int, int, int] = (20, 40, 90)) -> Path:
    """Create a tiny valid MP4 clip using ffmpeg for fast unit tests."""
    ffmpeg = assemble_video.find_ffmpeg()
    r, g, b = color
    hex_color = f"0x{r:02x}{g:02x}{b:02x}"
    cmd = [
        ffmpeg,
        "-y",
        "-f",
        "lavfi",
        "-i",
        f"color=c={hex_color}:s=320x180:r=30:d={duration}",
        "-c:v",
        "libx264",
        "-pix_fmt",
        "yuv420p",
        str(path),
    ]
    subprocess.run(cmd, check=True, capture_output=True)
    return path


@pytest.mark.parametrize(
    "bad_name",
    [
        "rayman_legends_clip.mp4",
        "clips/Rayman-intro.mp4",
        "arena/xonotic_capture.mp4",
        "Xonotic-match.mp4",
        "unvanquished_stage.mp4",
        "footage/Unvanquished/shot1.mp4",
    ],
)
def test_refuses_rayman_xonotic_and_unvanquished_files(tmp_path, bad_name):
    shotlist = {
        "shots": [
            {
                "path": bad_name,
                "duration": 4.0,
                "caption_en": "Opening scene",
                "caption_ar": "المشهد الافتتاحي",
            }
        ]
    }
    yaml_path = tmp_path / "shots.yaml"
    yaml_path.write_text(yaml.safe_dump(shotlist, allow_unicode=True), encoding="utf-8")
    with pytest.raises(ValueError, match=r"(?i)rayman|xonotic|unvanquished"):
        assemble_video.assemble_from_yaml(yaml_path, tmp_path / "out.mp4")


def test_caps_video_duration_at_three_minutes(tmp_path):
    shots = [
        {"path": "clip_a.mp4", "start": 0.0, "duration": 100.0, "caption_en": "Part one", "caption_ar": "الجزء الأول"},
        {"path": "clip_b.mp4", "start": 0.0, "duration": 110.0, "caption_en": "Part two", "caption_ar": "الجزء الثاني"},
        {"path": "clip_c.mp4", "start": 0.0, "duration": 30.0, "caption_en": "Part three", "caption_ar": "الجزء الثالث"},
    ]
    capped = assemble_video.cap_shots(shots, max_seconds=assemble_video.MAX_DURATION_SECONDS)
    total = sum(float(s["duration"]) for s in capped)
    assert total == pytest.approx(180.0)
    assert len(capped) == 2
    assert capped[1]["duration"] == pytest.approx(80.0)


def test_builds_cut_from_yaml_with_separate_english_and_arabic_caption_tracks(tmp_path):
    clip1 = _make_test_clip(tmp_path / "shot1.mp4", duration=1.5, color=(12, 24, 68))
    clip2 = _make_test_clip(tmp_path / "shot2.mp4", duration=1.5, color=(40, 80, 140))
    still = tmp_path / "chart.png"
    Image.new("RGB", (320, 180), (20, 30, 70)).save(still)

    shotlist = {
        "width": 320,
        "height": 180,
        "fps": 30,
        "shots": [
            {
                "path": str(clip1),
                "start": 0.0,
                "duration": 1.0,
                "caption_en": "Shared control in the Practice Arena.",
                "caption_ar": "تحكم مشترك في ساحة التدريب.",
            },
            {
                "path": str(clip2),
                "start": 0.0,
                "duration": 1.0,
                "caption_en": "Press F9 to hand control back and forth.",
                "caption_ar": "اضغط F9 لتبادل التحكم فوراً.",
            },
            {
                "path": str(still),
                "duration": 1.0,
                "caption_en": "Every number comes from a committed result file.",
                "caption_ar": "كل رقم مستمد من ملفات النتائج المعتمدة.",
            },
        ],
    }
    yaml_path = tmp_path / "shotlist.yaml"
    yaml_path.write_text(yaml.safe_dump(shotlist, allow_unicode=True), encoding="utf-8")

    out_mp4 = tmp_path / "cut.mp4"
    result = assemble_video.assemble_from_yaml(yaml_path, out_mp4)

    assert out_mp4.is_file() and out_mp4.stat().st_size > 0
    assert result["en_srt"].is_file()
    assert result["ar_srt"].is_file()
    assert "Shared control" in result["en_srt"].read_text(encoding="utf-8")
    assert "تحكم مشترك" in result["ar_srt"].read_text(encoding="utf-8")
    assert result["duration"] <= assemble_video.MAX_DURATION_SECONDS
    assert result["duration"] == pytest.approx(3.0, abs=0.25)

    probe = assemble_video.probe_media(out_mp4)
    assert probe["duration"] <= assemble_video.MAX_DURATION_SECONDS
    assert probe["subtitle_streams"] >= 2
