"""Turn a real run's session log into the web page's recording (demo/web/replay.mjs, schema pf-replay/1).

    python demo/record_replay.py <session.jsonl> [--out demo/web/replay.mjs] [--sample]

The log is `pf-session-log/1`, JSON lines. The first line is the header:
    {"type": "header", "schema": "pf-session-log/1", "brain": "muse" | "local-open" | "builtin" | "fake" | ..., "model": "...",
     "marks": "sam" | "fake" | "off", "marks_endpoint": "<the address the marks were asked at>", "fake_server": false,
     "commit": "<git hash>", "recorded": "YYYY-MM-DD", "level": "<web level id>"}
and every later "turn" line is one look-think-act turn:
    {"type": "turn", "say": "...", "marks": [{"tag": "R1", "kind": "reward", "x": 0-1000, "y": 0-1000}], "actions": ["up"]}

Honesty rule (fail closed): the recording is written as kind "real" ONLY when the header proves a real brain (muse, or local-open) with
real SAM marks asked at the pinned address and no fake server; anything else is refused, or, with --sample, written as kind "sample"
(a scripted fixture the page labels as NOT AI). A real run is never relabelled a sample, and a fake run is never written as real.

Privacy: only the fields named above are ever read from the log; anything else in it (prompts, thoughts, images, paths, keys, headers)
is never copied. A spoken line that holds a path, an e-mail address, a key-like string or a private word is dropped whole."""
from __future__ import annotations

import getpass
import json
import math
import os
import re
import socket
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
try:  # the engine is normally pip-installed; without that, use PLAYFELLOW_ENGINE or the clone beside this repo
    import practice_arena  # noqa: F401
except ImportError:
    engine = Path(os.environ.get("PLAYFELLOW_ENGINE") or Path(__file__).resolve().parents[2] / "playfellow" / "software")
    sys.path.insert(0, str(engine))

from playfellow_coop import sam_marks  # noqa: E402

WEB = Path(__file__).resolve().parent / "web"
DEFAULT_OUT = WEB / "replay.mjs"
PINNED_MARKS_ENDPOINT = sam_marks.ENDPOINTS["sam"]  # taken when this file loads: nothing at run time can move it
MARKS_FROM = sam_marks.MODEL
LOG_SCHEMA, SCHEMA = "pf-session-log/1", "pf-replay/1"
REAL_BRAINS = ("muse", "local-open")
MARK_KINDS = ("me", "reward", "hazard", "door")
MAX_STEPS, MAX_MARKS, MAX_ACTIONS, MAX_SAY, MAX_TAG = 2000, 32, 8, 140, 6

MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,59}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
DAY = re.compile(r"^\d{4}-\d{2}-\d{2}$")
TAG = re.compile(r"[^A-Za-z0-9]")
PRIVATE_SHAPES = re.compile(
    r"[A-Za-z]:[\\/]|\\|~/|\.\./|(?:^|[\s(\"'])/(?:home|users|etc|var|tmp|mnt|root)\b|@|sk-|AIza|pdl_|https?://|[A-Za-z0-9_\-]{24,}", re.I)


class Refused(Exception):
    """The log cannot be turned into an honest recording; the message says why."""


def _card() -> tuple[str, ...]:
    """The keys the web page accepts, read from the page's own session module (one source of truth)."""
    found = re.search(r"CARD\s*=\s*\[([^\]]*)\]", (WEB / "session.mjs").read_text(encoding="utf-8"))
    if not found:
        raise Refused("cannot read the controls card from demo/web/session.mjs")
    return tuple(re.findall(r"'([a-z0-9_]+)'", found.group(1)))


def _levels() -> list[str]:
    data = json.loads((WEB / "levels.json").read_text(encoding="utf-8"))
    return [level["id"] for level in data["levels"]]


def _private_words(extra) -> list[str]:
    words = [*(extra or ()), getpass.getuser(), Path.home().name, socket.gethostname()]
    return [w.lower() for w in words if isinstance(w, str) and len(w.strip()) >= 3]


def read_log(path) -> tuple[dict, list[dict]]:
    """(header, turns) from a session log; Refused when it cannot be read or has no header."""
    try:
        text = Path(path).read_text(encoding="utf-8")
        lines = [json.loads(line) for line in text.splitlines() if line.strip()]
    except (OSError, ValueError) as error:
        raise Refused(f"the session log cannot be read: {type(error).__name__}") from None
    if not lines or not isinstance(lines[0], dict) or lines[0].get("type") != "header":
        raise Refused("the session log has no header line")
    return lines[0], [line for line in lines[1:] if isinstance(line, dict) and line.get("type") == "turn"]


def _why_not_real(head: dict) -> str | None:
    """None when the header proves a real run; otherwise the first thing it fails to prove."""
    if head.get("brain") not in REAL_BRAINS:
        return f"the brain is {head.get('brain')!r}, not a real one (muse or local-open)"
    if head.get("marks") != "sam":
        return f"the marks are {head.get('marks')!r}, not SAM"
    if head.get("marks_endpoint") != PINNED_MARKS_ENDPOINT:
        return "the marks were not asked at the pinned address"
    if head.get("fake_server") is not False:
        return "the log does not say, as a plain false, that no fake server was used"
    model = head.get("model")
    if not isinstance(model, str) or not MODEL.match(model):
        return "the model name is missing or not a plain model id"
    if not isinstance(head.get("commit"), str) or not COMMIT.match(head["commit"]):
        return "the commit is missing or not a git hash"
    recorded = head.get("recorded")
    if not isinstance(recorded, str) or not DAY.match(recorded):
        return "the recording date is missing or not YYYY-MM-DD"
    try:
        date.fromisoformat(recorded)
    except ValueError:
        return "the recording date is not a real date"
    return None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value):
        return None
    return float(value)


