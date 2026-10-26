"""D-2: the web arena's scene definitions, made FROM the Python Practice Arena so the two can never drift apart.

  python demo/web/make_levels.py [--check]

Writes three files next to this one: levels.json (the three mazes), texts.json (the arena's own English and Arabic lines, taken from the Python
arena) and expected.json (for each maze the keys that win it, found by a fixed search over the Python arena's own state, and the final score). The
browser code is tested against expected.json: it must win each maze with the same keys, and its own search must find the same keys. The search is a
checking tool and a teacher; it is NOT part of the page (a test checks that no page file contains it). With --check nothing is written; the exit
code says whether the files on disk still match what the Python arena gives now.
"""
from __future__ import annotations

import argparse
import json
import sys
from collections import deque
from pathlib import Path

from practice_arena.game import COIN_POINTS, DOOR_POINTS, LEVEL, MOVES, TEXTS, ArenaGame

HERE = Path(__file__).resolve().parent
SCHEMA = "pf-web-levels/1"
DIRECTIONS = ("up", "down", "left", "right")  # the order ties are broken in, here and in the browser test

LEVELS = [
    {"id": "garden", "title": {"english": "Level 1: the garden", "arabic": "المرحلة ١: الحديقة"}, "rows": list(LEVEL)},
    {"id": "winding", "title": {"english": "Level 2: the winding paths", "arabic": "المرحلة ٢: الممرات الملتفة"}, "rows": [
        "############",
        "#P..c#...c.#",
        "#.##.#.###.#",
        "#.#c...#k..#",
        "#.#.####.#.#",
        "#...#..c.#.#",
        "###.#.##.#D#",
        "#c.....#...#",
        "############",
    ]},
    {"id": "short", "title": {"english": "Level 3: the short way round", "arabic": "المرحلة ٣: الطريق القصير"}, "rows": [
        "##########",
        "#P..#...c#",
        "#.#.#.##.#",
        "#c#...#k.#",
        "#.####.#.#",
        "#......D.#",
        "##########",
    ]},
]


def search(game: ArenaGame, goals: set, avoid: frozenset = frozenset()):
    """The shortest keys from ME to the nearest goal (ties broken by DIRECTIONS order), or None. The door is a wall until the key is held."""
    start = game.player
    if start in goals:
        return []
    seen, queue = {start: None}, deque([start])
    rows, cols = len(game.level), len(game.level[0])
    while queue:
        here = queue.popleft()
        for name in DIRECTIONS:
            dx, dy = MOVES[name]
            nxt = (here[0] + dx, here[1] + dy)
            if nxt in seen or nxt in avoid or not (0 <= nxt[0] < cols and 0 <= nxt[1] < rows) or nxt in game.walls:
                continue
            if nxt == game.door and not game.has_key:
                continue
            seen[nxt] = (here, name)
            if nxt in goals:
                path, tile = [], nxt
                while seen[tile] is not None:
                    tile, step = seen[tile]
                    path.append(step)
                return path[::-1]
            queue.append(nxt)
    return None


def winning_keys(rows: list[str]) -> list[str]:
    """Every coin nearest-first (never stepping on the key on the way), then the key, then the door."""
    game, keys = ArenaGame(tuple(rows)), []
    while game.coins:
        path = search(game, set(game.coins), frozenset({game.key} if game.key else ()))
        if path is None:
            path = search(game, set(game.coins))
        assert path is not None, "a coin cannot be reached"
        for key in path:
            game.press(key)
        keys += path
    for goal in ({game.key}, {game.door}):
        path = search(game, goal)
        assert path is not None, "the key or the door cannot be reached"
        for key in path:
            game.press(key)
        keys += path
    assert game.won, "the keys did not win the game"
    return keys


def build() -> dict:
    levels, expected = [], {}
    for level in LEVELS:
        rows = level["rows"]
        assert len({len(r) for r in rows}) == 1, f"{level['id']}: rows of different lengths"
        for symbol in "PkD":
            assert sum(r.count(symbol) for r in rows) == 1, f"{level['id']}: needs exactly one {symbol}"
        keys = winning_keys(rows)
        game = ArenaGame(tuple(rows))
        coins = game.coins_left
        for key in keys:
            game.press(key)
        expected[level["id"]] = {"keys": keys, "steps": len(keys), "coins": coins, "final_score": game.score, "moves": game.moves, "bumps": game.bumps}
        levels.append({"id": level["id"], "title": level["title"], "rows": rows})
    texts = {language: dict(lines) for language, lines in TEXTS.items()}
    return {"levels.json": {"schema": SCHEMA, "coin_points": COIN_POINTS, "door_points": DOOR_POINTS, "directions": list(DIRECTIONS), "levels": levels},
            "texts.json": {"schema": SCHEMA, "texts": texts},
            "expected.json": {"schema": SCHEMA, "levels": expected}}


def data_module(files: dict) -> str:
    """data.mjs: the levels and the lines as a module the page imports (so the page needs no network request to load them). The winning keys
    (expected.json) are deliberately NOT in it: the page never gets the answer."""
    body = {"coin_points": files["levels.json"]["coin_points"], "door_points": files["levels.json"]["door_points"],
            "levels": files["levels.json"]["levels"], "texts": files["texts.json"]["texts"]}
    header = "// Made by make_levels.py from the Python Practice Arena. Do not edit by hand." + chr(10)
    return header + "export default " + json.dumps(body, indent=1, ensure_ascii=False) + ";" + chr(10)


def render(data: dict) -> str:
    return json.dumps(data, indent=1, ensure_ascii=False) + "\n"


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--check", action="store_true", help="write nothing; exit 1 if the files on disk differ")
    args = parser.parse_args(argv)
    files = build()
    texts_on_disk = {name: render(data) for name, data in files.items()}
    texts_on_disk["data.mjs"] = data_module(files)
    stale = [name for name, text in texts_on_disk.items() if not (HERE / name).is_file() or (HERE / name).read_text(encoding="utf-8") != text]
    if args.check:
        for name in stale:
            print("out of date:", name)
        return 1 if stale else 0
    for name, text in texts_on_disk.items():
        (HERE / name).write_text(text, encoding="utf-8", newline=chr(10))
    print("wrote", ", ".join(texts_on_disk))
    return 0


if __name__ == "__main__":
    sys.exit(main())
