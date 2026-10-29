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
    """Inside the block, opening a connection, resolving a name or sending on a socket raises NetworkBlocked. Everything is put back on exit. It is process-wide (every thread is
    affected, including the program's own) and it does not stop a child process such as curl, nor a function imported by name before the block began."""
    names = ("connect", "connect_ex", "send", "sendall", "sendto")
    originals = {n: getattr(socket.socket, n) for n in names}
    original = (socket.create_connection, socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex, socket.gethostbyaddr, socket.getnameinfo)

    def blocked(*args, **kwargs):
        raise NetworkBlocked("the network is switched off during this evaluation")

    for n in names:
        setattr(socket.socket, n, blocked)
    socket.create_connection = socket.getaddrinfo = socket.gethostbyname = socket.gethostbyname_ex = socket.gethostbyaddr = socket.getnameinfo = blocked
    try:
        yield
    finally:
        for n in names:
            setattr(socket.socket, n, originals[n])
        socket.create_connection, socket.getaddrinfo, socket.gethostbyname, socket.gethostbyname_ex, socket.gethostbyaddr, socket.getnameinfo = original


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
