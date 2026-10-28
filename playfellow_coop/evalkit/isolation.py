"""Keep an evaluation clean (Harness², research R5): no network while a candidate harness is being tried, an always-on prompt that stays small, and a record of what the search cost.

  NoNetwork      inside the block any attempt to open a connection or look up a host raises, so an agent cannot fetch a public grading rubric (one did) or the answers
  prompt_budget  the always-on text (system prompt, tool guidance, the skills paragraph) is paid for at every step of every task, so it has a size limit and a test that fails when it grows
  CostLedger     what the improvement search spent in total, by kind: the reference runs, the probes, the editing and the final run; efficiency is judged on the whole, not the last run
"""
from __future__ import annotations

import socket
from contextlib import contextmanager
from dataclasses import dataclass, field


class NetworkBlocked(OSError):
    """A network call was attempted while the network was switched off for an evaluation."""


@contextmanager
def NoNetwork():
    """Inside the block, opening a connection, resolving a name or sending to a socket raises NetworkBlocked. Everything is put back on exit."""
    original = (socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo, socket.gethostbyname)

    def blocked(*args, **kwargs):
        raise NetworkBlocked("the network is switched off during this evaluation")

    socket.socket.connect = blocked
    socket.socket.connect_ex = blocked
    socket.create_connection = blocked
    socket.getaddrinfo = blocked
    socket.gethostbyname = blocked
    try:
        yield
    finally:
        socket.socket.connect, socket.socket.connect_ex, socket.create_connection, socket.getaddrinfo, socket.gethostbyname = original


def estimate_tokens(text: str) -> int:
    return max(1, len(text) // 4)


def prompt_budget(parts: dict[str, str], limit_tokens: int) -> tuple[bool, dict[str, int]]:
    """(within the limit, tokens per part). The sum of the always-on parts must stay under `limit_tokens`."""
    sizes = {name: estimate_tokens(text) for name, text in parts.items()}
    return sum(sizes.values()) <= limit_tokens, sizes


KINDS = ("reference_run", "probe", "editing", "final_run")


@dataclass
class CostLedger:
    entries: list[tuple[str, float, int]] = field(default_factory=list)  # (kind, usd, calls)

    def add(self, kind: str, usd: float, calls: int = 1) -> None:
        if kind not in KINDS:
            raise ValueError(f"kind is one of {KINDS}")
        self.entries.append((kind, float(usd), int(calls)))

    def total(self) -> float:
        return sum(usd for _, usd, _ in self.entries)

    def by_kind(self) -> dict[str, float]:
        out = {k: 0.0 for k in KINDS}
        for kind, usd, _ in self.entries:
            out[kind] += usd
        return out

    def overhead_vs_final(self) -> float:
        """Total search cost divided by the cost of the final run alone: how many times more the improvement cost than just running the finished harness. inf when there was no final run."""
        final = self.by_kind()["final_run"]
        return float("inf") if final <= 0 else self.total() / final
