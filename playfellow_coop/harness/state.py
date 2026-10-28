"""Context and memory, part one: the session (the transcript) and its state (the scratchpad).

The session is the list of what happened, in order: messages, tool calls, tool results, state changes. The state is a small key-value scratchpad the code reads
directly (the current level, the last skill, how many tries) without searching the transcript. A key's prefix says how long it lives, like ADK's:

  (none)  this session       user:  this player, every session       app:  everything on this PC       temp:  this turn only (never saved)

State changes only through events (`append(..., delta=...)`), never by editing the dict: that is what makes a saved session load back exactly. Private
details are masked before an event is kept or saved.
"""
from __future__ import annotations

import json
import re
import threading
import uuid
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from playfellow_coop.harness.security import redact

MAX_TEXT = 500
MAX_KEYS = 200
MAX_EVENTS_IN_MEMORY = 500
KINDS = ("message", "tool_call", "tool_result", "skill", "state", "note")
KEY = re.compile(r"^(?:(?:user|app|temp):)?[a-z][a-z0-9_.]{0,47}$")


def _clean(value):
    if isinstance(value, str):
        return redact(value)[:MAX_TEXT]
    if isinstance(value, dict):
        return {str(k)[:48]: _clean(v) for k, v in list(value.items())[:MAX_KEYS]}
    if isinstance(value, (list, tuple)):
        return [_clean(v) for v in list(value)[:MAX_KEYS]]
    if isinstance(value, (bool, int, float)) or value is None:
        return value
    return redact(str(value))[:MAX_TEXT]


@dataclass
class Event:
    seq: int
    at: str
    kind: str
    data: dict
    who: dict = field(default_factory=dict)
    delta: dict = field(default_factory=dict)

    def as_json(self) -> dict:
        return {"seq": self.seq, "at": self.at, "kind": self.kind, "data": self.data, "who": self.who, "delta": self.delta}


class SessionStore:
    """Files on this PC: one JSON-lines file per session, plus user.json and app.json. Nothing is deleted unless `clear` is called."""

    def __init__(self, folder: Path):
        self.folder = Path(folder)
        self._lock = threading.Lock()

    def _session_path(self, session: str) -> Path:
        if not re.fullmatch(r"[A-Za-z0-9_\-]{1,64}", session):
            raise ValueError("a session id is letters, digits, dash and underscore")
        return self.folder / f"{session}.jsonl"

    def append(self, session: str, event: Event) -> None:
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            with open(self._session_path(session), "a", encoding="utf-8", newline="\n") as handle:
                handle.write(json.dumps(event.as_json(), ensure_ascii=False) + "\n")

    def events(self, session: str) -> list[Event]:
        path = self._session_path(session)
        if not path.is_file():
            return []
        out = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                raw = json.loads(line)
                out.append(Event(raw["seq"], raw["at"], raw["kind"], raw["data"], raw.get("who", {}), raw.get("delta", {})))
            except (ValueError, KeyError):
                continue  # a torn last line (a crash while writing) is skipped, the rest still loads
        return out

    def scope_file(self, scope: str) -> Path:
        return self.folder / f"{scope}.json"

    def load_scope(self, scope: str) -> dict:
        path = self.scope_file(scope)
        try:
            return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}
        except ValueError:
            return {}

    def save_scope(self, scope: str, values: dict) -> None:
        with self._lock:
            self.folder.mkdir(parents=True, exist_ok=True)
            tmp = self.scope_file(scope).with_suffix(".tmp")
            tmp.write_text(json.dumps(values, ensure_ascii=False, indent=1), encoding="utf-8", newline="\n")
            tmp.replace(self.scope_file(scope))

    def sessions(self) -> list[str]:
        return sorted(p.stem for p in self.folder.glob("*.jsonl")) if self.folder.is_dir() else []

    def clear(self, session: str | None = None) -> int:
        """Delete one session (or every session and the user and app files) because the player asked. Returns the number of files removed."""
        targets = [self._session_path(session)] if session else list(self.folder.glob("*.jsonl")) + [self.scope_file("user"), self.scope_file("app")]
        removed = 0
        for path in targets:
            if path.is_file():
                path.unlink()
                removed += 1
        return removed


class Session:
    def __init__(self, session_id: str | None = None, store: SessionStore | None = None, clock=lambda: datetime.now().astimezone()):
        self.id = session_id or uuid.uuid4().hex[:12]
        self.store, self._clock = store, clock
        self.events: list[Event] = []
        self._state: dict = {}
        self._temp: dict = {}
        self._user: dict = store.load_scope("user") if store else {}
        self._app: dict = store.load_scope("app") if store else {}
        self._seq = 0
        if store:
            for event in store.events(self.id):  # replaying the saved events rebuilds the scratchpad exactly
                self._apply(event.delta, persist=False)
                self.events.append(event)
                self._seq = max(self._seq, event.seq)

    def _apply(self, delta: dict, persist: bool = True) -> None:
        for key, value in delta.items():
            if not KEY.match(key):
                raise ValueError(f"bad state key {key!r}")
            scope = self._user if key.startswith("user:") else self._app if key.startswith("app:") else self._temp if key.startswith("temp:") else self._state
            if value is None:
                scope.pop(key, None)
            else:
                scope[key] = value
        if persist and self.store and any(k.startswith("user:") for k in delta):
            self.store.save_scope("user", self._user)
        if persist and self.store and any(k.startswith("app:") for k in delta):
            self.store.save_scope("app", self._app)

    def append(self, kind: str, data: dict | None = None, who: dict | None = None, delta: dict | None = None) -> Event:
        if kind not in KINDS:
            raise ValueError(f"unknown event kind {kind!r}")
        delta = _clean(delta or {})
        self._apply(delta)
        self._seq += 1
        event = Event(self._seq, self._clock().isoformat(timespec="seconds"), kind, _clean(data or {}), _clean(who or {}),
                      {k: v for k, v in delta.items() if not k.startswith("temp:")})  # temp: never leaves memory
        self.events.append(event)
        del self.events[:-MAX_EVENTS_IN_MEMORY]
        if self.store:
            self.store.append(self.id, event)
        return event

    def get(self, key: str, default=None):
        for scope in (self._temp, self._state, self._user, self._app):
            if key in scope:
                return scope[key]
        return default

    def end_turn(self) -> None:
        self._temp.clear()

    def transcript(self, limit: int = 12) -> list[str]:
        """The last events as short plain lines, for the model's context (as data: wrap it with security.fence)."""
        lines = []
        for event in self.events[-limit:]:
            body = ", ".join(f"{k}={v}" for k, v in list(event.data.items())[:4])
            lines.append(f"{event.kind}: {body}"[:200])
        return lines
