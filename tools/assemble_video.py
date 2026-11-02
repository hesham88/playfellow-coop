"""Assemble the hackathon demo cut from a YAML shot list using ffmpeg.

Features & rules enforced:
- Refuses any shot or asset path referencing Rayman, Xonotic, or Unvanquished.
- Caps the assembled cut at 3:00 (180.0 seconds).
- Writes separate English (.en.srt) and Arabic (.ar.srt) caption files and muxes
  both as separate subtitle tracks (eng and ara) in the output MP4 container.
"""
from __future__ import annotations

import argparse
import re
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path
from typing import Any

import yaml

MAX_DURATION_SECONDS = 180.0
RESTRICTED_GAMES = ("rayman", "xonotic", "unvanquished")
_RESTRICTED_RE = re.compile(r"(rayman|xonotic|unvanquished)", re.IGNORECASE)
_IMAGE_SUFFIXES = {".png", ".jpg", ".jpeg", ".bmp", ".webp"}


def find_ffmpeg() -> str:
    """Locate an executable ffmpeg binary on PATH or via imageio_ffmpeg."""
    found = shutil.which("ffmpeg")
    if found:
        return found
    try:
        import imageio_ffmpeg

        return imageio_ffmpeg.get_ffmpeg_exe()
    except Exception as exc:  # pragma: no cover
        raise RuntimeError("ffmpeg executable not found on PATH or via imageio_ffmpeg") from exc


def check_restricted_names(spec: Any) -> None:
    """Raise ValueError if any shot path or field names Rayman, Xonotic, or Unvanquished."""
    if isinstance(spec, str):
        m = _RESTRICTED_RE.search(spec)
        if m:
            raise ValueError(f"Refusing restricted game asset ({m.group(1)}): {spec}")
        return
    if isinstance(spec, Path):
        check_restricted_names(str(spec))
        return
    if isinstance(spec, list):
        for item in spec:
            check_restricted_names(item)
        return
    if isinstance(spec, dict):
        for k, v in spec.items():
            check_restricted_names(k)
            check_restricted_names(v)


def cap_shots(shots: list[dict[str, Any]], max_seconds: float = MAX_DURATION_SECONDS) -> list[dict[str, Any]]:
    """Return a copy of shots truncated so total duration never exceeds max_seconds (180.0s)."""
    remaining = float(max_seconds)
    out: list[dict[str, Any]] = []
    for shot in shots:
        if remaining <= 1e-6:
            break
        dur = float(shot.get("duration", 0.0))
        if dur <= 0.0:
            continue
        clamped = min(dur, remaining)
        entry = dict(shot)
        entry["duration"] = round(clamped, 6)
        out.append(entry)
        remaining -= clamped
    return out


def _srt_timestamp(seconds: float) -> str:
    ms_total = max(0, int(round(seconds * 1000.0)))
    hours, rem = divmod(ms_total, 3_600_000)
    minutes, rem = divmod(rem, 60_000)
    secs, ms = divmod(rem, 1000)
    return f"{hours:02d}:{minutes:02d}:{secs:02d},{ms:03d}"


def build_srt(entries: list[dict[str, Any]]) -> str:
    """Render a list of {'start': float, 'end': float, 'text': str} items as SubRip (.srt)."""
    blocks: list[str] = []
    idx = 1
    for item in entries:
        text = str(item.get("text") or "").strip()
        if not text:
            continue
        start = float(item["start"])
        end = float(item["end"])
        if end <= start:
            continue
        blocks.append(f"{idx}\n{_srt_timestamp(start)} --> {_srt_timestamp(end)}\n{text}\n")
        idx += 1
    if not blocks:
        blocks.append("1\n00:00:00,000 --> 00:00:01,000\n \n")
    return "\n".join(blocks)


