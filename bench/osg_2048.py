"""The assist on an open-source game we did not write: the original 2048 (Gabriele Cirulli, MIT), played in a headless browser.

    python bench/fetch_osg.py                      # once: the game at a pinned commit, into a cache folder outside the repository
    python -m bench.osg_2048 --seeds 5             # writes results/access/osg-2048-<date>.json

What is real here and what is not:
  * decisions are made from pixels only: a screenshot of the board, the colour of each cell sampled inside the tile (away from its digits and
    glow), mapped to a tile value by the game's own palette, then the same two-move look-ahead as our 2048 skill (`skills.tile_merge.best`);
  * the board's position on the page is read once from the page layout, the way a player finds the board before playing;
  * the page's own numbers (score, best tile, game-over) are used only to MEASURE whether a request was done, never to choose a move;
  * the page's random numbers are seeded (a small PRNG installed before the game loads), so a run can be repeated; the game's code is untouched;
  * every key goes through the real `OwnedKeys` guard and every request through the real `Assist`, as in a live session.

Requests are what a player would say: "get me to a 64 tile", then 128, 256, 512. Conditions: assist, split (the player keeps the key the
buddy used least in its unsplit run, still used at least once), random (random arrow keys). No model, no network, $0. No disabled player is
simulated: between requests the player rests and nothing is pressed."""
from __future__ import annotations

import argparse
import datetime
import functools
import http.server
import json
import random
import threading
from pathlib import Path

import numpy as np

from bench.access_bench import _commit, wilson
from playfellow_coop.assist import Assist, OwnedKeys
from playfellow_coop.skills.tile_merge import move, value


def choose(board, keys) -> str | None:
    """The 2048 skill's two-move look-ahead, over the keys the buddy may press."""
    scored = [(value(move(board, k), 2), k) for k in keys if move(board, k) != board]
    return max(scored)[1] if scored else None

GAME_DIR = Path(r"F:\PlayFellow\dev\cache\osg\2048")
PINNED = "478b6ec346e3787f589e4af751378d06ded4cbbc"
OUT = Path(__file__).resolve().parents[1] / "results" / "access"
TARGETS = (64, 128, 256, 512)
PART_TURNS = 400
SETTLE_MS = 260  # the slide takes 100 ms and a new tile pops in over 200 ms
KEYS = ("left", "right", "up", "down")
ARROWS = {"left": "ArrowLeft", "right": "ArrowRight", "up": "ArrowUp", "down": "ArrowDown"}
# the game's own palette (style/main.css); an empty cell is rgba(238,228,218,0.35) over the board colour #bbada0
PALETTE = {0: (205, 193, 180), 2: (238, 228, 218), 4: (237, 224, 200), 8: (242, 177, 121), 16: (245, 149, 99), 32: (246, 124, 95),
           64: (246, 94, 59), 128: (237, 207, 114), 256: (237, 204, 97), 512: (237, 200, 80), 1024: (237, 197, 63), 2048: (237, 194, 46)}
SEED_SCRIPT = """(() => { let s = %d >>> 0; Math.random = () => { s = (s + 0x6D2B79F5) >>> 0; let t = s;
  t = Math.imul(t ^ (t >>> 15), t | 1); t ^= t + Math.imul(t ^ (t >>> 7), t | 61); return ((t ^ (t >>> 14)) >>> 0) / 4294967296; };
  try { localStorage.clear(); } catch (e) {} })();"""


def value_of(rgb) -> int:
    return min(PALETTE, key=lambda v: sum((a - b) ** 2 for a, b in zip(PALETTE[v], rgb)))


def read_board(shot: np.ndarray, cells: list[tuple[float, float, float]]) -> list[list[int]]:
    """Each cell: (x, y, size) relative to the screenshot. Sample a small patch inside the tile's upper-left corner (no digits there)."""
    board = []
    for row in range(4):
        line = []
        for col in range(4):
            x, y, size = cells[row * 4 + col]
            a, b = int(x + size * 0.08), int(y + size * 0.08)
            patch = shot[b:b + max(3, int(size * 0.08)), a:a + max(3, int(size * 0.08)), :3].reshape(-1, 3).mean(0)
            line.append(value_of(tuple(patch)))
        board.append(line)
    return board