def _marks(raw) -> list[dict]:
    kept = []
    for mark in raw if isinstance(raw, list) else []:
        if not isinstance(mark, dict) or mark.get("kind") not in MARK_KINDS or not isinstance(mark.get("tag"), str):
            continue
        tag, x, y = TAG.sub("", mark["tag"])[:MAX_TAG], _number(mark.get("x")), _number(mark.get("y"))
        if not tag or x is None or y is None:
            continue
        kept.append({"tag": tag, "kind": mark["kind"], "x": min(1000, max(0, round(x))), "y": min(1000, max(0, round(y)))})
    return kept[:MAX_MARKS]


def _say(raw, words: list[str]) -> str:
    if not isinstance(raw, str):
        return ""
    text = " ".join(raw.split())
    if PRIVATE_SHAPES.search(text) or any(w in text.lower() for w in words):
        return ""  # a line with anything private in it is dropped whole, never edited
    return text[:MAX_SAY].rstrip()


def _actions(raw, card: tuple[str, ...], number: int) -> list[str]:
    if not isinstance(raw, list) or len(raw) > MAX_ACTIONS or not all(isinstance(a, str) for a in raw):
        raise Refused(f"turn {number}: actions must be a list of at most {MAX_ACTIONS} key names")
    names = [a.lower() for a in raw]
    off = [a for a in names if a not in card]
    if off:
        raise Refused(f"turn {number}: a key that is not on the controls card ({len(off)} of them)")
    return names


def build(parsed, kind: str | None = None, private_words=None) -> dict:
    """The pf-replay/1 recording for a parsed log. `kind` None = whatever the log proves, but only "real" or refuse;
    "sample" = the scripted fixture label, allowed only for a log that is NOT a real run; "real" = refuse unless proven."""
    head, turns = parsed
    if head.get("schema") != LOG_SCHEMA:
        raise Refused("the log's schema is not pf-session-log/1")
    if head.get("level") not in _levels():
        raise Refused("the log's level is not a level of the web page")
    why = _why_not_real(head)
    if kind == "sample":
        if why is None:
            raise Refused("this log is a real run: it cannot be written as a sample (the label must match what it was)")
        source = {"kind": "sample"}
    else:
        if why is not None:
            raise Refused(f"not written as a real recording: {why}")
        brain = head["model"] if head["brain"] == "muse" else f"local-open:{head['model']}"
        if any(w in brain.lower() for w in _private_words(private_words)):
            raise Refused("the model name holds a private word")
        source = {"kind": "real", "brain": brain, "commit": head["commit"], "recorded": head["recorded"], "marks_from": MARKS_FROM}
    if not 1 <= len(turns) <= MAX_STEPS:
        raise Refused(f"the log has {len(turns)} turns; a recording needs 1 to {MAX_STEPS}")
    card, words = _card(), _private_words(private_words)
    steps = [{"say": _say(t.get("say"), words), "marks": _marks(t.get("marks")), "actions": _actions(t.get("actions"), card, i + 1)}
             for i, t in enumerate(turns)]
    return {"schema": SCHEMA, "source": source, "level": head["level"], "steps": steps}


def module_text(recording: dict) -> str:
    kind = "a RECORDED REAL session" if recording["source"]["kind"] == "real" else "a SAMPLE (scripted, NOT an AI model)"
    return (f"// Written by demo/record_replay.py from a session log (pf-session-log/1): {kind}. Do not edit by hand.\n"
            f"export default {json.dumps(recording, indent=1, ensure_ascii=False)};\n")


def record(log, out, sample: bool = False, private_words=None) -> dict:
    """Read the log, build the recording, write it whole (never half a file). Refused leaves `out` untouched."""
    out = Path(out)
    if sample and out.resolve() == DEFAULT_OUT.resolve():
        raise Refused("a sample must not be written to the page's own recording file")
    recording = build(read_log(log), kind="sample" if sample else None, private_words=private_words)
    temporary = out.with_name(out.name + ".tmp")
    try:
        out.parent.mkdir(parents=True, exist_ok=True)
        temporary.write_text(module_text(recording), encoding="utf-8", newline="\n")
        os.replace(temporary, out)
    finally:
        temporary.unlink(missing_ok=True)
    return recording


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(description="Turn a real session log into the web page's recording.")
    parser.add_argument("log", type=Path)
    parser.add_argument("--out", type=Path, default=DEFAULT_OUT)
    parser.add_argument("--sample", action="store_true", help="write a scripted fixture (kind sample) from a NON-real run; never to the page's own file")
    args = parser.parse_args(argv)
    try:
        recording = record(args.log, args.out, sample=args.sample)
    except Refused as error:
        print(f"Refused: {error}")
        return 2
    print(f"Wrote {len(recording['steps'])} steps ({recording['source']['kind']}) to {args.out.name}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
