"""The raw session log for the replay recorder (demo/record_replay.py): `--log <path>` writes it, nothing else ever does.

pf-session-log/1 is JSON lines: one header (which brain, which marks, the address the marks were really asked at, whether any address
was not the pinned one, commit, date, web level) and one line per look-think-act turn (the buddy's spoken line, the marks it saw on the
0-1000 grid, the keys it pressed). Only those fields are ever written: no key, no header, no picture, no prompt, no thought, no path,
no user name and none of the player's words (typed or spoken commands never reach this file at all)."""
from __future__ import annotations

import getpass
import json
import re
import socket
import subprocess
import threading
from datetime import date
from pathlib import Path

from playfellow_coop import muse_brain, sam_marks

LOG_SCHEMA = "pf-session-log/1"
PINNED = {"sam": sam_marks.ENDPOINTS["sam"], "muse": muse_brain.ENDPOINTS["muse"]}  # taken when this file loads: later changes show up as fake
MAX_SAY = 140
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,59}$")
COMMIT = re.compile(r"^[0-9a-f]{7,40}$")
PRIVATE_SHAPES = re.compile(
    r"[A-Za-z]:[\\/]|\\|~/|\.\./|(?:^|[\s(\"'])/(?:home|users|etc|var|tmp|mnt|root)\b|@|sk-|AIza|pdl_|https?://|[A-Za-z0-9_\-]{24,}", re.I)
DEFAULT_DIR = "session-logs"  # a bare file name goes here; the folder is git-ignored, so a log is never committed by a tool
HEADER_FIELDS = ("brain", "model", "marks", "marks_endpoint", "fake_server", "commit", "recorded", "level")


def resolve_log_path(name) -> Path:
    """A bare file name goes under ./session-logs/; anything with a folder in it is kept as the user gave it."""
    path = Path(name)
    return Path(DEFAULT_DIR) / path if len(path.parts) == 1 else path


def private_words(extra=()) -> list[str]:
    """Words that must not appear in anything written: the OS user name, the home folder's name, the PC's name (3 letters or more)."""
    words = [*(extra or ()), getpass.getuser(), Path.home().name, socket.gethostname()]
    return [w.lower() for w in words if isinstance(w, str) and len(w.strip()) >= 3]


def clean_line(raw, words: list[str]) -> str:
    """A spoken line, or "" when it holds anything private (a path, an address, a key-like string, a private word): dropped whole, never edited."""
    if not isinstance(raw, str):
        return ""
    text = " ".join(raw.split())
    if PRIVATE_SHAPES.search(text) or any(w in text.lower() for w in words):
        return ""
    return text[:MAX_SAY].rstrip()


def git_commit() -> str | None:
    """The short hash of the code that is running, or None when git cannot say (then the recorder will refuse a real recording)."""
    try:
        done = subprocess.run(["git", "rev-parse", "--short=10", "HEAD"], cwd=Path(__file__).resolve().parents[1], capture_output=True,
                              text=True, timeout=5)
    except (OSError, subprocess.SubprocessError):
        return None
    found = done.stdout.strip()
    return found if done.returncode == 0 and COMMIT.match(found) else None


def make_header(parts, plan: dict) -> dict:
    """What this run really was. fake_server is true whenever the fake marks server is attached or any address is not the pinned one."""
    model, level = plan.get("model"), plan.get("level")
    fake = (bool(getattr(parts, "fake_sam", None)) or sam_marks.ENDPOINTS["sam"] != PINNED["sam"]
            or muse_brain.ENDPOINTS["muse"] != PINNED["muse"])
    header = {"brain": plan.get("brain"), "marks": getattr(parts, "marks_source", "off"), "marks_endpoint": sam_marks.ENDPOINTS["sam"],
              "fake_server": fake, "recorded": date.today().isoformat()}
    if isinstance(model, str) and MODEL.match(model):
        header["model"] = model
    commit = git_commit()
    if commit:
        header["commit"] = commit
    if isinstance(level, str) and MODEL.match(level):
        header["level"] = level
    return header


class SessionLog:
    """An on_event listener that writes the log. Never overwrites a file (FileExistsError); every line is flushed as it is written."""

    def __init__(self, path, header: dict):
        if Path(path).parent.name == DEFAULT_DIR:
            Path(path).parent.mkdir(parents=True, exist_ok=True)  # the default folder is made for you; no other folder is
        self._file = open(path, "x", encoding="utf-8", newline="\n")  # noqa: SIM115 (closed by close())
        self._lock = threading.Lock()
        self._words = private_words()
        self._marks: list[dict] = []
        self._line = ""
        self._write({"type": "header", "schema": LOG_SCHEMA, **{k: header[k] for k in HEADER_FIELDS if k in header}})

    def _write(self, record: dict) -> None:
        self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
        self._file.flush()

    def __call__(self, kind: str, data) -> None:
        with self._lock:
            if self._file.closed:
                return
            if kind == "marks":
                self._marks = [{"tag": str(m["tag"]), "kind": str(m["kind"]), "x": int(m["x"]), "y": int(m["y"])}
                               for m in data if isinstance(m, dict) and {"tag", "kind", "x", "y"} <= set(m)]
            elif kind == "buddy_line":
                self._line = clean_line(data, self._words)
            elif kind == "actions":
                self._write({"type": "turn", "say": self._line, "marks": self._marks, "actions": [str(a) for a in data]})
                self._marks, self._line = [], ""  # nothing carries over into the next turn

    def close(self) -> None:
        with self._lock:
            self._file.close()
