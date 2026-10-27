"""Turn a pf-trace/1 file into a Chrome-trace JSON that Perfetto (Google, Apache-2.0, github.com/google/perfetto) opens: slices for each request and its encode, wait
and parse parts on one track per stage, counters for tokens and cost, and an instant mark for each turn.

The trace holds counted facts only (no pictures, prompts, words or keys), so what this writes holds none either. The file records how long each part took but not
the wall-clock moment, so requests are laid end to end in the order they were made: positions show order and duration, not the time of day (the metadata says so).
Open the result at ui.perfetto.dev (Open trace file) or in the admin panel's Traces page. Nothing is uploaded by this module.
"""
from __future__ import annotations

import json
from pathlib import Path

SCHEMA = "pf-trace/1"
PID = 1
TRACKS = {"plan": 1, "marks": 2, "voice": 3, "turns": 4}
PARTS = (("encode", "encode"), ("request", "wait for the service"), ("parse", "parse"))


class TraceFileError(ValueError):
    """The file is not a pf-trace/1 file."""


def read_trace(path: str | Path) -> list[dict]:
    lines = [ln for ln in Path(path).read_text(encoding="utf-8").splitlines() if ln.strip()]
    try:
        records = [json.loads(ln) for ln in lines]
    except ValueError as error:
        raise TraceFileError("a line is not JSON") from error
    if not records or records[0].get("schema") != SCHEMA:
        raise TraceFileError(f"not a {SCHEMA} file")
    return records


def _us(ms) -> int:
    return int(round(float(ms) * 1000)) if isinstance(ms, (int, float)) and not isinstance(ms, bool) and ms >= 0 else 0


def to_events(records: list[dict]) -> dict:
    header = records[0]
    events = [{"ph": "M", "pid": PID, "name": "process_name", "args": {"name": f"Playfellow trial {header.get('trial', '')}"}}]
    for name, tid in TRACKS.items():
        events.append({"ph": "M", "pid": PID, "tid": tid, "name": "thread_name", "args": {"name": name}})
    clock = {tid: 0 for tid in TRACKS.values()}
    cursor = 0
    tokens_in = tokens_out = tokens_cached = 0
    cost = 0.0
    for record in records[1:]:
        kind = record.get("type")
        if kind == "request":
            stage = record.get("stage") if record.get("stage") in TRACKS else "plan"
            tid = TRACKS[stage]
            latency = record.get("latency_ms") or {}
            parts = [(label, _us(latency.get(key))) for key, label in PARTS if _us(latency.get(key)) > 0]
            total = sum(d for _, d in parts) or _us(record.get("audio_ms")) or 1000
            start = max(cursor, clock[tid])
            args = {k: record[k] for k in ("model", "status", "finish_reason", "error", "tokens", "cost_usd", "parse", "images", "image_bytes") if k in record}
            events.append({"ph": "X", "pid": PID, "tid": tid, "ts": start, "dur": total, "name": f"{stage} #{record.get('n', '')}", "cat": stage, "args": args})
            at = start
            for label, duration in parts:
                events.append({"ph": "X", "pid": PID, "tid": tid, "ts": at, "dur": duration, "name": label, "cat": stage})
                at += duration
            clock[tid] = cursor = start + total
            tokens = record.get("tokens") or {}
            tokens_in += tokens.get("in") or 0
            tokens_out += tokens.get("out") or 0
            tokens_cached += tokens.get("cached") or 0
            cost += record.get("cost_usd") or 0.0
            events.append({"ph": "C", "pid": PID, "ts": cursor, "name": "tokens", "args": {"in": tokens_in, "cached": tokens_cached, "out": tokens_out}})
            events.append({"ph": "C", "pid": PID, "ts": cursor, "name": "cost_usd", "args": {"total": round(cost, 6)}})
        elif kind == "turn":
            events.append({"ph": "i", "s": "t", "pid": PID, "tid": TRACKS["turns"], "ts": cursor, "name": f"turn {record.get('n', '')}", "cat": "turn",
                           "args": {k: record[k] for k in ("actions", "won", "progress", "bumps") if k in record}})
    return {"traceEvents": events, "displayTimeUnit": "ms",
            "metadata": {"source": SCHEMA, "trial": header.get("trial"), "started": header.get("started"),
                         "timeline": "requests are laid end to end in the order they were made: positions show order and duration, not the time of day"}}


def convert(src: str | Path, dest: str | Path) -> int:
    """Write the Chrome-trace file; never overwrites. Returns the number of events."""
    document = to_events(read_trace(src))
    with open(dest, "x", encoding="utf-8", newline="\n") as handle:
        json.dump(document, handle, ensure_ascii=False)
    return len(document["traceEvents"])
