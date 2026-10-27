"""The Rust fast path and its Python twin must give the same answers. Python tests always run; the native ones run when the DLL is
built (CI builds it and sets PF_REQUIRE_NATIVE=1, so a missing DLL there is a failure, not a silent skip)."""
from __future__ import annotations

import os
import random

import pytest

from playfellow_coop import fastpath

native = pytest.mark.skipif(not fastpath.available() and not os.environ.get("PF_REQUIRE_NATIVE"), reason="the Rust DLL is not built here")


def _grid(seed: int, w: int, h: int, density: float):
    rng = random.Random(seed)
    cells = bytes(1 if rng.random() < density else 0 for _ in range(w * h))
    free = [i for i, c in enumerate(cells) if not c]
    return cells, rng.choice(free), rng.choice(free)


def _bfs_length(w: int, h: int, cells: bytes, start: int, goal: int):
    """An independent check of the SHORTEST length (breadth-first search, no heuristic)."""
    from collections import deque

    dist = {start: 0}
    queue = deque([start])
    while queue:
        here = queue.popleft()
        if here == goal:
            return dist[here] + 1
        x, y = here % w, here // w
        for nx, ny in ((x, y - 1), (x + 1, y), (x, y + 1), (x - 1, y)):
            if 0 <= nx < w and 0 <= ny < h and not cells[ny * w + nx] and (ny * w + nx) not in dist:
                dist[ny * w + nx] = dist[here] + 1
                queue.append(ny * w + nx)
    return None


def _valid(w: int, cells: bytes, path: list[int], start: int, goal: int) -> bool:
    if path[0] != start or path[-1] != goal or any(cells[i] for i in path):
        return False
    return all(abs(a % w - b % w) + abs(a // w - b // w) == 1 for a, b in zip(path, path[1:]))


def test_the_native_flag_is_required_in_ci():
    if os.environ.get("PF_REQUIRE_NATIVE"):
        assert fastpath.available(), "CI built the Rust DLL, so it must load"


@pytest.mark.parametrize("seed", range(40))
def test_the_python_path_is_a_shortest_valid_path(seed):
    w, h = 12 + seed % 7, 9 + seed % 5
    cells, start, goal = _grid(seed, w, h, 0.28)
    path = fastpath.astar_py(w, h, cells, start, goal)
    expected = _bfs_length(w, h, cells, start, goal)
    if expected is None:
        assert path is None
    else:
        assert path is not None and len(path) == expected and _valid(w, cells, path, start, goal)


@native
@pytest.mark.parametrize("seed", range(200))
def test_native_and_python_give_the_identical_path(seed):
    w, h = 6 + seed % 40, 5 + (seed * 7) % 33
    cells, start, goal = _grid(seed, w, h, 0.05 + (seed % 9) * 0.04)
    assert fastpath.astar_native(w, h, cells, start, goal) == fastpath.astar_py(w, h, cells, start, goal)


@native
def test_native_handles_start_equals_goal_and_walled_off_goals():
    open_grid = bytes(25)
    assert fastpath.astar_native(5, 5, open_grid, 12, 12) == [12]
    walled = bytearray(25)
    for i in (1, 5, 7, 11):  # the corner cell 0 is closed in
        walled[i] = 1
    assert fastpath.astar_native(5, 5, bytes(walled), 0, 24) is None


@pytest.mark.parametrize("call", ["astar_py", "astar_native"])
def test_bad_arguments_are_refused_on_both_sides(call):
    if call == "astar_native" and not fastpath.available():
        pytest.skip("the Rust DLL is not built here")
    fn = getattr(fastpath, call)
    with pytest.raises(ValueError):
        fn(3, 3, bytes(8), 0, 8)  # the wrong number of cells
    with pytest.raises(ValueError):
        fn(3, 3, bytes(9), 0, 9)  # the goal is outside
    with pytest.raises(ValueError):
        fn(3, 3, bytes([1]) + bytes(8), 0, 8)  # the start is blocked
    with pytest.raises(ValueError):
        fn(0, 3, b"", 0, 0)


@native
def test_a_side_beyond_the_largest_allowed_is_refused():
    with pytest.raises(ValueError):
        fastpath.astar_native(16385, 1, bytes(16385), 0, 1)


@native
@pytest.mark.parametrize("seed", range(60))
def test_changed_cells_agree(seed):
    rng = random.Random(seed)
    a = bytes(rng.randrange(256) for _ in range(1024))
    b = bytes(min(255, max(0, x + rng.randrange(-40, 41))) for x in a)
    for threshold in (0, 20, 39, 255):
        assert fastpath.changed_cells_native(a, b, threshold) == fastpath.changed_cells_py(a, b, threshold)


def test_changed_cells_python_counts_only_the_cells_above_the_threshold():
    a, b = bytes([0, 10, 50, 100]), bytes([0, 30, 70, 100])
    assert fastpath.changed_cells_py(a, b, 20) == 0  # two cells differ by exactly 20, which is not MORE than 20
    assert fastpath.changed_cells_py(a, b, 19) == 2
    with pytest.raises(ValueError):
        fastpath.changed_cells(bytes(3), bytes(4), 1)


def test_the_public_functions_work_with_or_without_the_dll():
    cells, start, goal = _grid(5, 10, 8, 0.2)
    assert fastpath.astar(10, 8, cells, start, goal) == fastpath.astar_py(10, 8, cells, start, goal)
    assert fastpath.changed_cells(bytes(4), bytes([30, 0, 0, 0]), 20) == 1


def test_a_missing_or_wrong_dll_means_the_python_path(tmp_path, monkeypatch):
    monkeypatch.setenv(fastpath.ENV_DLL, str(tmp_path / "nothing.dll"))
    monkeypatch.setattr(fastpath, "_NATIVE_DIR", tmp_path)  # and no default library either
    assert fastpath._load() is None
    bogus = tmp_path / "pf_fastpath.dll"
    bogus.write_bytes(b"this is not a library")
    assert fastpath._load() is None  # a file that cannot be loaded is the same as no file
