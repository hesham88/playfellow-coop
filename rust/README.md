# The optional Rust fast path

Two small hot paths, written **during the hackathon** and sharing no code with any earlier project:

| Function | What it does | Used by |
|---|---|---|
| `pf_astar_grid` | shortest 4-connected path on a grid (A*, unit cost, Manhattan heuristic, tie-break by cost, then distance, then cell index) | route planning on the arena grid |
| `pf_changed_cells` | how many bytes of two thumbnails differ by more than a threshold | SAM keyframes: ask SAM again only when the picture changed |

It is **optional**. `playfellow_coop/fastpath.py` loads the DLL with `ctypes` and has an identical pure-Python twin, so a PC without a Rust toolchain gets the same answers, only slower. Tests check that both give the **identical path** on 200 random grids and the **identical count** on 60 random thumbnail pairs; CI builds the DLL and fails if it cannot be loaded.

## Build it (Windows)

```
powershell -ExecutionPolicy Bypass -File rust/build.ps1
python -c "from playfellow_coop import fastpath; print(fastpath.available())"
python bench/fastpath_bench.py
```

The DLL has no dependencies (no crates, no runtime DLLs to ship) and is never committed (`playfellow_coop/_native/` is ignored).

## Measured (this PC, one run; read the medians, run it yourself)

The numbers live in `results/fastpath_bench-*.json`, written by `bench/fastpath_bench.py`. Typical: 8 to 33 times faster for grid search, and about 50 times for the thumbnail count (which includes the cost of the call). The speed-up depends on the grid and on how busy the PC is.
