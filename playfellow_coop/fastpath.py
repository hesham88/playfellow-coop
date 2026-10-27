"""An optional Rust fast path (rust/fastpath) with an identical pure-Python twin.

Two small hot paths: grid A* and the thumbnail change count that decides whether the picture changed enough to ask SAM again.
Like a shortcut through a park: if the shortcut is closed (no compiled library on this PC), you take the main path and get
the same answer, only a little later. Both are tested to give identical results, on random grids and random thumbnails.
Written during the hackathon; it shares no code with any earlier project.
"""
from __future__ import annotations

import ctypes
import heapq
import os
from pathlib import Path

ABI = 1
ENV_DLL = "PF_FASTPATH_DLL"
_NATIVE_DIR = Path(__file__).resolve().parent / "_native"
_UP, _RIGHT, _DOWN, _LEFT = (0, -1), (1, 0), (0, 1), (-1, 0)  # the neighbour order the Rust side uses too


def _load() -> ctypes.CDLL | None:
    candidates = [Path(os.environ[ENV_DLL])] if os.environ.get(ENV_DLL) else []
    candidates.append(_NATIVE_DIR / "pf_fastpath.dll")
    for path in candidates:
        try:
            lib = ctypes.CDLL(str(path))
            lib.pf_fastpath_abi.restype = ctypes.c_uint32
            if lib.pf_fastpath_abi() != ABI:
                continue  # an older or newer build: do not trust it
            lib.pf_astar_grid.argtypes = [ctypes.c_uint32, ctypes.c_uint32, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint32,
                                          ctypes.POINTER(ctypes.c_uint32), ctypes.c_uint32]
            lib.pf_astar_grid.restype = ctypes.c_int32
            lib.pf_changed_cells.argtypes = [ctypes.c_char_p, ctypes.c_char_p, ctypes.c_uint32, ctypes.c_uint8]
            lib.pf_changed_cells.restype = ctypes.c_uint32
            return lib
        except (OSError, AttributeError):
            continue
    return None


_LIB = _load()


def available() -> bool:
    """True when the compiled library was found and checked."""
    return _LIB is not None


def _check(width: int, height: int, cells: bytes, start: int, goal: int) -> None:
    size = width * height
    if width < 1 or height < 1 or width > 16384 or height > 16384 or len(cells) != size:
        raise ValueError("bad_args")
    if not (0 <= start < size and 0 <= goal < size) or cells[start] or cells[goal]:
        raise ValueError("bad_args")


def astar_py(width: int, height: int, cells: bytes, start: int, goal: int) -> list[int] | None:
    """Shortest 4-connected path (cell indexes, start to goal) or None; the pure-Python twin of the Rust function."""
    _check(width, height, cells, start, goal)
    gx, gy = goal % width, goal // width

    def heuristic(index: int) -> int:
        return abs(index % width - gx) + abs(index // width - gy)

    unseen = 1 << 40
    cost = [unseen] * (width * height)
    parent = [-1] * (width * height)
    cost[start] = 0
    open_list = [(heuristic(start), heuristic(start), start)]
    while open_list:
        f, _h, here = heapq.heappop(open_list)
        if here == goal:
            break
        if f != cost[here] + heuristic(here):
            continue  # stale entry
        x, y = here % width, here // width
        for dx, dy in (_UP, _RIGHT, _DOWN, _LEFT):
            nx, ny = x + dx, y + dy
            if not (0 <= nx < width and 0 <= ny < height):
                continue
            there = ny * width + nx
            if cells[there]:
                continue
            g = cost[here] + 1
            if g < cost[there]:
                cost[there] = g
                parent[there] = here
                hh = heuristic(there)
                heapq.heappush(open_list, (g + hh, hh, there))
    if cost[goal] == unseen:
        return None
    path = [goal]
    while path[-1] != start:
        path.append(parent[path[-1]])
    path.reverse()
    return path


def astar_native(width: int, height: int, cells: bytes, start: int, goal: int) -> list[int] | None:
    """The same, through the Rust library. Raises RuntimeError if the library is not loaded."""
    if _LIB is None:
        raise RuntimeError("the Rust fast path is not loaded")
    _check(width, height, cells, start, goal)
    out = (ctypes.c_uint32 * (width * height))()
    code = _LIB.pf_astar_grid(width, height, cells, start, goal, out, width * height)
    if code == -1:
        return None
    if code < 0:
        raise ValueError("bad_args" if code == -2 else "out_too_small")
    return list(out[:code])


def astar(width: int, height: int, cells: bytes, start: int, goal: int) -> list[int] | None:
    """Rust when available, otherwise Python: the same answer either way."""
    return astar_native(width, height, cells, start, goal) if _LIB is not None else astar_py(width, height, cells, start, goal)


def changed_cells_py(a: bytes, b: bytes, threshold: int) -> int:
    return sum(abs(x - y) > threshold for x, y in zip(a, b))


def changed_cells_native(a: bytes, b: bytes, threshold: int) -> int:
    if _LIB is None:
        raise RuntimeError("the Rust fast path is not loaded")
    if len(a) != len(b):
        raise ValueError("bad_args")
    return int(_LIB.pf_changed_cells(a, b, len(a), threshold))


def changed_cells(a: bytes, b: bytes, threshold: int) -> int:
    """How many cells differ by more than `threshold` grey levels (Rust when available, otherwise Python)."""
    if len(a) != len(b):
        raise ValueError("bad_args")
    return changed_cells_native(a, b, threshold) if _LIB is not None else changed_cells_py(a, b, threshold)