class Page:
    """The game in a headless browser: screenshot of the board, arrow keys, and the page's own numbers for measuring."""

    def __init__(self, browser, base: str, seed: int):
        self.pressed: list[str] = []  # every key that reached the page
        self.page = browser.new_page(viewport={"width": 700, "height": 900}, device_scale_factor=1)
        self.page.add_init_script(SEED_SCRIPT % (seed * 2654435761 + 12345))
        self.page.goto(base + "/index.html", wait_until="load")
        self.page.wait_for_timeout(400)
        box = self.page.locator(".game-container").bounding_box()
        self.clip = {"x": box["x"], "y": box["y"], "width": box["width"], "height": box["height"]}
        rects = self.page.evaluate("[...document.querySelectorAll('.grid-cell')].map(c => { const r = c.getBoundingClientRect(); return [r.x, r.y, r.width]; })")
        self.cells = [(x - box["x"], y - box["y"], w) for x, y, w in rects]

    def board(self) -> list[list[int]]:
        import io

        from PIL import Image
        shot = np.asarray(Image.open(io.BytesIO(self.page.screenshot(clip=self.clip))).convert("RGB"), dtype=np.float64)
        return read_board(shot, self.cells)

    def keyDown(self, key: str) -> None:  # noqa: N802  (the backend name the guard wraps)
        self.pressed.append(key)
        self.page.keyboard.press(ARROWS[key])
        self.page.wait_for_timeout(SETTLE_MS)

    def measured(self) -> dict:
        """The page's own numbers: for measuring only."""
        return self.page.evaluate("""() => ({ best: Math.max(0, ...[...document.querySelectorAll('.tile')].map(t => {
            const m = [...t.classList].find(c => /^tile-\\d+$/.test(c)); return m ? +m.slice(5) : 0; })),
            score: +(document.querySelector('.score-container').firstChild.textContent || 0),
            over: document.querySelector('.game-message').classList.contains('game-over') })""")

    def close(self):
        self.page.close()


def episode(browser, base: str, seed: int, condition: str, owned=(), part_turns: int = PART_TURNS, targets=TARGETS) -> dict:
    game = Page(browser, base, seed)
    owned = set(owned) if condition == "split" else set()
    guard = OwnedKeys(game, owned)
    rng = random.Random(seed * 7919 + 3)
    target = {"tile": 0}
    state = {"m": game.measured()}
    assist = Assist(max_turns=part_turns, done=lambda r, _p: "game_progress" if state["m"]["best"] >= target["tile"] else False)
    use = {k: 0 for k in KEYS}
    parts, misreads = [], 0
    for tile in targets:
        if state["m"]["over"]:
            break
        target["tile"] = tile
        assist.begin(f"get me to a {tile} tile", 0)
        line = None
        while line is None:
            if condition == "random":
                key = rng.choice([k for k in KEYS if k not in owned])
            else:
                board = game.board()
                key = choose(board, KEYS)
                if key in owned:  # the buddy's best key is one the player keeps: the attempt is refused (and counted), it takes its best other key
                    guard.keyDown(key)
                    key = choose(board, [k for k in KEYS if k not in owned])
                if key is None:  # the board as read allows no move: a misread; any key the buddy may press
                    misreads += 1
                    key = rng.choice([k for k in KEYS if k not in owned])
            guard.keyDown(key)
            use[key] += 1
            state["m"] = game.measured()
            line = assist.after_turn(None, 1, 0)
            if line is None and state["m"]["over"]:
                assist.end("game_over", 0)
                line = "over"
        record = dict(assist.log[-1])
        record["done"] = bool(record["done"]) and state["m"]["best"] >= tile
        record.pop("seconds", None)
        record.pop("ai_calls", None)
        parts.append(record)
    breaches = sum(1 for k in game.pressed if k in owned)  # a kept key that reached the page: must be 0
    final = game.measured()
    game.close()
    return {"game": "2048-web", "seed": seed, "condition": condition, "owned": sorted(owned), "parts": parts, "key_use": use,
            "refused": guard.refused, "breaches": breaches, "misreads": misreads, "best_tile": final["best"], "score": final["score"]}


