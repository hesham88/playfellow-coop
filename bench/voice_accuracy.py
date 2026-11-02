"""Muse Voice accuracy on real recordings: English, Arabic, and both mixed in one sentence (the application: "English/Arabic code-switching").

    python -m bench.voice_accuracy --clips <folder with NN.* clips and RECORD-THESE.md>      # writes results/voice/voice-<date>.json

The clips stay outside the repository (a person's voice); only the scores are published. Each clip NN.* is matched to line NN of
RECORD-THESE.md in the same folder. Any audio format is converted to the WAV Muse Voice wants (mono, 16-bit, 16 kHz) with ffmpeg.

Two scores per clip:
  * word error rate (WER) against the line, after the same clean-up the control words use (case, punctuation, Arabic short vowels);
  * command match: would the right command reach the buddy? A hand-over phrase ("stop", "you take it", "I've got it" and their Arabic)
    must be recognised as exactly that phrase; any other request must keep at least two thirds of its meaningful words.
The second one is the number that matters for play; WER is reported beside it, never instead of it."""
from __future__ import annotations

import argparse
import datetime
import json
import re
import subprocess
import tempfile
from pathlib import Path

from playfellow_coop.control_words import _normal, control_action

STOP_WORDS = {"the", "a", "an", "to", "me", "on", "of", "this", "then", "and", "i", "it", "go", "get",
              "على", "من", "في", "الى", "إلى", "و", "دي", "ده", "اللي", "الـ", "ال", "بعدين"}
OUT = Path(__file__).resolve().parents[1] / "results" / "voice"


def expected_lines(md: Path) -> dict[str, tuple[str, str]]:
    """{"01": (line, group)} from RECORD-THESE.md, group = english | arabic | mixed (from the heading above it)."""
    lines, group = {}, "english"
    for raw in md.read_text(encoding="utf-8").splitlines():
        head = raw.strip().lower()
        if head.startswith("## "):
            group = "mixed" if "mixed" in head else "arabic" if "arabic" in head else "english"
        m = re.match(r"^(\d\d)\.\s+(.+)$", raw.strip())
        if m:
            lines[m.group(1)] = (m.group(2).strip(), group)
    return lines


def words(text: str) -> list[str]:
    return [w.removeprefix("ال") if len(w) > 3 and w.startswith("ال") else w for w in _normal(text).split()]


def wer(ref: str, hyp: str) -> float:
    r, h = words(ref), words(hyp)
    if not r:
        return 0.0 if not h else 1.0
    d = list(range(len(h) + 1))
    for i, rw in enumerate(r, 1):
        prev, d[0] = d[0], i
        for j, hw in enumerate(h, 1):
            cur = min(d[j] + 1, d[j - 1] + 1, prev + (rw != hw))
            prev, d[j] = d[j], cur
    return round(d[len(h)] / len(r), 4)


def command_match(ref: str, hyp: str) -> bool:
    want = control_action(ref)
    if want:
        return control_action(hyp) == want
    if control_action(hyp):  # a request heard as "stop" or a hand-over phrase is the worst mistake
        return False
    content = [w for w in words(ref) if w not in STOP_WORDS]
    heard = set(words(hyp))
    return bool(content) and sum(w in heard for w in content) / len(content) >= 2 / 3


def to_wav(path: Path) -> bytes:
    import imageio_ffmpeg

    with tempfile.TemporaryDirectory() as folder:
        out = Path(folder) / "clip.wav"
        subprocess.run([imageio_ffmpeg.get_ffmpeg_exe(), "-loglevel", "error", "-y", "-i", str(path), "-ac", "1", "-ar", "16000",
                        "-sample_fmt", "s16", str(out)], check=True, timeout=60)
        return out.read_bytes()


def score(rows: list[dict]) -> dict:
    out = {}
    for group in ("english", "arabic", "mixed", "all"):
        rs = [r for r in rows if group == "all" or r["group"] == group]
        if rs:
            out[group] = {"clips": len(rs), "command_match": sum(r["command_ok"] for r in rs),
                          "command_match_rate": round(sum(r["command_ok"] for r in rs) / len(rs), 4),
                          "mean_wer": round(sum(r["wer"] for r in rs) / len(rs), 4)}
    return out


def run(clips: Path, transcriber, lines_md: Path | None = None, convert=None) -> dict:
    """lines_md: the line list (default RECORD-THESE.md beside the clips). Clips may be named 01.m4a or 1.m4a."""
    lines = expected_lines(lines_md if lines_md is not None else clips / "RECORD-THESE.md")
    convert = convert or to_wav
    rows = []
    numbered = [(f"{int(p.stem):02d}", p) for p in clips.iterdir() if re.match(r"^\d{1,2}\.[a-z0-9]+$", p.name, re.I)]
    for number, path in sorted(numbered):
        if number not in lines:
            continue
        line, group = lines[number]
        heard = transcriber.transcribe(convert(path), language="english" if group == "english" else "arabic")
        rows.append({"clip": number, "group": group, "expected": line, "heard": heard, "wer": wer(line, heard),
                     "command_ok": command_match(line, heard)})
    return {"rows": rows, "summary": score(rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--clips", required=True)
    ap.add_argument("--out", default=None)
    ap.add_argument("--lines", default=None, help="the line list, when it is not RECORD-THESE.md beside the clips")
    args = ap.parse_args(argv)
    from playfellow_coop.__main__ import load_muse_key
    from playfellow_coop.voice import MuseVoiceTranscriber

    key = load_muse_key()
    if not key:
        raise SystemExit("needs a Muse key (MODEL_API_KEY)")
    result = run(Path(args.clips), MuseVoiceTranscriber(key), lines_md=Path(args.lines) if args.lines else None)
    result.update({"schema": "pf-voice/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"),
                   "model": "muse-voice-transcribe-1.0", "speaker": "one adult speaker (the project owner), Egyptian Arabic and English",
                   "honesty": "One speaker, about 20 short clips: a first measurement, not a population result. The clips are not published."})
    out = Path(args.out) if args.out else OUT / f"voice-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    for group, s in result["summary"].items():
        print(f"{group:8} command match {s['command_match']}/{s['clips']} ({s['command_match_rate']:.0%})  mean WER {s['mean_wer']:.2f}")
    print("wrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
