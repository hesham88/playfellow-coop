"""Reads a pilot's save (the game's own plain-text data format: indentation is structure, quotes group words). Read-only."""
from __future__ import annotations

import os
import re
from dataclasses import dataclass, field
from pathlib import Path

SAVES = Path(os.environ.get("APPDATA", "")) / "endless-sky" / "saves"
_TOKEN = re.compile(r'"([^"]*)"|`([^`]*)`|(\S+)')


@dataclass
class Node:
    tokens: list[str]
    children: list["Node"] = field(default_factory=list)

    @property
    def key(self) -> str:
        return self.tokens[0] if self.tokens else ""

    def value(self, default: str = "") -> str:
        return self.tokens[1] if len(self.tokens) > 1 else default

    def find(self, key: str) -> "Node | None":
        return next((c for c in self.children if c.key == key), None)

    def find_all(self, key: str) -> list["Node"]:
        return [c for c in self.children if c.key == key]


def parse(text: str) -> Node:
    root = Node([])
    stack: list[tuple[int, Node]] = [(-1, root)]
    for line in text.splitlines():
        stripped = line.strip()
        if not stripped or stripped.startswith("#"):
            continue
        depth = len(line) - len(line.lstrip("\t"))
        node = Node([a or b or c for a, b, c in _TOKEN.findall(stripped)])
        while stack[-1][0] >= depth:
            stack.pop()
        stack[-1][1].children.append(node)
        stack.append((depth, node))
    return root


@dataclass
class Job:
    title: str  # the mission's data name
    name: str  # what the job board shows
    description: str
    destination: str
    payment: int
    npc_systems: list[str]
    npc_ships: list[str] = field(default_factory=list)

    @property
    def is_bounty(self) -> bool:
        return self.title.startswith("Bounty Hunting")


def _payments(hooks: list[Node]) -> list[int]:
    return [int(c.value()) for h in hooks for c in h.children if c.key == "payment" and c.value().isdigit()]


def _job(node: Node) -> Job:
    payment = max(_payments(node.find_all("on")) or [0])
    systems, ships = [], []
    for npc in node.find_all("npc"):
        payment = max([payment] + _payments(npc.find_all("on")))
        for ship in npc.find_all("ship"):
            ships.append(ship.value())
            system = ship.find("system")
            if system is not None:
                systems.append(system.value())
    desc, name, dest = node.find("description"), node.find("name"), node.find("destination")
    return Job(node.value(), name.value() if name else "", desc.value() if desc else "", dest.value() if dest else "", payment, systems, ships)


@dataclass
class Pilot:
    name: str
    system: str
    planet: str
    credits: int
    conditions: dict[str, int]
    missions: list[Job]
    jobs: list[Job]
    ships: list[str]

    def done(self, mission: str) -> bool:
        return self.conditions.get(f"{mission}: done", 0) > 0

    def has(self, condition: str) -> bool:
        return self.conditions.get(condition, 0) > 0


def find_job(pilot: Pilot, title: str, not_these: frozenset[str] | set[str] = frozenset()) -> Job | None:
    """The job with this board title, accepted or still listed (the save written at acceptance can still list it as available). Several boards can post the
    same title: `not_these` holds the descriptions of the ones already turned down."""
    want = title.strip().lower()
    return next((j for j in pilot.missions + pilot.jobs if j.name.strip().lower() == want and j.description not in not_these), None)


def read_pilot(text: str) -> Pilot:
    root = parse(text)
    pilot, account = root.find("pilot"), root.find("account")
    credit_node = account.find("credits") if account else None
    conditions: dict[str, int] = {}
    block = root.find("conditions")
    for child in block.children if block else []:
        try:
            conditions[child.key] = int(float(child.value("1")))
        except ValueError:
            conditions[child.key] = 1

    def get(key: str) -> str:
        node = root.find(key)
        return node.value() if node else ""

    return Pilot(" ".join(pilot.tokens[1:]) if pilot else "", get("system"), get("planet"),
                 int(credit_node.value("0")) if credit_node else 0, conditions,
                 [_job(n) for n in root.find_all("mission")], [_job(n) for n in root.find_all("available job")],
                 [n.value() for n in root.find_all("ship")])


def load_pilot(name: str, saves: Path = SAVES) -> Pilot | None:
    """The save of this pilot only: a new pilot has none until the first landing, and an older pilot's file is not theirs."""
    for path in sorted(saves.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True):
        if "~" not in path.name and path.stem.endswith(name):  # the game can put a prefix before the typed first name
            return read_pilot(path.read_text(encoding="utf-8", errors="replace"))
    return None


def save_time(name: str, saves: Path = SAVES) -> float:
    """When this pilot's save was last written (0 when there is none)."""
    times = [p.stat().st_mtime for p in saves.glob("*.txt") if "~" not in p.name and p.stem.endswith(name)]
    return max(times, default=0.0)


def latest_save(saves: Path = SAVES) -> Path | None:
    files = [p for p in saves.glob("*.txt") if "~" not in p.name]
    return max(files, key=lambda p: p.stat().st_mtime) if files else None


def load_latest(saves: Path = SAVES) -> Pilot | None:
    path = latest_save(saves)
    return read_pilot(path.read_text(encoding="utf-8", errors="replace")) if path else None