def _extract_caption_tracks(
    shots: list[dict[str, Any]],
    spec: dict[str, Any],
    max_seconds: float = MAX_DURATION_SECONDS,
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    en_entries: list[dict[str, Any]] = []
    ar_entries: list[dict[str, Any]] = []

    cursor = 0.0
    for shot in shots:
        dur = float(shot["duration"])
        start = cursor
        end = min(max_seconds, cursor + dur)
        cursor = end
        en_text = shot.get("caption_en") or shot.get("en")
        ar_text = shot.get("caption_ar") or shot.get("ar")
        if en_text:
            en_entries.append({"start": start, "end": end, "text": str(en_text)})
        if ar_text:
            ar_entries.append({"start": start, "end": end, "text": str(ar_text)})

    if isinstance(spec.get("captions_en"), list):
        en_entries = [
            {
                "start": float(c["start"]),
                "end": min(max_seconds, float(c["end"])),
                "text": str(c["text"]),
            }
            for c in spec["captions_en"]
            if float(c["start"]) < max_seconds
        ]
    if isinstance(spec.get("captions_ar"), list):
        ar_entries = [
            {
                "start": float(c["start"]),
                "end": min(max_seconds, float(c["end"])),
                "text": str(c["text"]),
            }
            for c in spec["captions_ar"]
            if float(c["start"]) < max_seconds
        ]
    return en_entries, ar_entries


def probe_media(path: Path) -> dict[str, Any]:
    """Inspect duration and stream counts of a media file via ffmpeg -i."""
    ffmpeg = find_ffmpeg()
    proc = subprocess.run([ffmpeg, "-hide_banner", "-i", str(path)], capture_output=True, text=True, encoding="utf-8", errors="replace")
    info = proc.stderr
    m_dur = re.search(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)", info)
    duration = 0.0
    if m_dur:
        duration = int(m_dur.group(1)) * 3600 + int(m_dur.group(2)) * 60 + float(m_dur.group(3))
    video_streams = len(re.findall(r"Stream #\d+:\d+.*?: Video:", info))
    subtitle_streams = len(re.findall(r"Stream #\d+:\d+.*?: Subtitle:", info))
    return {
        "duration": duration,
        "video_streams": video_streams,
        "subtitle_streams": subtitle_streams,
        "raw": info,
    }


def assemble_from_yaml(
    yaml_path: Path,
    out_mp4: Path,
    *,
    max_seconds: float = MAX_DURATION_SECONDS,
) -> dict[str, Any]:
    """Build the cut described in yaml_path and write out_mp4 + .en.srt + .ar.srt."""
    yaml_path = Path(yaml_path).resolve()
    out_mp4 = Path(out_mp4).resolve()
    spec = yaml.safe_load(yaml_path.read_text(encoding="utf-8")) or {}
    check_restricted_names(spec)
    check_restricted_names(out_mp4.name)

    raw_shots = spec.get("shots") or []
    if not raw_shots:
        raise ValueError(f"No shots defined in {yaml_path}")

    limit = min(float(max_seconds), MAX_DURATION_SECONDS)
    shots = cap_shots(raw_shots, max_seconds=limit)
    total_duration = round(sum(float(s["duration"]) for s in shots), 6)

    width = int(spec.get("width", 1920))
    height = int(spec.get("height", 1080))
    fps = int(spec.get("fps", 30))
    base_dir = yaml_path.parent

    en_entries, ar_entries = _extract_caption_tracks(shots, spec, max_seconds=limit)
    en_srt = out_mp4.with_suffix(".en.srt")
    ar_srt = out_mp4.with_suffix(".ar.srt")
    out_mp4.parent.mkdir(parents=True, exist_ok=True)
    en_srt.write_text(build_srt(en_entries), encoding="utf-8", newline="\n")
    ar_srt.write_text(build_srt(ar_entries), encoding="utf-8", newline="\n")

    ffmpeg = find_ffmpeg()
    vf = (
        f"scale={width}:{height}:force_original_aspect_ratio=decrease,"
        f"pad={width}:{height}:(ow-iw)/2:(oh-ih)/2:color=0x04061a,"
        f"fps={fps},format=yuv420p"
    )

    with tempfile.TemporaryDirectory(prefix="pf_assemble_") as tmp_dir:
        tmp = Path(tmp_dir)
        segment_paths: list[Path] = []
        for idx, shot in enumerate(shots):
            raw_path = Path(shot.get("path") or shot.get("file"))
            clip_path = raw_path if raw_path.is_absolute() else (base_dir / raw_path).resolve()
            check_restricted_names(clip_path)
            if not clip_path.is_file():
                raise FileNotFoundError(f"Shot file not found: {clip_path}")

            dur = float(shot["duration"])
            start = float(shot.get("start", 0.0))
            seg_out = tmp / f"seg_{idx:03d}.mp4"
            if clip_path.suffix.lower() in _IMAGE_SUFFIXES:
                cmd = [
                    ffmpeg,
                    "-y",
                    "-loop",
                    "1",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(clip_path),
                    "-vf",
                    vf,
                    "-r",
                    str(fps),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(seg_out),
                ]
            else:
                cmd = [
                    ffmpeg,
                    "-y",
                    "-ss",
                    f"{start:.3f}",
                    "-t",
                    f"{dur:.3f}",
                    "-i",
                    str(clip_path),
                    "-vf",
                    vf,
                    "-r",
                    str(fps),
                    "-an",
                    "-c:v",
                    "libx264",
                    "-preset",
                    "ultrafast",
                    "-pix_fmt",
                    "yuv420p",
                    str(seg_out),
                ]
            subprocess.run(cmd, check=True, capture_output=True)
            segment_paths.append(seg_out)

        concat_txt = tmp / "concat.txt"
        concat_txt.write_text(
            "\n".join(f"file '{p.as_posix()}'" for p in segment_paths) + "\n",
            encoding="utf-8",
            newline="\n",
        )
        mux_cmd = [
            ffmpeg,
            "-y",
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            str(concat_txt),
            "-i",
            str(en_srt),
            "-i",
            str(ar_srt),
            "-map",
            "0:v:0",
            "-map",
            "1:s:0",
            "-map",
            "2:s:0",
            "-c:v",
            "copy",
            "-c:s",
            "mov_text",
            "-metadata:s:s:0",
            "language=eng",
            "-metadata:s:s:0",
            "title=English",
            "-metadata:s:s:1",
            "language=ara",
            "-metadata:s:s:1",
            "title=Arabic",
            "-t",
            f"{min(total_duration, limit):.3f}",
            str(out_mp4),
        ]
        subprocess.run(mux_cmd, check=True, capture_output=True)

    return {
        "video": out_mp4,
        "en_srt": en_srt,
        "ar_srt": ar_srt,
        "duration": min(total_duration, limit),
        "shots": len(shots),
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Assemble an MP4 cut from a YAML shot list with English and Arabic caption tracks.")
    parser.add_argument("shotlist", type=Path, help="Path to YAML shot list")
    parser.add_argument("-o", "--output", type=Path, required=True, help="Output MP4 path")
    args = parser.parse_args(argv)
    res = assemble_from_yaml(args.shotlist, args.output)
    print(f"assembled {res['video']} ({res['duration']:.2f}s, {res['shots']} shots) with {res['en_srt'].name} and {res['ar_srt'].name}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
