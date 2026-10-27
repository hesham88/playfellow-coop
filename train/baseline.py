"""The "base baseline" row (report 13, T-1 follow-up): how the engine's built-in navigator does on the held-out part of the training data.

  python -m train.baseline --data DIR [--out DIR] [--warm]

The built-in navigator needs no account, no network and no model. For every held-out row it looks at the same picture a model would be given and
presses one key. Two settings, always reported side by side and never mixed:
  cold   a fresh navigator sees only that one picture (it has not had time to learn which thing on the screen is "me");
  warm   a fresh navigator first sees the pictures of the walk that led to the frame, with the keys that walk pressed, as if it had been playing.
It ignores the command (it has no way to read one except stop and explore), so two numbers are written: whether its key walks TOWARD a target
(the same label the bake-off uses) and whether it presses the key the correct plan for that row starts with. The rows it writes use the bake-off's
raw format, so tools/accuracy_bench.py scores them without a new run. Every number comes from this run; nothing here is typed in.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import os
import sys
import time
from collections import deque
from pathlib import Path

from practice_arena.game import MOVES, ArenaGame

SCHEMA = "pf-results/2"
TOOL = "train_baseline"
KEYS = ("UP", "DOWN", "LEFT", "RIGHT")
DELTAS = {name: MOVES[name.lower()] for name in KEYS}


def distances(game: ArenaGame) -> dict:
    """Walking distance from every tile to the nearest target (a coin, the key if not held, the door once held)."""
    targets = set(game.coins) | ({game.key} if game.key is not None and not game.has_key else set()) | ({game.door} if game.has_key else set())
    rows, cols = len(game.level), len(game.level[0])
    dist = {tile: 0 for tile in targets}
    queue = deque(targets)
    while queue:
        x, y = queue.popleft()
        for dx, dy in DELTAS.values():
            nxt = (x + dx, y + dy)
            if nxt in dist or not (0 <= nxt[0] < cols and 0 <= nxt[1] < rows) or nxt in game.walls or (nxt == game.door and not game.has_key):
                continue
            dist[nxt] = dist[(x, y)] + 1
            queue.append(nxt)
    return dist


def toward_moves(game: ArenaGame) -> tuple[list[str], int | None, dict]:
    """(the keys that shorten the walk, the walk now, the walk after each key). A key into a wall leaves ME where it is."""
    dist = distances(game)
    here = dist.get(game.player)
    after = {}
    for name, (dx, dy) in DELTAS.items():
        nxt = (game.player[0] + dx, game.player[1] + dy)
        blocked = nxt in game.walls or (nxt == game.door and not game.has_key) or not (0 <= nxt[0] < len(game.level[0]) and 0 <= nxt[1] < len(game.level))
        after[name] = here if blocked else dist.get(nxt, here)
    return [n for n, v in after.items() if here is not None and v is not None and v < here], here, after


def replay(walk: list[str]) -> ArenaGame:
    game = ArenaGame()
    for key in walk:
        game.press(key)
    return game


def engine_dir() -> Path:
    """Where the engine's controls cards are: PLAYFELLOW_ENGINE when set, otherwise the installed engine's own folder
    (an unset variable used to mean the current folder, which crashed with FileNotFoundError)."""
    import play

    return Path(os.environ.get("PLAYFELLOW_ENGINE") or play.SOFTWARE)


def default_factory():
    """A fresh built-in navigator for the Practice Arena's card (needs the engine on the path, as the tests and the plugin have it)."""
    from brain.builtin_nav import BuiltinNavBrain
    from controls import load_card
    engine = engine_dir()
    return BuiltinNavBrain(load_card(engine / "controls" / "practice_arena.yaml"), "english")


def ask_once(brain, game: ArenaGame) -> str:
    from reply import parse_reply
    from controls import load_card
    engine = engine_dir()
    card = load_card(engine / "controls" / "practice_arena.yaml")
    raw = brain.ask("", "", [game.render().convert("RGB")])
    reply = parse_reply(raw, card, 1) if raw else None
    return reply.steps[0].action if reply is not None and not reply.confused and reply.steps else ""


def decide(row: dict, factory, warm: bool) -> str:
    """The key a fresh navigator presses for this row's frame; warm = after seeing the walk (its own `_last` set to the key the walk pressed)."""
    brain = factory()
    game = ArenaGame()
    if warm:
        for key in row["frame"]["walk"]:
            ask_once(brain, game)
            brain._last = key.upper()  # what it "pressed": the walk's own key, so what it learns from the next picture is real
            game.press(key)
    return ask_once(brain, game)


