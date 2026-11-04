"""The skill catalogue for platformers and metroidvanias, Rayman Legends first. Same families and honest marks as the racing one.

Status words: built = code exists, is called by the run loop and has offline tests; none of these has played a real game yet.
known = researched, not built. unverified = the fact itself still needs a source (see results/platform/research-1.md).
"""
from __future__ import annotations

SKILLS = [
    # name, family, what it does, status
    ("camera motion", "pre-skill", "how far and which way the view moved, from pixels", "built"),
    ("sprint and run", "pre-skill", "holds run, and sprint when the card has a key", "built"),
    ("blocked: jump, jump higher, back off", "pre-skill", "camera stops while running: tries in that order, then notes the wall", "built"),
    ("gap jump with hold", "pre-skill", "no ground ahead: jump and hold, which rises and hovers where the game allows it", "built (weak on busy art)"),
    ("attack while running", "pre-skill", "a tap every so often: cages and enemies in the path", "built (timed, not aimed)"),
    ("pick-ups above the path", "pre-skill", "yellow pick-ups ahead and above: a jump to reach them", "built (colour rule, not checked on a real game)"),
    ("death and fade recovery", "pre-skill", "lets go on a fade, counts it, waits, goes on more carefully", "built"),
    ("keyboard door", "pre-skill", "keys only in front, only allowed keys, all released, F12 and F9", "built"),
    ("controls from the card", "pre-skill", "keys come from the game's controls card or arguments", "built"),
    ("level map from motion", "learned skill", "cells visited, furthest point, rooms joined", "built"),
    ("blocked-way memory", "learned skill", "walls kept with a reason, offered again when an ability arrives", "built"),
    ("route back", "learned skill", "shortest list of rooms to a remembered place", "built (not yet used to steer)"),
    ("boss cue memory", "learned skill", "which change on screen came before which hit, across attempts", "built (not yet called by the run loop)"),
    ("boss dodge choice", "learned skill", "tries each dodge once, then the best record", "built (not yet called by the run loop)"),
    ("boss openings", "learned skill", "attacks after cues that drew no punishment", "built (not yet called by the run loop)"),
    ("widget lines and status", "command-skill", "says what it does and what it waits for", "built"),
    ("stop and hand over", "command-skill", "F12, F9, voice, typing", "built"),
    ("reading on-screen hints", "AI-skill", "'[W] Open' style prompts and Murfy prompts, read by the vision model", "known, not built"),
    ("menus and gallery", "AI-skill", "title to any level by reading the screen", "known, not built"),
    ("seeing enemies", "AI-skill", "SAM names enemies ahead, a tracker follows them", "known, not built"),
    ("wall jump", "pre-skill", "leap between walls", "known, not built"),
    ("wall run", "pre-skill", "run up curved walls at speed", "known, not built (unverified)"),
    ("air kick and hover cancel", "pre-skill", "cancel the kick with a hover to stall or kick again", "known, not built"),
    ("ground pound", "pre-skill", "attack down in the air", "known, not built (unverified)"),
    ("charged punch", "pre-skill", "hold attack", "known, not built (unverified)"),
    ("rope swing", "pre-skill", "hang and release with momentum", "known, not built (unverified)"),
    ("Teensy cages", "pre-skill", "find and break cages, 10 a level", "known, not built"),
    ("Lum King timing", "pre-skill", "doubles Lum value for a short time", "known, not built (unverified)"),
    ("heart management", "pre-skill", "a heart absorbs one hit", "known, not built (unverified)"),
    ("music levels", "pre-skill", "jumps timed to the beat", "known, not built"),
    ("chase levels", "pre-skill", "the screen pushes the player: never stop", "known, not built"),
    ("swimming", "pre-skill", "free movement underwater", "known, not built"),
    ("Invaded levels", "pre-skill", "speed versions of levels", "known, not built"),
    ("save-room use", "pre-skill", "return to a save on low health (metroidvania)", "known, not built"),
    ("hit and retreat", "pre-skill", "attack in openings, then back off (metroidvania)", "known, not built"),
    ("dash through attacks", "pre-skill", "invulnerable frames on a dash (metroidvania)", "known, not built (unverified)"),
    ("false walls", "pre-skill", "attack dead ends for hidden ways (metroidvania)", "known, not built"),
    ("upgrade spending", "AI-skill", "spend currency on maps and upgrades (metroidvania)", "known, not built"),
]

WIRING = {  # skill -> the file and the name that does the work
    "camera motion": ("sight.py", "def camera_shift"), "sprint and run": ("runner.py", "self.keys.sprint"),
    "blocked: jump, jump higher, back off": ("runner.py", "def _unstick"), "gap jump with hold": ("runner.py", "gap_ahead(frame)"),
    "attack while running": ("runner.py", "attack_every"), "pick-ups above the path": ("runner.py", "collectibles(frame)"),
    "death and fade recovery": ("runner.py", "self.deaths"), "keyboard door": ("live.py", "window.hands(allowed)"),
    "controls from the card": ("live.py", "Keys(jump="), "level map from motion": ("world.py", "def move"),
    "blocked-way memory": ("world.py", "def note_blocked"), "route back": ("world.py", "def route"),
    "boss cue memory": ("bosses.py", "def record"), "boss dodge choice": ("bosses.py", "def choose"), "boss openings": ("bosses.py", "def attack_now"),
    "widget lines and status": ("live.py", "set_status"), "stop and hand over": ("live.py", "HANDOVER.exists()"),
}


def as_markdown() -> str:
    rows = ["# Skill catalogue: platformers and metroidvanias, Rayman Legends first", "",
            "None of these has played a real game yet. Facts marked unverified still need a source.", "",
            "| skill | family | what it does | status |", "|---|---|---|---|"]
    rows += [f"| {n} | {f} | {d} | {s} |" for n, f, d, s in SKILLS]
    return "\n".join(rows) + "\n"
