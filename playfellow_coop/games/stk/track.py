"""A track's driveline, read from the game's own data files (quads.xml and graph.xml in data/tracks/<track>/), the way a
player studies the map before a race: an ordered centre line around the main loop, with the road width at each point.

quads.xml lists four-cornered pieces of road; a corner may be written as "i:j" (corner j of quad i). graph.xml joins the
pieces: "edge-loop" closes a run of quads into a loop, "edge" adds a single link (a shortcut or a fork). The main line is
followed from quad 0 taking the first successor, which is the lowest-numbered one, until it comes back to quad 0.
"""
from __future__ import annotations

try:  # the game's files are local, but a hardened parser costs nothing
    import defusedxml.ElementTree as ET
except ImportError:  # pragma: no cover
    import xml.etree.ElementTree as ET
from dataclasses import dataclass
from pathlib import Path

from playfellow_coop.games.stk.paths import game_data

import numpy as np

DEFAULT_DATA = game_data()


def _point(text: str, quads: list[np.ndarray]) -> np.ndarray:
    if ":" in text:
        q, c = text.split(":")
        return quads[int(q)][int(c)].copy()
    return np.array([float(v) for v in text.split()], dtype=float)


def parse_quads(xml_text: str) -> list[np.ndarray]:
    quads: list[np.ndarray] = []
    for node in ET.fromstring(xml_text).iter("quad"):
        quads.append(np.stack([_point(node.get(f"p{i}"), quads) for i in range(4)]))
    return quads


def parse_successors(xml_text: str, count: int) -> dict[int, list[int]]:
    succ: dict[int, list[int]] = {i: [] for i in range(count)}
    root = ET.fromstring(xml_text)
    for node in root:
        if node.tag == "edge-loop":
            a, b = int(node.get("from")), int(node.get("to"))
            for i in range(a, b):
                succ[i].append(i + 1)
            succ[b].append(a)
        elif node.tag == "edge-line":
            a, b = int(node.get("from")), int(node.get("to"))
            for i in range(a, b):
                succ[i].append(i + 1)
        elif node.tag == "edge":
            succ[int(node.get("from"))].append(int(node.get("to")))
    if not any(succ.values()):  # no graph file content: the quads in order make one loop
        for i in range(count):
            succ[i].append((i + 1) % count)
    return {k: sorted(set(v)) for k, v in succ.items()}