def score_rows(rows: list[dict], factory, warm: bool, timer=time.perf_counter) -> list[dict]:
    out = []
    for row in rows:
        game = replay(row["frame"]["walk"])
        best, here, after = toward_moves(game)
        plan = json.loads(row["completion"])["actions"]
        start = timer()
        action = decide(row, factory, warm)
        seconds = timer() - start
        out.append({"file": row["id"], "seed": row["frame"]["seed"], "valid": bool(action), "label": best, "action": action,
                    "distance_before": here, "distance_after": after.get(action), "toward": action in best, "seconds": round(seconds, 4), "error": "",
                    "intent": row["intent"], "language": row["language"], "plan_label": plan[0] if plan else None,
                    "follows_plan": bool(plan) and action == plan[0]})
    return out


def load_heldout(data: Path | str) -> list[dict]:
    rows = [json.loads(line) for line in (Path(data) / "heldout.jsonl").read_text(encoding="utf-8").splitlines() if line.strip()]
    if not rows or any(r["split"] != "heldout" for r in rows):
        raise ValueError("heldout.jsonl must hold held-out rows only")
    return rows


def summarize(scored: list[dict]) -> dict:
    sys.path.insert(0, str(Path(__file__).resolve().parent))
    n = len(scored)
    labelled = [r for r in scored if r["label"]]
    planned = [r for r in scored if r["plan_label"]]
    by_intent = {i: {"count": sum(r["follows_plan"] for r in planned if r["intent"] == i), "of": sum(1 for r in planned if r["intent"] == i)}
                 for i in sorted({r["intent"] for r in planned})}
    return {"n": n, "json_valid": {"count": sum(r["valid"] for r in scored), "of": n},
            "toward_a_target": {"count": sum(r["toward"] for r in labelled), "of": len(labelled)},
            "follows_the_plan": {"count": sum(r["follows_plan"] for r in planned), "of": len(planned)}, "follows_the_plan_by_intent": by_intent,
            "unlabelled_frames": n - len(labelled),
            # so a reader can tell a real skill from a habit: the share of rows where a blind guess among the four keys would be right, and how
            # much of the time the navigator pressed the single key it presses most
            "chance_toward": round(sum(len(r["label"]) for r in labelled) / (4 * len(labelled)), 4) if labelled else None,
            "most_common_key_share": round(max((sum(1 for r in scored if r["action"] == k) for k in {r["action"] for r in scored}), default=0) / n, 4) if n else None}


def run(data: Path | str, out_dir: Path | str, warm: bool, factory=default_factory, commit: str = "unknown") -> dict:
    """Score the held-out rows with a fresh navigator per row and write ONE results file (plus its raw log)."""
    data, out_dir = Path(data), Path(out_dir)
    manifest = json.loads((data / "manifest.json").read_text(encoding="utf-8"))
    rows = load_heldout(data)
    began = time.monotonic()
    scored = score_rows(rows, factory, warm)
    out_dir.mkdir(parents=True, exist_ok=True)
    mode = "warm" if warm else "cold"
    raw_path = out_dir / f"baseline-builtin-{mode}.raw.jsonl"
    raw_bytes = "".join(json.dumps(r, ensure_ascii=False) + "\n" for r in scored).encode("utf-8")
    raw_path.write_bytes(raw_bytes)
    result = {
        "schema": SCHEMA, "tool": TOOL, "commit": commit, "dirty": None, "machine": {"load": "not recorded"}, "brain": "builtin", "model": "navigator",
        "skin": "classic", "seeds": sorted({r["seed"] for r in scored}), "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "seconds": round(time.monotonic() - began, 1),
        "metrics": {"setting": mode, "heldout_sha256": manifest["heldout_sha256"], "raw_sha256": hashlib.sha256(raw_bytes).hexdigest(), **summarize(scored)},
        "levels": {}, "raw": str(raw_path),
    }
    (out_dir / f"baseline-builtin-{mode}.json").write_text(json.dumps(result, indent=2), encoding="utf-8")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--data", required=True)
    parser.add_argument("--out", default="results")
    parser.add_argument("--warm", action="store_true")
    parser.add_argument("--commit", default="unknown")
    args = parser.parse_args(argv)
    result = run(args.data, args.out, args.warm, commit=args.commit)
    m = result["metrics"]
    print(f"{m['setting']}: toward a target {m['toward_a_target']['count']} of {m['toward_a_target']['of']}, "
          f"follows the plan {m['follows_the_plan']['count']} of {m['follows_the_plan']['of']}, valid {m['json_valid']['count']} of {m['n']}, "
          f"chance {m['chance_toward']}, most common key {m['most_common_key_share']:.0%} of the time")
    return 0


if __name__ == "__main__":
    sys.exit(main())
