"""A daily spending cap for the Muse brain, kept in a small file so a restart does not reset it.

The cap stops a call BEFORE it is sent. Prices are the Standard-mode prices for muse-spark (dollars per token); the cost of a
call is worked out from the token counts the provider reports. If a reply carries no counts, the call is charged a stated
estimate and flagged, never silently counted as free."""
from __future__ import annotations

import json
import os
import threading
import time
from pathlib import Path
from typing import Callable

INPUT_USD_PER_TOKEN = 1.25e-6  # muse-spark Standard, per input token
OUTPUT_USD_PER_TOKEN = 4.25e-6  # per output token


class DailyBudget:
    def __init__(self, path, cap_usd: float, max_calls: int, estimate_usd: float = 0.01,
                 today: Callable[[], str] = lambda: time.strftime("%Y-%m-%d")):
        self.path = Path(path)
        self.cap_usd = float(cap_usd)
        self.max_calls = int(max_calls)
        self.estimate_usd = float(estimate_usd)
        self._today = today
        self._guard = threading.RLock()  # several requests may finish at once (the SAM phrases are asked together)

    def _load(self) -> dict:
        fresh = {"date": self._today(), "spent_usd": 0.0, "calls": 0, "estimated_calls": 0}
        try:
            data = json.loads(self.path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            return fresh
        return data if isinstance(data, dict) and data.get("date") == fresh["date"] else fresh

    def _save(self, data: dict) -> None:
        self.path.parent.mkdir(parents=True, exist_ok=True)
        temporary = self.path.with_suffix(".tmp")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)  # a crash never leaves half a file

    def exhausted(self) -> bool:
        data = self._load()
        return data["spent_usd"] >= self.cap_usd or data["calls"] >= self.max_calls

    def record_cost(self, usd: float) -> float:
        """Add one call whose price is known up front (for example a per-image price)."""
        with self._guard:
            data = self._load()
            data["spent_usd"] = float(data["spent_usd"]) + usd
            data["calls"] = int(data["calls"]) + 1
            self._save(data)
        return usd

    def record(self, prompt_tokens: int | None = None, completion_tokens: int | None = None) -> float:
        """Add one finished call. Returns what it cost."""
        data = self._load()
        if prompt_tokens is None and completion_tokens is None:
            cost = self.estimate_usd
            data["estimated_calls"] = data.get("estimated_calls", 0) + 1
        else:
            cost = (prompt_tokens or 0) * INPUT_USD_PER_TOKEN + (completion_tokens or 0) * OUTPUT_USD_PER_TOKEN
        data["spent_usd"] = float(data["spent_usd"]) + cost
        data["calls"] = int(data["calls"]) + 1
        self._save(data)
        return cost
