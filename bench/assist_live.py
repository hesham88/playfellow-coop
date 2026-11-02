"""The assist with a real model: the application's own requests, and is the model's "done" true?

    MODEL_API_KEY=... python -m bench.assist_live --brain muse --seeds 2 --max-usd 1.5
    OPEN_BRAIN_API_KEY=... python -m bench.assist_live --brain open --seeds 2 --max-usd 0.5

It runs the real session loop (`session.play_session`) with the hand-over, the assist and the planner's done rule, on a game in memory
(a virtual screen: no window, no key reaches the PC). The player starts with the controls and says one request from the application;
the buddy takes that part; the controls come back when the model says the part is done or the part's turn limit is reached.

At each hand-back two things are recorded: did the model say done, and do the game's own numbers say the part was done? From them:
  * done-claim precision: of the parts the model called done, how many really were (a false "done" leaves the player in a bad spot);
  * parts really done, and parts the model missed (done, but it kept going until the limit).
Every key goes through the card check; a key the card does not have is counted as a breach (must be 0)."""
from __future__ import annotations

import argparse
import datetime
import json
import os
from pathlib import Path

from bench import arena_run as ar
from bench.access_bench import _commit, wilson

OUT = Path(__file__).resolve().parents[1] / "results" / "access"
PART_TURNS = 12
# (game, the request as the player says it, the game's own truth that the part is done, from the progress at the request and now)
TASKS = [
    ("lane_dash", "grab the coins", lambda a, b: b["coins"] - a["coins"] >= 3),
    ("maze_chase", "grab the coins on the left", lambda a, b: a["coins_left"] - b["coins_left"] >= 2),
    ("key_caves", "get me past this jump", lambda a, b: b["room"] > a["room"] or (b["has_boots"] and not a["has_boots"])),
    ("key_caves", "take me to the door", lambda a, b: b["room"] > a["room"] or (b["door_open"] and not a["door_open"])),
    ("ray_maze", "take me to the door", lambda a, b: bool(b.get("exit_open")) and b["hits"] > a["hits"] or bool(b.get("escaped"))),
]


def part(game_key: str, request: str, truth, seed: int, brain, engine_dir: Path, part_turns: int = PART_TURNS) -> dict:
    import controls
    import settings as engine_settings
    from brain.prompts import system_prompt
    from memory import Memory
    from safety import Safety

    from playfellow_coop import session
    from playfellow_coop.__main__ import assist_system
    from playfellow_coop.assist import Assist, DoneSpotter, VerifiedDone
    from playfellow_coop.handover import HandOver
    from playfellow_coop.stage_timer import StageTimer
    from playfellow_coop.voice import CommandQueue

    game = ar.load_game(game_key, seed)
    card = controls.load_card(engine_dir / "controls" / f"arena_{game_key}.yaml")
    cfg = engine_settings.Settings(look_every_seconds=0.0, max_actions_per_step=4, image_width=480, goal=getattr(game, "goal", "") or engine_settings.Settings().goal)
    parts = type("Parts", (), {})()
    if hasattr(brain, "set_actions"):  # exactly as the command line does with --assist: the card's actions and room for "done"
        brain.set_actions(card.actions)
    if hasattr(brain, "set_done_flag"):
        brain.set_done_flag(True)
    parts.brain = DoneSpotter(brain)
    parts.card, parts.screen, parts.hands = card, ar.VirtualScreen(game), ar.VirtualHands(game, card)
    parts.safety, parts.memory = Safety(60, part_turns + 5), Memory(cfg.memory_steps)
    handover = HandOver(parts.hands, parts.safety)
    check = VerifiedDone(grab=game.render)  # as the command line does: a claim counts after a second look at before and now
    parts.assist = Assist(max_turns=part_turns, done=check)
    queue, state = CommandQueue(), {"tick": 0, "p0": None}

    def wait(_seconds):
        state["tick"] += 1
        if state["tick"] == 1:
            state["p0"] = dict(game.progress())
            queue.put(request)
            return False
        return bool(parts.assist.log) or game.done or state["tick"] > part_turns + 5

    usage_before = 0.0
    session.play_session(parts, cfg, assist_system(system_prompt(cfg, card)), StageTimer(), handover, wait=wait, commands=queue)
    record = dict(parts.assist.log[-1]) if parts.assist.log else {"request": request, "done": False, "ended": "never_started", "turns": 0}
    real = bool(state["p0"] is not None and truth(state["p0"], game.progress()))
    keys = {k for a in card.actions.values() for k in a.keys}
    return {"game": game_key, "seed": seed, "request": request, "model_said_done": record.get("done_by") in ("model_said", "model_verified"),
            "claims_not_confirmed": check.refused,
            "really_done": real, "turns": record.get("turns", 0), "ended": record.get("ended"),
            "breaches": sum(1 for k in parts.hands.pressed if k not in keys), "cost_usd": round(float(getattr(parts, "_spent", 0.0) or 0.0) - usage_before, 6),
            "back_with_player": handover.human_has_controls}


