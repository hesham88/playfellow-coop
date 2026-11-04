"""One recorded Endless Sky run with the widget on the game window: the level the owner set (4 Nov): new pilot, buy a ship, finish James's first
passenger job and get paid, then win one paid bounty.

    python -m playfellow_coop.games.endless_sky.run [--stage all|intro|bounty] [--first Fello] [--last Playfellow]

Proof kept in <PLAYFELLOW_GAME_DIR>/sessions/<stamp>/ (default ~/.playfellow/endless-sky): video + shots, every step's screenshot, events.jsonl (every key, every screen read,
fight numbers), widget lines, the game's save copied at each milestone, result.json. A win is claimed only from the save and the paid dialog on screen.
"""
from __future__ import annotations

import argparse
import json
import os
import shutil
import subprocess
import sys
import time
from pathlib import Path

from playfellow_coop.games.endless_sky.where import GAME_DIR, game_exe  # noqa: E402  (sets the widget's game before it loads)

from playfellow_coop.games.endless_sky import flight  # noqa: E402
from playfellow_coop.games.endless_sky.save import find_job, latest_save, save_time  # noqa: E402
from playfellow_coop.games.endless_sky.session import Session, Stopped, start_widget_process  # noqa: E402
from playfellow_coop.games.stk import widget  # noqa: E402

ROOT = GAME_DIR
EXE = game_exe()
PREFS = Path(os.environ.get("APPDATA", "")) / "endless-sky" / "preferences.txt"
INTRO_DESTINATION = ("Arcturus", "New Greenland")


def start_game() -> subprocess.Popen | None:  # pragma: no cover
    from playfellow_coop.games.stk.io import GameWindow

    try:
        GameWindow("Endless Sky")
        return None
    except LookupError:
        pass
    if not PREFS.exists():  # the game's default is fullscreen: a window keeps the rest of the desktop usable and the widget docked
        PREFS.parent.mkdir(parents=True, exist_ok=True)
        PREFS.write_text('"window size" 1280 860\nfullscreen 0\nvolume 40\n"music volume" 20\n', encoding="utf-8")
    game = subprocess.Popen([str(EXE)], cwd=str(EXE.parent))
    for _ in range(120):
        time.sleep(1)
        try:
            GameWindow("Endless Sky")
            break
        except LookupError:
            continue
    time.sleep(8)  # the first load fills the sprite cache behind the title
    return game


def start_widget() -> None:  # pragma: no cover
    if not widget.widget_running():
        start_widget_process()
        time.sleep(10)


