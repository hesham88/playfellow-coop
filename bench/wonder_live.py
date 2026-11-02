"""Muse Wonder, measured for real: first sight on games it has never seen, and debriefs that may only use counted numbers.

    MODEL_API_KEY=... python -m bench.wonder_live --games maze_chase,key_caves,top_racer --debriefs results/access/assist-live-muse-<date>.json

  * first sight: 3 frames + the title -> a drafted controls card (refused if it breaks the engine's card rules) -> a probe on the game in
    memory -> the learned card; scored by the share of the real card's keys found, and the keys it invented that the probe dropped;
  * debriefs: for each live-assist part log, Muse Wonder words the counted facts; scored by how many texts passed the number check.
Costs are priced at Muse Wonder's own rates."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

from bench import arena_run as ar
from bench.access_bench import _commit

ROOT = Path(__file__).resolve().parents[1]
TITLES = {"maze_chase": "Maze Chase", "key_caves": "Key Caves", "top_racer": "Top Racer", "action_quest": "Action Quest",
          "ray_maze": "Ray Maze", "tiny_kingdom": "Tiny Kingdom"}


def first_sight_game(brain, game_key: str, engine: Path) -> dict:
    import controls
    import numpy as np

    from playfellow_coop.first_sight import FirstSightError, draft_card, key_recall, probe

    real = controls.load_card(engine / "controls" / f"arena_{game_key}.yaml")
    game = ar.load_game(game_key, 0)
    frames = []
    for _ in range(3):
        frames.append(game.render())
        for _ in range(5):
            game.step(None)
    row = {"game": game_key, "title": TITLES.get(game_key, game_key)}
    try:
        card, info = draft_card(brain, frames, row["title"])
    except FirstSightError as error:
        return {**row, "drafted": False, "error": str(error)[:200], "recall": 0.0}
    row.update({"drafted": True, "genre": info["genre"], "goal": info["goal"], "cost_usd": info["cost_usd"],
                "drafted_keys": sorted({k for a in card.actions.values() for k in a.keys}), "draft_recall": key_recall(card, real)})
    play = ar.load_game(game_key, 1)
    try:
        learned, report = probe(card, lambda k: play.step(k), lambda: np.asarray(play.render().convert("RGB")), idle=lambda: play.step(None))
        row.update({"learned_keys": sorted({k for a in learned.actions.values() for k in a.keys}), "recall": key_recall(learned, real),
                    "probe": report})
    except FirstSightError as error:
        row.update({"learned_keys": [], "recall": 0.0, "probe_error": str(error)[:200]})
    real_keys = {k for a in real.actions.values() for k in a.keys}
    row["invented_keys_dropped"] = sorted(set(row["drafted_keys"]) - set(row["learned_keys"]) - real_keys)
    row["real_keys"] = sorted(real_keys)
    return row


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--games", default="maze_chase,key_caves,top_racer")
    ap.add_argument("--debriefs", default="")
    ap.add_argument("--engine", type=Path, default=Path(os.environ.get("PLAYFELLOW_ENGINE", "")))
    args = ap.parse_args(argv)
    from playfellow_coop.debrief import Debrief, facts_from, wonder_brain

    key = os.environ["MODEL_API_KEY"]
    sight = [first_sight_game(wonder_brain(key), g, args.engine) for g in args.games.split(",") if g]
    for r in sight:
        print(f"first sight {r['game']}: drafted={r['drafted']} genre={r.get('genre')} recall={r.get('recall')} learned={r.get('learned_keys')} real={r.get('real_keys')}", flush=True)
    debriefs = []
    if args.debriefs:
        rows = json.loads(Path(args.debriefs).read_text(encoding="utf-8"))["parts"]
        writer = Debrief(wonder_brain(key))
        for i in range(0, len(rows), 2):  # two parts per pretend session
            log = [{"request": r["request"], "done": r["model_said_done"], "done_by": "model_said" if r["model_said_done"] else "",
                    "turns": r["turns"], "actions": r["turns"], "ai_calls": r["turns"], "seconds": 0} for r in rows[i:i + 2]]
            for language in ("english", "arabic"):
                out = writer.write(facts_from(log, refused=0, f12=False), language)
                debriefs.append({"language": language, **out})
                print(f"debrief {language}: {out['source']} {out['text'][:90]!r}", flush=True)
    cost = sum(r.get("cost_usd", 0) or 0 for r in sight) + sum(d.get("cost_usd", 0) or 0 for d in debriefs)
    result = {"schema": "pf-wonder-live/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "model": "muse-wonder-1.0", "first_sight": sight,
              "first_sight_mean_recall": round(sum(r.get("recall", 0) for r in sight) / len(sight), 4) if sight else None,
              "debriefs": debriefs, "debriefs_passed_number_check": sum(d["source"] == "muse-wonder" for d in debriefs),
              "cost_usd": round(cost, 4),
              "honesty": "First sight is scored against the games' real cards, which the model never saw. Our own simple games."}
    out = ROOT / "results" / "wonder" / f"wonder-live-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + "\n", encoding="utf-8")
    print(f"mean recall {result['first_sight_mean_recall']}, debriefs passed {result['debriefs_passed_number_check']}/{len(debriefs)}, cost ${cost:.4f}\nwrote {out}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