def serve(folder: Path):
    class Quiet(http.server.SimpleHTTPRequestHandler):
        def log_message(self, *args):
            pass

    handler = functools.partial(Quiet, directory=str(folder))
    server = http.server.ThreadingHTTPServer(("127.0.0.1", 0), handler)
    threading.Thread(target=server.serve_forever, daemon=True).start()
    return server, f"http://127.0.0.1:{server.server_port}"


def launch(p):
    for options in ({}, {"channel": "msedge"}, {"channel": "chrome"}):
        try:
            return p.chromium.launch(**options)
        except Exception:
            continue
    raise RuntimeError("no Chromium, Edge or Chrome")


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--seeds", type=int, default=5)
    ap.add_argument("--game-dir", default=str(GAME_DIR))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    from playwright.sync_api import sync_playwright

    folder = Path(args.game_dir)
    if not (folder / "index.html").exists():
        raise SystemExit(f"the game is not in {folder}: run python bench/fetch_osg.py first")
    server, base = serve(folder)
    episodes = []
    with sync_playwright() as p:
        browser = launch(p)
        for seed in range(args.seeds):
            plain = episode(browser, base, seed, "assist")
            used = {k: n for k, n in plain["key_use"].items() if n > 0}
            keep = [min(used, key=lambda k: (used[k], k))] if len(used) > 1 else []
            episodes += [plain, episode(browser, base, seed, "split", owned=keep), episode(browser, base, seed, "random")]
            print(f"seed {seed}: assist best {plain['best_tile']}, split best {episodes[-2]['best_tile']} (kept {keep}), random best {episodes[-1]['best_tile']}", flush=True)
        browser.close()
    server.shutdown()
    rows = {}
    for cond in ("assist", "split", "random"):
        eps = [e for e in episodes if e["condition"] == cond]
        parts = [x for e in eps for x in e["parts"]]
        done = [x for x in parts if x["done"]]
        rows[cond] = {"episodes": len(eps), "requests": len(parts), "done": len(done), "done_rate_95": wilson(len(done), len(parts)),
                      "by_target": {str(t): sum(1 for x in done if x["request"].endswith(f"{t} tile")) for t in TARGETS},
                      "presses_spared": sum(x["actions"] for x in parts), "refused": sum(e["refused"] for e in eps),
                      "breaches": sum(e["breaches"] for e in eps), "misreads": sum(e["misreads"] for e in eps),
                      "best_tiles": [e["best_tile"] for e in eps]}
    result = {"schema": "pf-access-osg/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "game": {"name": "2048", "author": "Gabriele Cirulli", "licence": "MIT", "source": "https://github.com/gabrielecirulli/2048", "pinned": PINNED},
              "brain": "the 2048 skill's look-ahead on the board read from pixels (no model, no network, $0)", "targets": TARGETS, "part_turns": PART_TURNS,
              "honesty": "Decisions from pixels only; the page's numbers only measure. The page's Math.random is seeded for repeatability. "
                         "No disabled player was simulated or involved.", "summary": rows, "episodes": episodes}
    out = Path(args.out) if args.out else OUT / f"osg-2048-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    for cond, r in rows.items():
        print(f"{cond:7} done {r['done']}/{r['requests']} 95% {r['done_rate_95']} by target {r['by_target']} spared {r['presses_spared']} refused {r['refused']} breaches {r['breaches']} misreads {r['misreads']}")
    print("wrote", out)
    return 1 if any(r["breaches"] for r in rows.values()) else 0


if __name__ == "__main__":
    raise SystemExit(main())
