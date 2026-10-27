"""Times the Rust fast path against its Python twin and writes ONE pf-results/1 file with only measured numbers.

    python bench/fastpath_bench.py            (needs the DLL, see rust/README.md; without it the file says "not measured")

Nothing here is typed in: every number comes from the timing loop below, and the file records the commit, whether the
working tree was dirty, and the machine, like every other result in this repository.
"""
from __future__ import annotations

import json
import random
import statistics
import sys
import time
from datetime import datetime
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from playfellow_coop import bench, fastpath  # noqa: E402

SIDES = (32, 64, 128, 256)
REPEATS = 15


def _grid(seed: int, side: int):
    """A random grid with a path from the top-left to the bottom-right cell (the first seed that has one), so every row is a real search."""
    for attempt in range(60):
        rng = random.Random(seed * 1000 + attempt)
        cells = bytearray(1 if rng.random() < 0.18 else 0 for _ in range(side * side))
        cells[0] = 0
        cells[-1] = 0
        if fastpath.astar_py(side, side, bytes(cells), 0, side * side - 1) is not None:
            return bytes(cells), 0, side * side - 1
    raise RuntimeError("no grid with a path found: lower the density")


def _time(call, repeats: int) -> list[float]:
    out = []
    for _ in range(repeats):
        began = time.perf_counter()
        call()
        out.append((time.perf_counter() - began) * 1000)
    return out


def _summary(values: list[float]) -> dict:
    ordered = sorted(values)
    return {"n": len(values), "median_ms": round(statistics.median(ordered), 4),
            "p95_ms": round(ordered[min(len(ordered) - 1, int(0.95 * len(ordered)))], 4), "min_ms": round(ordered[0], 4)}


def run(out_dir: Path) -> Path:
    rows = []
    for side in SIDES:
        cells, start, goal = _grid(side, side)
        py_path = fastpath.astar_py(side, side, cells, start, goal)
        row = {"grid": f"{side}x{side}", "path_found": py_path is not None, "path_cells": len(py_path) if py_path else None,
               "python": _summary(_time(lambda: fastpath.astar_py(side, side, cells, start, goal), REPEATS))}
        if fastpath.available():
            rust_path = fastpath.astar_native(side, side, cells, start, goal)
            row["same_path_as_python"] = rust_path == py_path
            row["rust"] = _summary(_time(lambda: fastpath.astar_native(side, side, cells, start, goal), REPEATS))
            row["speedup_x"] = round(row["python"]["median_ms"] / row["rust"]["median_ms"], 1) if row["rust"]["median_ms"] else None
        else:
            row["rust"] = bench.NOT_MEASURED if hasattr(bench, "NOT_MEASURED") else "not measured"
        rows.append(row)
    a = bytes(random.Random(1).randrange(256) for _ in range(1024))
    b = bytes(min(255, x + 3) for x in a)
    thumb = {"cells": 1024, "python": _summary(_time(lambda: fastpath.changed_cells_py(a, b, 20), 400))}
    if fastpath.available():
        thumb["rust"] = _summary(_time(lambda: fastpath.changed_cells_native(a, b, 20), 400))
        thumb["same_count"] = fastpath.changed_cells_native(a, b, 20) == fastpath.changed_cells_py(a, b, 20)
    commit, dirty = bench.git_state(ROOT)
    data = {"schema": "pf-results/1", "tool": "fastpath_bench", "commit": commit, "dirty": dirty, "machine": bench.machine(),
            "started": datetime.now().astimezone().isoformat(timespec="seconds"),
            "metrics": {"label": "diagnostic" if dirty else "clean", "native_loaded": fastpath.available(), "astar": rows,
                        "thumbnail_change": thumb,
                        "note": "the speed-up depends on the grid, this PC and how busy it is; read the medians, not one run"}}
    out_dir.mkdir(parents=True, exist_ok=True)
    path = out_dir / f"fastpath_bench-{datetime.now().strftime('%Y%m%d-%H%M%S')}-{commit[:7]}.json"
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")
    return path


if __name__ == "__main__":
    written = run(ROOT / "results")
    print(written)
    print(json.dumps(json.loads(written.read_text(encoding="utf-8"))["metrics"]["astar"], indent=1)[:1500])
