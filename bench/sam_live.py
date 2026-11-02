"""SAM 3.1, measured for real on the Practice Arena (our own game, so its pictures may be published): are the marks right, and do the
numbers stay with the same things across frames?

    MODEL_API_KEY=... python -m bench.sam_live --frames 20 --max-usd 0.5       # writes results/sam/sam-live-<date>.json and docs/img/sam-marked-frame.png

  * accuracy: precision and recall per kind (me, reward, door) against the arena's own truth (`sam_eval.evaluate`);
  * stable IDs: the marker with its tracker over a walk of consecutive frames, scored by `sam_eval.id_stability`;
  * one real marked frame is saved for the README and the video (replacing the fake-server picture), with the source written beside it.
Every SAM request is paid by the image; the spend stops at --max-usd."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

from bench.access_bench import _commit

ROOT = Path(__file__).resolve().parents[1]
WALK = ["right", "right", "down", "down", "right", "right", "down", "left", "down", "right", "right", "up", "right", "down", "down",
        "right", "left", "down", "right", "right", "up", "up", "right", "down"]


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--frames", type=int, default=20)
    ap.add_argument("--max-usd", type=float, default=0.5)
    ap.add_argument("--budget-file", default=str(Path.home() / ".playfellow-coop" / "sam-live-budget.json"))
    args = ap.parse_args(argv)
    from practice_arena.game import ArenaGame

    from playfellow_coop.budget import DailyBudget
    from playfellow_coop.sam_eval import arena_objects, evaluate, id_stability
    from playfellow_coop.sam_marks import USD_PER_IMAGE, SamMarker, mark_image_full
    from playfellow_coop.tracking import Tracker

    key = os.environ["MODEL_API_KEY"]
    budget = DailyBudget(Path(args.budget_file), cap_usd=args.max_usd, max_calls=10_000)
    # accuracy: a fresh frame each step of the walk, SAM asked every time (no tracker), against the truth of that frame
    plain = SamMarker(key, budget=budget)
    games = []
    for k in range(args.frames):  # frame k = a fresh game after the first k steps of the walk
        snapshot = ArenaGame()
        for step in WALK[:k]:
            snapshot.press(step)
        games.append(snapshot)
    accuracy = evaluate(plain, games, source="SAM 3.1")
    # stable IDs: the marker with its tracker over the same walk
    game = ArenaGame()
    tracked = SamMarker(key, budget=budget, tracker=Tracker(refresh_every=4))
    frames = [(game.render(), arena_objects(game))]
    for step in WALK[: args.frames]:
        game.press(step)
        frames.append((game.render(), arena_objects(game)))
    stability = id_stability(tracked, frames, source="SAM 3.1")
    # one real marked frame for the README and the video
    picture, labels, marks = mark_image_full(ArenaGame().render(), SamMarker(key, budget=budget))
    img = ROOT / "docs" / "img" / "sam-marked-frame.png"
    img.parent.mkdir(parents=True, exist_ok=True)
    picture.save(img)
    requests = (plain.calls or 0) + (tracked.calls or 0) + 1
    result = {"schema": "pf-sam-live/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "model": "sam-3.1", "game": "Practice Arena (our own game)", "accuracy": accuracy, "id_stability": stability,
              "marked_frame": {"file": "docs/img/sam-marked-frame.png", "marks": len(marks), "labels": labels},
              "requests_upper_bound": requests, "cost_usd_upper_bound": round(requests * USD_PER_IMAGE, 4),
              "honesty": "Our own simple 2D game; the truth comes from the game itself. Not evidence of accuracy on other games."}
    out = ROOT / "results" / "sam" / f"sam-live-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1, default=str) + "\n", encoding="utf-8")
    print(json.dumps({k: result[k] for k in ("id_stability", "requests_upper_bound", "cost_usd_upper_bound")}, default=str))
    print(json.dumps(accuracy["kinds"]), "\nwrote", out, "and", img)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
