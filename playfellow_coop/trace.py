"""pf-trace/1: a JSON-lines trace of every request the session makes, for the credit-day trials and the cost report (demo/trace_report.py).

One header line, then one `request` line per call to the planner (stage "plan"), the marker (stage "marks") or the voice service
(stage "voice"), and one `turn` line per turn:

  request  stage, model, prefix_hash (sha256 of the system prompt: the part the provider's cache can hit), images, image_bytes,
           captured_px / sent_px (the picture's size before and after the shrink), tokens {in, cached, out} as the provider reported them,
           audio_ms, latency_ms {encode, request, parse, first_partial}, finish_reason, cost_usd (the budget's own prices), status,
           error (a short key), parse {valid, dropped, actions, boxes}
  turn     the action names, and, when the game can say, won / progress / bumps

Every line (the header too) also says who acted, when the session has an identity (harness H4-25): `who` = {agent, session}, for example
{"agent": "buddy", "session": "a1b2c3d4e5f6"} or a skill's "skill:chase_food". The player is never written, not even as a hash: a trace belongs to one
PC, and the session id leads to the session store, which knows the player.

What can never be in it: a picture, a prompt, a thought, a spoken or typed word, a key, a header, a path, a user name. This is true by
construction: the writer takes only the named fields above, checks the type of each, and keeps the system prompt only as a hash. A value
that does not look right is dropped, never written as it came."""
from __future__ import annotations

import hashlib
import json
import math
import re
import threading
from datetime import datetime
from pathlib import Path

SCHEMA = "pf-trace/1"
STAGES = ("plan", "marks", "voice")
FINISH_REASONS = ("stop", "length", "content_filter", "tool_calls")
TRIAL = re.compile(r"^[A-Za-z0-9._\-]{1,40}$")
MODEL = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._\-/]{0,59}$")
NAME = re.compile(r"^[A-Za-z0-9_]{1,24}$")
ERROR_KEY = re.compile(r"^[a-z_]{1,30}$")
AGENT = re.compile(r"^[a-z][a-z0-9_]{0,23}(:[a-z0-9_.\-]{1,40})?$")  # "buddy", "skill:chase_food": a role, never a person
SESSION = re.compile(r"^[A-Za-z0-9._\-]{1,64}$")
BRAIN_FIELDS = ("model", "images", "image_bytes", "tokens_in", "tokens_cached", "tokens_out", "finish_reason", "cost_usd",
                "encode_ms", "request_ms")  # what a brain may say about its last request; anything else it says is ignored
PARSE_FIELDS = {"valid": bool, "dropped": int, "actions": int, "boxes": int}


def prefix_hash(system: str) -> str:
    """sha256 of the system prompt, the text that is identical on every turn (so a provider's prompt cache can hit it)."""
    return hashlib.sha256(system.encode("utf-8")).hexdigest()


def _count(value) -> int | None:
    return value if isinstance(value, int) and not isinstance(value, bool) and value >= 0 else None


def _number(value) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)) or not math.isfinite(value) or value < 0:
        return None
    return round(float(value), 6)


def _px(value):
    if isinstance(value, (tuple, list)) and len(value) == 2 and all(_count(v) is not None for v in value):
        return [int(value[0]), int(value[1])]
    return None


def _who(value) -> dict | None:
    """{agent, session} from an `Identity` or its `tag()` dict; None when either does not look right. The player is never taken."""
    if isinstance(value, dict):
        agent, session_id = value.get("agent"), value.get("session")
    else:
        agent, session_id = getattr(value, "agent", None), getattr(value, "session", None)
    if isinstance(agent, str) and isinstance(session_id, str) and AGENT.match(agent) and SESSION.match(session_id):
        return {"agent": agent, "session": session_id}
    return None