def summarise(rows: list[dict]) -> dict:
    said = [r for r in rows if r["model_said_done"]]
    true_claims = [r for r in said if r["really_done"]]
    real = [r for r in rows if r["really_done"]]
    missed = [r for r in real if not r["model_said_done"]]
    return {"parts": len(rows), "really_done": len(real), "really_done_95": wilson(len(real), len(rows)),
            "model_said_done": len(said), "true_done_claims": len(true_claims),
            "done_claim_precision": round(len(true_claims) / len(said), 4) if said else None,
            "done_claim_precision_95": wilson(len(true_claims), len(said)),
            "missed_done": len(missed), "back_with_player": sum(r["back_with_player"] for r in rows),
            "breaches": sum(r["breaches"] for r in rows), "cost_usd": round(sum(r["cost_usd"] for r in rows), 4),
            "claims_not_confirmed_by_the_second_look": sum(r.get("claims_not_confirmed", 0) for r in rows)}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--brain", choices=["muse", "open"], required=True)
    ap.add_argument("--seeds", type=int, default=2)
    ap.add_argument("--max-usd", type=float, default=1.5)
    ap.add_argument("--engine", type=Path, default=Path(os.environ.get("PLAYFELLOW_ENGINE", "")))
    ap.add_argument("--out", default=None)
    args = ap.parse_args(argv)
    if args.brain == "muse":
        from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain
        brain, model = MuseBrain(DEFAULT_MODEL, os.environ["MODEL_API_KEY"]), DEFAULT_MODEL
    else:
        from bench.open_weights_brain import OPEN_MODEL, OpenWeightsBrain
        brain, model = OpenWeightsBrain(os.environ["OPEN_BRAIN_API_KEY"]), OPEN_MODEL
    rows, spent = [], 0.0
    for seed in range(args.seeds):
        for game_key, request, truth in TASKS:
            if spent >= args.max_usd:
                print(f"cap reached at ${spent:.4f}: stopping before the next part")
                break
            row = part(game_key, request, truth, seed, brain, args.engine)
            rows.append(row)
            spent += row["cost_usd"]
            print(f"{game_key:11} seed {seed} '{request}': model said done={row['model_said_done']} really done={row['really_done']} "
                  f"turns={row['turns']} ended={row['ended']} ${row['cost_usd']:.4f}", flush=True)
    result = {"schema": "pf-assist-live/1", "written": datetime.datetime.now().astimezone().isoformat(timespec="seconds"), "commit": _commit(),
              "brain": args.brain, "model": model, "part_turns": PART_TURNS, "summary": summarise(rows), "parts": rows,
              "honesty": "A game in memory (virtual screen), not a window. 'Really done' is judged by the game's own progress numbers; "
                         "'model said done' is the model's word. No disabled player was involved."}
    out = Path(args.out) if args.out else OUT / f"assist-live-{args.brain}-{datetime.date.today():%Y%m%d}.json"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(json.dumps(result, indent=1) + "\n", encoding="utf-8")
    print(json.dumps(result["summary"]), "\nwrote", out)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
