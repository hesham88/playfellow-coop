"""The speed bench: run N turns of the composed loop and write ONE results file in the pf-results/1 shape.

Everything in the file was measured by this run or read from the machine and git. Whatever could not be measured says
"not measured"; no number is typed in. A run from a dirty working tree is labelled a diagnostic."""
from __future__ import annotations

import ctypes
import json
import platform
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Callable

from playfellow_coop.session import play_session
from playfellow_coop.stage_timer import NOT_MEASURED, StageTimer

ROOT = Path(__file__).resolve().parents[1]
SCHEMA = "pf-results/1"


def git_state(repo: Path = ROOT) -> tuple[str, bool]:
    """(commit, dirty) of the repo this bench belongs to, or ("not measured", True) when git cannot say."""
    try:
        commit = subprocess.run(["git", "-C", str(repo), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        status = subprocess.run(["git", "-C", str(repo), "status", "--porcelain"], capture_output=True, text=True, check=True).stdout
        return commit, bool(status.strip())
    except (subprocess.CalledProcessError, OSError):
        return NOT_MEASURED, True


def _ram_gb() -> float | str:
    if sys.platform != "win32":
        return NOT_MEASURED

    class Status(ctypes.Structure):
        _fields_ = [("length", ctypes.c_ulong), ("load", ctypes.c_ulong), ("total", ctypes.c_ulonglong), ("avail", ctypes.c_ulonglong),
                    ("pt", ctypes.c_ulonglong), ("pa", ctypes.c_ulonglong), ("vt", ctypes.c_ulonglong), ("va", ctypes.c_ulonglong),
                    ("ex", ctypes.c_ulonglong)]

    status = Status()
    status.length = ctypes.sizeof(Status)
    try:
        ctypes.windll.kernel32.GlobalMemoryStatusEx(ctypes.byref(status))
    except (AttributeError, OSError):
        return NOT_MEASURED
    return round(status.total / 2**30, 1)


def machine() -> dict:
    """What this PC says about itself. The GPU and the load are not read here, so they say so."""
    return {"cpu": platform.processor() or NOT_MEASURED, "ram_gb": _ram_gb(), "gpu": NOT_MEASURED, "os": platform.platform(),
            "load": NOT_MEASURED}


def run_bench(parts, settings, system: str, turns: int, out_dir, brain_name: str, model: str, handover=None,
              git: tuple[str, bool] | None = None, wait: Callable[[float], bool] | None = None, clock=time.monotonic) -> Path:
    """Run `turns` turns, write <out_dir>/speed_bench-<date>-<commit>.json and a per-turn log beside it. Returns the file."""
    commit, dirty = git or git_state()
    marks = getattr(parts, "marks_source", "off")
    timer = StageTimer()
    started = datetime.now().astimezone()
    begun = clock()
    reason = play_session(parts, settings, system, timer, handover, max_turns=turns, wait=wait)
    seconds = clock() - begun
    out = Path(out_dir)
    out.mkdir(parents=True, exist_ok=True)
    stamp = f"{started:%Y%m%d-%H%M%S}-{commit[:8]}"
    raw = out / f"speed_bench-{stamp}.turns.jsonl"
    raw.write_text("".join(json.dumps(turn) + "\n" for turn in timer.turns), encoding="utf-8")
    result = {
        "schema": SCHEMA, "tool": "speed_bench", "commit": commit, "dirty": dirty, "machine": machine(),
        "brain": brain_name, "model": model, "started": started.isoformat(timespec="seconds"), "seconds": round(seconds, 3),
        "metrics": {"turns": len(timer.turns), "stopped_because": reason, "stages": timer.summary(),
                    "marks": marks,
                    "label": ("diagnostic: FAKE marks, not SAM output" if marks == "fake" else
                              "diagnostic: the working tree had uncommitted changes" if dirty else "clean")},
        "levels": NOT_MEASURED, "raw": raw.name,
    }
    path = out / f"speed_bench-{stamp}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    return path