class Trace:
    """Never overwrites a file (FileExistsError); every line is flushed as it is written."""

    def __init__(self, path, trial: str, commit: str | None = None, who=None):
        if not isinstance(trial, str) or not TRIAL.match(trial):
            raise ValueError("the trial id must be 1 to 40 letters, digits, dots, dashes or underscores")
        self.trial = trial
        self.who = _who(who) if who is not None else None  # who acts on every line unless a call names someone else
        self._file = open(path, "x", encoding="utf-8", newline="\n")  # noqa: SIM115 (closed by close())
        self._lock = threading.Lock()
        self._requests = self._turns = 0
        head = {"type": "header", "schema": SCHEMA, "trial": trial, "started": datetime.now().astimezone().isoformat(timespec="seconds")}
        if isinstance(commit, str) and re.match(r"^[0-9a-f]{7,40}$", commit):
            head["commit"] = commit
        if self.who:
            head["who"] = dict(self.who)
        self._write(head)

    def _tag(self, record: dict, who) -> None:
        """A call's own `who` wins; a bad one is dropped (never replaced by the default, which would name the wrong agent)."""
        tag = _who(who) if who is not None else self.who
        if tag:
            record["who"] = dict(tag)

    def _write(self, record: dict) -> None:
        with self._lock:
            if self._file.closed:
                return
            self._file.write(json.dumps(record, ensure_ascii=False) + "\n")
            self._file.flush()

    def request(self, stage: str, *, model=None, prefix=None, images=None, image_bytes=None, captured_px=None, sent_px=None,
                tokens_in=None, tokens_cached=None, tokens_out=None, audio_ms=None, encode_ms=None, request_ms=None, parse_ms=None,
                first_partial_ms=None, finish_reason=None, cost_usd=None, parse=None, status=None, error=None, who=None) -> None:
        if stage not in STAGES:
            raise ValueError(f"stage must be one of {STAGES}")
        with self._lock:
            self._requests += 1
            number = self._requests
        record: dict = {"type": "request", "trial": self.trial, "n": number, "stage": stage}
        self._tag(record, who)
        if isinstance(model, str) and MODEL.match(model):
            record["model"] = model
        if isinstance(prefix, str):
            record["prefix_hash"] = prefix_hash(prefix)
        for name, value in (("images", images), ("image_bytes", image_bytes)):
            if _count(value) is not None:
                record[name] = value
        for name, value in (("captured_px", captured_px), ("sent_px", sent_px)):
            if _px(value) is not None:
                record[name] = _px(value)
        tokens = {name: _count(value) for name, value in (("in", tokens_in), ("cached", tokens_cached), ("out", tokens_out))}
        if any(v is not None for v in tokens.values()):
            record["tokens"] = tokens
        if _number(audio_ms) is not None:
            record["audio_ms"] = _number(audio_ms)
        latency = {name: _number(value) for name, value in (("encode", encode_ms), ("request", request_ms), ("parse", parse_ms),
                                                            ("first_partial", first_partial_ms))}
        latency = {k: v for k, v in latency.items() if v is not None}
        if latency:
            record["latency_ms"] = latency
        if finish_reason is not None:
            record["finish_reason"] = finish_reason if finish_reason in FINISH_REASONS else "other"
        if _number(cost_usd) is not None:
            record["cost_usd"] = _number(cost_usd)
        if isinstance(parse, dict):
            record["parse"] = {k: parse[k] for k, kind in PARSE_FIELDS.items()
                               if k in parse and isinstance(parse[k], kind) and (kind is bool or (not isinstance(parse[k], bool) and parse[k] >= 0))}
        if _count(status) is not None and 100 <= status <= 599:
            record["status"] = status
        if isinstance(error, str) and ERROR_KEY.match(error):
            record["error"] = error
        self._write(record)

    def turn(self, actions=(), won=None, progress=None, bumps=None, who=None) -> None:
        with self._lock:
            self._turns += 1
            number = self._turns
        record: dict = {"type": "turn", "trial": self.trial, "n": number,
                        "actions": [a for a in actions if isinstance(a, str) and NAME.match(a)]}
        self._tag(record, who)
        if isinstance(won, bool):
            record["won"] = won
        if _number(progress) is not None:
            record["progress"] = _number(progress)
        if _count(bumps) is not None:
            record["bumps"] = bumps
        self._write(record)

    def close(self) -> None:
        with self._lock:
            self._file.close()