def milestone(s: Session, name: str, facts: dict) -> None:  # pragma: no cover
    path = latest_save()
    if path:
        shutil.copy2(path, s.out / f"save-{name}.txt")
    pilot = s.pilot()
    facts[name] = {"at": time.strftime("%H:%M:%S"), "credits": pilot.credits if pilot else None, "system": pilot.system if pilot else None,
                   "planet": pilot.planet if pilot else None}
    (s.out / "result.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
    s.shot(name)
    s.say(f"Milestone: {name}. Credits {facts[name]['credits']:,}." if pilot else f"Milestone: {name}. (No save yet: this pilot has not landed.)")


def stage_intro(s: Session, facts: dict, first: str, last: str, fresh: bool = True) -> None:  # pragma: no cover
    s.pilot_name = f"{first} {last}"
    if fresh or s.view().name in ("menu", "start"):
        s.new_pilot(first, last)
        s.buy_ship()
        s.settle_panels()
        facts["refit"] = s.refit()
        milestone(s, "ship-bought-and-refitted", facts)
    s.depart()
    s.settle_panels(6)
    system, planet = INTRO_DESTINATION
    if not s.jump(system):
        raise RuntimeError(f"no arrival in {system}")
    s.land(planet)
    s.shot("intro-paid-on-screen")
    s.say("James is delivered and paid: the save will confirm it at the next takeoff.")


def stage_bounty(s: Session, facts: dict, tries: int = 25, held: str = "") -> None:  # pragma: no cover
    """Find a bounty on the job board (each landing brings a new board), check who the target is and how far (the save written at acceptance names them),
    leave anything unfair, hunt a fair one, get paid."""
    if s.settle_panels(6).name == "flight":  # picking up in flight: the board is on the ground, and the job key means jump up here
        s.land()
    job, title, refused = None, "", set()
    if held:  # a job already accepted in an earlier part of the run
        title, job = held, find_job(s.pilot(), held)
    for attempt in range(0 if job else tries):
        before = save_time(s.pilot_name)
        title = s.accept_bounty()
        if title:
            found, pilot = None, None
            for _ in range(16):  # the game writes the file a moment after the panel closes, and a read can catch it half written
                pilot = s.fresh_pilot(before)
                found = find_job(pilot, title, refused) if pilot else None
                if found:
                    break
                time.sleep(0.5)
            here = pilot.system if pilot else ""
            jumps = len(s.stars.route(here, found.npc_systems[0])) if found and found.npc_systems else 99
            why = flight.job_is_fair(found.npc_ships if found else [], jumps)
            s.log("job-checked", title=title, ships=found.npc_ships if found else None, systems=found.npc_systems if found else None, jumps=jumps, refused=why)
            if not why:
                job = found
                break
            if found:
                refused.add(found.description)
            s.say(f"Not this one: {why}. I leave it and look at the next board.")
        else:
            s.say(f"No bounty on this board. Taking off and landing again for a new one (try {attempt + 1}).")
        s.depart()
        s.settle_panels(3)
        s.land()
    if job is None:
        raise RuntimeError("no fair bounty on the boards")
    pilot = s.pilot()
    facts["credits_before_bounty"] = pilot.credits
    facts["intro_done"] = pilot.done("Intro [0]")
    facts["bounty"] = {"title": title, "payment": job.payment, "system": job.npc_systems[0], "target": job.npc_ships, "description": job.description}
    s.say(f"Took the job: {title}, a {job.npc_ships[0]} in {job.npc_systems[0]}, {job.payment:,} credits.")
    s.depart()
    s.settle_panels(3)
    milestone(s, "bounty-accepted", facts)
    if s.here_settled() != job.npc_systems[0] and not s.jump(job.npc_systems[0]):
        raise RuntimeError(f"no arrival in {job.npc_systems[0]}")
    s.say(f"In {job.npc_systems[0]}: hunting. Nearest hostile selected, closing to weapon range, guns on the lead point.")
    stage_hunt(s, facts)


def stage_hunt(s: Session, facts: dict) -> None:  # pragma: no cover
    """The fight itself and the proof after it. A win is only ever said from the game's own message or the money in the save."""
    paid = False
    before = facts.get("credits_before_bounty")
    for _ in range(10):
        outcome = s.fight(lambda: False, seconds=240, patience=45.0)
        s.log("fight-end", outcome=outcome)
        if outcome == "panel":
            seen = s.view()
            s.shot("panel-in-fight")
            text = " ".join(l.text for l in seen.lines)
            if flight.destroyed(text):
                break
            if flight.bounty_paid(text, None, None):
                paid = True
                s.shot("bounty-paid")
                s.say("The game says it: " + next((l.text for l in seen.lines if "eliminated" in l.text.lower()), text[:100]))
                facts["paid_dialog"] = text[:500]
            s.settle_panels(4)
            if paid:
                break
            continue
        frame_text = " ".join(l.text for l in s.read())
        if flight.destroyed(frame_text):
            break
        if outcome == "retreat":
            s.fly_until(s.landed, "The retreat", 60, fight_back=False)
            if s.landed():
                s.settle_panels()
                s.depart()
                s.settle_panels(3)
            continue
        break
    final = " ".join(l.text for l in s.read())
    if flight.destroyed(final):
        facts["outcome"] = "LOSS: the ship was destroyed"
        s.shot("ship-destroyed")
        s.say("I lost: my ship was destroyed. No bounty paid.")
        (s.out / "result.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
        raise RuntimeError("the ship was destroyed")
    s.land()
    s.depart()  # leaves through the game's save path, so the proof below is the game's own record
    s.settle_panels(3)
    s.land()
    pilot = s.pilot()
    facts["credits_after_bounty"] = pilot.credits if pilot else None
    facts["paid_seen"] = paid
    facts["win"] = bool(paid and flight.bounty_paid("", before, pilot.credits if pilot else None))
    facts["outcome"] = "WIN: the game named the target eliminated and the money is in the save" if facts["win"] else "NOT PROVEN: see the numbers"
    milestone(s, "bounty-finished", facts)
    s.say(facts["outcome"])


def main(argv=None) -> None:  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--stage", default="all", choices=["all", "intro", "bounty", "hunt"])
    p.add_argument("--first", default="Fello")
    p.add_argument("--last", default="Playfellow")
    p.add_argument("--keep-pilot", action="store_true")
    p.add_argument("--job", default="", help="the title of a bounty the pilot already holds")
    a = p.parse_args(argv)
    widget.STOP.unlink(missing_ok=True)
    widget.HANDOVER.unlink(missing_ok=True)
    out = ROOT / "sessions" / f"{a.stage}-{time.strftime('%Y%m%d-%H%M%S')}"
    out.mkdir(parents=True, exist_ok=True)
    start_game()
    start_widget()
    s = Session(out, place=a.stage in ("all", "intro"))
    stop_rec = out / "STOP-RECORD"
    root = str(Path(__file__).resolve().parents[3])
    rec = subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.record", "--title", "Endless Sky", "--out", str(out / f"{a.stage}.mp4"),
                            "--stop-file", str(stop_rec), "--fps", "12", "--shot-every", "10"],
                           env=dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (root, os.environ.get("PLAYFELLOW_ENGINE", "")) if p)), cwd=root)
    facts: dict = {"stage": a.stage, "started": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "rules": "screen and keyboard only, no save or data edits"}
    try:
        if a.stage in ("all", "intro"):
            stage_intro(s, facts, a.first, a.last, not a.keep_pilot)
        if a.stage == "bounty":
            s.pilot_name = f"{a.first} {a.last}"
        if a.stage in ("all", "bounty"):
            stage_bounty(s, facts, held=a.job)
        if a.stage == "hunt":  # picks up a fight in progress, for trying changes to the fight without flying there again
            s.pilot_name = f"{a.first} {a.last}"
            stage_hunt(s, facts)
        s.say("This run is over. Everything is in the session folder.")
    except Stopped:
        facts["stopped"] = "owner pressed stop"
    except Exception as exc:
        facts["error"] = f"{type(exc).__name__}: {exc}"
        s.say(f"I got stuck: {exc}")
        s.shot("stuck")
        raise
    finally:
        s.hands.release_all()
        stop_rec.write_text("stop", encoding="utf-8")
        (out / "result.json").write_text(json.dumps(facts, indent=1), encoding="utf-8")
        if widget.FEED.exists():
            shutil.copy2(widget.FEED, out / "widget-lines.txt")
        rec.wait(timeout=30)


if __name__ == "__main__":
    main()