@dataclass
class Track:
    name: str
    quads: list[np.ndarray]
    order: list[int]  # quad indices along the main line, starting at quad 0
    centre: np.ndarray  # (n, 2) world X, Z of each ordered quad's centre
    width: np.ndarray  # (n,) road width there
    bb_min: np.ndarray  # world X, Z of the bounding box of every quad corner
    bb_max: np.ndarray

    @classmethod
    def from_texts(cls, name: str, quads_xml: str, graph_xml: str | None) -> "Track":
        quads = parse_quads(quads_xml)
        succ = parse_successors(graph_xml, len(quads)) if graph_xml else parse_successors("<graph/>", len(quads))
        order, seen, i = [], set(), 0
        while i not in seen and len(order) <= len(quads):
            order.append(i)
            seen.add(i)
            nxt = succ.get(i) or []
            if not nxt:
                break
            i = nxt[0]
        corners = np.concatenate(quads)[:, [0, 2]]
        centre = np.array([q[:, [0, 2]].mean(axis=0) for q in (quads[k] for k in order)])
        width = np.array([np.linalg.norm(((q[1] + q[2]) - (q[0] + q[3]))[[0, 2]]) / 2 for q in (quads[k] for k in order)])
        return cls(name, quads, order, centre, width, corners.min(axis=0), corners.max(axis=0))

    @classmethod
    def load(cls, track_id: str, data: Path = DEFAULT_DATA) -> "Track":
        folder = data / "tracks" / track_id
        graph = folder / "graph.xml"
        return cls.from_texts(track_id, (folder / "quads.xml").read_text(encoding="utf-8"), graph.read_text(encoding="utf-8") if graph.exists() else None)

    def nearest(self, xz: np.ndarray, hint: int | None = None, window: int = 12) -> int:
        """Index (into `order`) of the centre point nearest to world X, Z; near `hint` when given, so crossing roads are not confused."""
        n = len(self.centre)
        if hint is None:
            idx = np.arange(n)
        else:
            idx = (hint + np.arange(-window // 3, window)) % n
        d = np.linalg.norm(self.centre[idx] - xz, axis=1)
        return int(idx[int(np.argmin(d))])

    def ahead(self, index: int, distance: float) -> np.ndarray:
        """The centre-line point `distance` metres further along from point `index`."""
        n, left, i = len(self.centre), distance, index
        while True:
            a, b = self.centre[i % n], self.centre[(i + 1) % n]
            seg = float(np.linalg.norm(b - a))
            if seg >= left or seg == 0 and left <= 0:
                return a + (b - a) * (left / seg if seg else 0.0)
            left -= seg
            i += 1
            if i - index > n:
                return b

    # ---- what a racer reads off the map before the race (4 Nov research, STK-research-2-deep) ----

    def lap_positions(self) -> np.ndarray:
        """Metres along the lap of each centre point."""
        seg = np.linalg.norm(np.roll(self.centre, -1, axis=0) - self.centre, axis=1)
        return np.concatenate([[0.0], np.cumsum(seg)[:-1]])

    def corners(self, min_deg: float = 25.0) -> list["Corner"]:
        """The bends of the lap: runs of the centre line turning one way, with the angle turned, the arc length and the radius
        (arc / angle). The driver plans skids from these: an arc driven in over 1 s pays a skid bonus, over 3 s the red one."""
        c = self.centre
        n = len(c)
        if n < 6:
            return []
        seg = np.linalg.norm(np.roll(c, -1, axis=0) - c, axis=1)
        s = np.concatenate([[0.0], np.cumsum(seg)[:-1]])
        d = np.roll(c, -1, axis=0) - c
        head = np.arctan2(d[:, 1], d[:, 0])
        turn = (np.roll(head, -1) - head + np.pi) % (2 * np.pi) - np.pi  # + = anti-clockwise in world X, Z
        rate = turn / np.maximum(seg, 0.2)
        bend = np.convolve(np.concatenate([rate[-2:], rate, rate[:2]]), np.ones(5) / 5, "valid")
        sign = np.where(np.abs(bend) > 0.012, np.sign(bend), 0)
        out, i = [], 0
        while i < n:
            if sign[i] == 0:
                i += 1
                continue
            j = i
            while j + 1 < n and sign[j + 1] == sign[i]:
                j += 1
            angle = float(turn[i:j + 1].sum())
            arc = float(seg[i:j + 1].sum())
            if abs(np.degrees(angle)) >= min_deg and arc > 0:
                out.append(Corner(i, j, float(s[i]), float(s[j] + seg[j]), 1 if angle > 0 else -1, abs(angle), arc,
                                  arc / max(abs(angle), 1e-3), float(self.width[i:j + 1].mean())))
            i = j + 1
        return out

    def lateral(self, index: int, xz: np.ndarray) -> float:
        """How far `xz` lies from the centre line at point `index`, metres; + = to the left of the direction of travel
        (anti-clockwise of it, in world X, Z: the same frame the driver steers in)."""
        n = len(self.centre)
        a, b = self.centre[index], self.centre[(index + 1) % n]
        d = (b - a) / max(float(np.linalg.norm(b - a)), 1e-6)
        rel = np.asarray(xz, float) - a
        return float(-rel[0] * d[1] + rel[1] * d[0])


@dataclass
class Corner:
    first: int  # index into `order` where the bend starts
    last: int
    s0: float  # metres along the lap
    s1: float
    side: int  # +1 anti-clockwise (world X, Z), -1 clockwise
    angle: float  # radians turned
    arc: float  # metres
    radius: float  # metres
    width: float


@dataclass
class TrackItem:
    kind: str  # "item" (gift box), "small-nitro", "big-nitro", "banana", "zipper"
    xz: np.ndarray
    index: int  # nearest centre point
    s: float  # metres along the lap
    offset: float  # metres from the centre line, + = left of travel (Track.lateral)


ITEM_TAGS = ("item", "small-nitro", "big-nitro", "banana", "zipper")


def load_items(track: Track, data: Path = DEFAULT_DATA) -> list[TrackItem]:
    """Every fixed item of the track (gift boxes, nitro cans, bananas, ground zippers) from its scene.xml, placed on the lap.
    The game takes an item when the kart's centre passes within 1.1 m of it (item.cpp: distance squared 1.2)."""
    scene = data / "tracks" / track.name / "scene.xml"
    try:
        root = ET.fromstring(scene.read_text(encoding="utf-8", errors="replace"))
    except (OSError, ET.ParseError):
        return []
    s_of = track.lap_positions()
    n = len(track.centre)
    out = []
    for node in root.iter():
        if node.tag not in ITEM_TAGS or node.get("x") is None or node.get("z") is None:
            continue
        xz = np.array([float(node.get("x")), float(node.get("z"))])
        i = int(np.argmin(np.linalg.norm(track.centre - xz, axis=1)))
        a, b = track.centre[i], track.centre[(i + 1) % n]
        seg = float(np.linalg.norm(b - a))
        along = float(np.dot(xz - a, (b - a) / seg)) if seg > 0 else 0.0
        total = float(s_of[-1] + np.linalg.norm(track.centre[0] - track.centre[-1]))
        out.append(TrackItem(node.tag, xz, i, (float(s_of[i]) + along) % total, track.lateral(i, xz)))
    return sorted(out, key=lambda t: t.s)
