"""Score SAM marks against the Practice Arena's own truth: precision, recall and latency, offline.

The arena knows where its coins, door and player are, so a mark can be checked without a human. The score says how many marks
were right (precision) and how many real things were found (recall). WHO produced the marks is recorded in the result, because a
run against the fake server in playfellow_coop/fakes.py only checks this harness; it says nothing about SAM's accuracy."""
from __future__ import annotations

import math

from grounding import Mark, mark_from_box
from practice_arena.game import BANNER, TILE

TOLERANCE = 60  # grid units (0-1000): a mark this close to a real thing counts as finding it


def tile_box(cell: tuple[int, int]) -> tuple[int, int, int, int]:
    x, y = cell
    return (x * TILE, BANNER + y * TILE, (x + 1) * TILE, BANNER + (y + 1) * TILE)


def arena_truth_boxes(game) -> dict[str, list[tuple[int, int, int, int]]]:
    """Pixel boxes of what is really on screen, by mark kind."""
    return {"me": [tile_box(game.player)], "reward": [tile_box(c) for c in sorted(game.coins)] + ([tile_box(game.key)] if game.key else []),
            "door": [tile_box(game.door)], "hazard": []}


def arena_truth(game) -> dict[str, list[Mark]]:
    size = game.pixel_size
    return {kind: [mark_from_box(kind, box, size) for box in boxes] for kind, boxes in arena_truth_boxes(game).items()}


def score(marks: list[Mark], truth: dict[str, list[Mark]], tolerance: float = TOLERANCE) -> dict[str, dict]:
    """Per kind: tp, fp, fn, precision, recall. A truth mark can be found once; each mark can find one thing."""
    out = {}
    for kind in ("me", "reward", "hazard", "door"):
        wanted = list(truth.get(kind, []))
        got = [m for m in marks if m.kind == kind]
        found = 0
        for mark in got:
            near = min(wanted, key=lambda t: math.hypot(t.x - mark.x, t.y - mark.y), default=None)
            if near is not None and math.hypot(near.x - mark.x, near.y - mark.y) <= tolerance:
                wanted.remove(near)
                found += 1
        total_truth = len(truth.get(kind, []))
        out[kind] = {"tp": found, "fp": len(got) - found, "fn": total_truth - found,
                     "precision": (found / len(got)) if got else None, "recall": (found / total_truth) if total_truth else None}
    return out


def evaluate(marker, games, source: str) -> dict:
    """Run the marker on each game's frame and total the scores. `source` names what answered ("fake server", "SAM 3.1")."""
    totals = {kind: {"tp": 0, "fp": 0, "fn": 0} for kind in ("me", "reward", "hazard", "door")}
    for game in games:
        per_kind = score(marker(game.render()), arena_truth(game))
        for kind, row in per_kind.items():
            for field in ("tp", "fp", "fn"):
                totals[kind][field] += row[field]
    for kind, row in totals.items():
        row["precision"] = row["tp"] / (row["tp"] + row["fp"]) if row["tp"] + row["fp"] else None
        row["recall"] = row["tp"] / (row["tp"] + row["fn"]) if row["tp"] + row["fn"] else None
    latencies = sorted(getattr(marker, "latencies", []))
    return {"source": source, "frames": len(games), "kinds": totals, "requests": getattr(marker, "calls", None),
            "latency_p50_s": latencies[max(0, math.ceil(0.5 * len(latencies)) - 1)] if latencies else "not measured",
            "note": ("this run checks the harness only: the answers came from a fake server built from the arena's own truth, "
                     "so the scores say nothing about SAM") if "fake" in source else "measured against the arena's own truth"}


# ---- stable IDs across frames ---------------------------------------------------------------------------------------------------------
def arena_objects(game) -> dict[str, tuple[str, tuple[int, int, int, int]]]:
    """Every real thing on screen under a name that stays the same from frame to frame: name -> (mark kind, pixel box)."""
    out = {"me": ("me", tile_box(game.player)), "door": ("door", tile_box(game.door))}
    for cell in sorted(game.coins):
        out[f"coin@{cell[0]},{cell[1]}"] = ("reward", tile_box(cell))
    if game.key:
        out[f"key@{game.key[0]},{game.key[1]}"] = ("reward", tile_box(game.key))
    return out


def _centre(box) -> tuple[float, float]:
    return (box[0] + box[2]) / 2, (box[1] + box[3]) / 2


def id_stability(marker, frames, source: str, tolerance_px: float = 40.0) -> dict:
    """Run the marker (with its tracker) over consecutive frames. For each real thing seen in two frames in a row, check that the nearest
    track of its kind carries the same number in both. `frames` = [(picture, arena_objects(game))]."""
    seen_ids: list[dict[str, int]] = []
    for picture, objects in frames:
        marker(picture)
        tracks = list(getattr(marker.tracker, "tracks", []) or [])
        ids = {}
        for name, (kind, box) in objects.items():
            cx, cy = _centre(box)
            near = min((t for t in tracks if t.kind == kind), key=lambda t: math.hypot(_centre(t.box)[0] - cx, _centre(t.box)[1] - cy), default=None)
            if near is not None and math.hypot(_centre(near.box)[0] - cx, _centre(near.box)[1] - cy) <= tolerance_px:
                ids[name] = near.id
        seen_ids.append(ids)
    pairs = stable = 0
    for before, after in zip(seen_ids, seen_ids[1:]):
        for name in before.keys() & after.keys():
            pairs += 1
            stable += before[name] == after[name]
    return {"source": source, "frames": len(frames), "pairs": pairs, "stable": stable,
            "stable_rate": round(stable / pairs, 4) if pairs else None,
            "sam_requests": getattr(marker, "calls", None), "tracked_pictures": getattr(marker, "tracked_pictures", None),
            "note": ("this run checks the harness only: the answers came from a fake server built from the arena's own truth, "
                     "so it says nothing about SAM") if "fake" in source else "measured against the arena's own truth"}
