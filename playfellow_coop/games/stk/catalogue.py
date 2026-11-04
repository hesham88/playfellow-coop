"""The skill catalogue: before every new game or difficulty, the buddy lists every skill it needs for it, where each came from,
whether it is built and how it has done, plus the track notes it learned from its own races. Shown in the widget and saved
next to the pre-skills (catalogue-<difficulty>.md / .json), so each step up starts from everything learned so far.

Track notes (`note_race`): after a race, the drive log is read for trouble spots - where on the driveline the kart stalled,
reversed, was rescued, or jumped (fell off and was put back) - and the spots are kept per track. In the next race on that
track the driver comes into each noted spot prepared: a nearer aim point, a wider line, a short lift before it (drive.py).
"""
from __future__ import annotations

import json
import time
from pathlib import Path

from playfellow_coop.games.stk.paths import PRESKILLS

DIFFICULTIES = ("novice", "intermediate", "expert", "supertux")

SKILLS = [
    # name, area, where it came from, what it does, status (built / partly / off until proven / known, not built)
    ("controls card", "controls", "the game's own input.xml", "every key the buddy presses is a key the player really has bound", "built"),
    ("read lesson boxes", "reading", "tutorial + help pages (Muse vision)", "reads on-screen instructions and acts on them at the right moment", "built"),
    ("menu routes", "menus", "explored 3 Nov (Muse vision + tooltip reader)", "reaches races and menus with the keyboard, offline only", "partly"),
    ("race gate", "safety", "built 3 Nov", "no race key until the race map is on screen; never drives a menu", "built"),
    ("hand-over (F9) and stop (F12)", "safety", "owner request 3 Nov", "F9: the buddy lets go and waits; F12: everything stops", "built"),
    ("rocket start", "start", "help page + guide: accelerate at 'Set!'", "full throttle exactly at 'Set!' (countdown read locally)", "built"),
    ("kart class from the game's data", "physics", "kart_characteristics.xml + each kart.xml (4 Nov research)", "light / medium / heavy: turning circle per speed decides how fast a bend can be taken", "built"),
    ("heavy kart choice", "physics", "kart_characteristics.xml: heavy = top speed x1.05", "picks a heavy kart (Puffy) on the kart screen; its minimap look is made from the game's own icon file", "built (not yet proven in a race)"),
    ("item line from the track's data", "items", "the track's scene.xml + item.cpp pick-up radius 1.1 m (4 Nov research)", "plans the line through side gift boxes and nitro cans, 2.2 m clear of every fixed banana", "built (not yet proven in a race)"),
    ("keep a held power", "items", "powerup.cpp: collect mode 'new' replaces the held power", "with a power in hand, gift boxes stop pulling the line", "built (not yet proven in a race)"),
    ("no counter-steer after a skid", "boosts", "skidding.cpp: the game straightens the kart on release", "no steering key for 0.2 s after letting go of a skid", "built (not yet proven in a race)"),
    ("minimap localisation", "driving", "the game's quads.xml + learned icon look", "knows where the kart is on the track, 20 times a second", "built"),
    ("driveline pursuit", "driving", "the game's own driveline", "follows the road; looks further at speed", "built"),
    ("calm straights", "driving", "owner feedback 3 Nov", "holds the wheel still on straights (no weaving)", "built"),
    ("speed for the bend ahead", "driving", "owner 3 Nov + turn radius in the game's data (4 Nov)", "lifts only when the bend is tighter than the kart's turning circle at that speed; never on Abyss (bends 28 m+)", "built (rule changed 4 Nov, not yet proven in a race)"),
    ("outside line in tight bends", "driving", "race notes 3 Nov (inner-wall stalls)", "aims a little wide of the centre line in tight bends", "built"),
    ("track notes", "learning", "its own race notes", "comes into its noted trouble spots slower and wider", "built"),
    ("nitro on straights", "boosts", "tutorial lesson", "taps nitro when the road ahead is straight", "built"),
    ("nitro tapping on a fading boost", "boosts", "owner's guide", "tap nitro as a skid or zipper boost fades to hold top speed", "built (not yet proven in a race)"),
    ("skid boost (yellow +16.2 km/h, red +23.4 km/h)", "boosts", "tutorial + owner's guide + skidding.cpp", "bends driven >= 1.1 s get a yellow, >= 3.3 s a red; steered with the game's three skid levels (outward 0.2 / none 0.5 / inward 0.8 of full lock); released at the bend's end", "built (not yet proven in a race)"),
    ("brake-drift in hairpins", "boosts", "owner's guide", "tap brake while drifting to pivot in tight hairpins", "partly (brake taps before very sharp bends, no drift)"),
    ("snaking on straights", "boosts", "owner's guide (speedrun)", "chained hop-drifts on straights for repeated boosts", "known, not built (speedrun trick, too risky in races)"),
    ("hop / low-air hop", "airborne", "owner's guide", "tap skid before a crest to land sooner", "known, not built (needs crest detection)"),
    ("zipper buffering", "boosts", "owner's guide", "do not stack a zipper item or nitro on a ground zipper", "known, not built"),
    ("reverse off walls", "recovery", "owner request 3 Nov", "backs off a wall with the wheel turned, before any rescue", "built"),
    ("rescue", "recovery", "tutorial lesson", "Rescue when stalled again, lost, or going nowhere", "built"),
    ("focus + pause recovery", "recovery", "races 3 Nov (game paused itself)", "takes the front back and leaves the pause menu", "built"),
    ("item hunt (SAM)", "items", "owner request; SAM 3.1 + tracker", "picks one reachable gift box or nitro on gentle road, then the next", "built (gentle pulls only)"),
    ("obstacle avoidance (SAM)", "items", "owner request; SAM 3.1 + tracker", "steers around bananas and crates in the path", "built (gentle)"),
    ("aimed firing (SAM)", "items", "owner request; SAM 3.1 + tracker", "fires only with an opponent lined up, never at itself", "built"),
    ("held power reading", "items", "the game's own icon files", "knows which power and how many charges it holds, 25 ms a look", "built"),
    ("power rules per item", "items", "the game's own AI + data", "each power used at its moment; never thrown just to empty the hand", "built (not yet proven in a race)"),
    ("rear-firing (look back + fire)", "items", "help page + owner's guide", "fire backwards when leading and a power has been held too long", "partly (no sight of karts behind)"),
    ("shielding (bubblegum) and swatter", "items", "help page + owner's guide", "shield or swat with an opponent very close", "partly (attachments on the kart are not read yet)"),
    ("item blocking (drop behind)", "items", "owner's guide", "drop a banana behind to block projectiles", "known, not built"),
    ("wall riding (magnet sections)", "tracks", "owner's guide", "ride gravity surfaces on Cocoa Temple / STK Enterprise", "known, not needed on Abyss"),
    # --- added 3 Nov evening: the wider racing and gaming skill set (owner: "fill the catalogue with all kinds of skills") ---
    ("predictive drift", "boosts", "owner + tutorial + guide; bends from the driveline (4 Nov)", "skids planned from the map's bends: enters a quarter second before, one skid per bend per lap", "built (rewritten 4 Nov, not yet proven in a race)"),
    ("fast banana eye", "items", "owner 3 Nov (SAM too slow for bananas)", "local yellow detector, 10 looks a second, dodges at once", "built"),
    ("learning at each lap end", "learning", "owner: 'act in real time while learning in parallel'", "a parallel thread adds the lap's trouble spots to the next lap", "built"),
    ("steering damping + speed schedule", "driving", "kart simulator (sim.py), 3 Nov", "steers on where the error is going; gentler at speed", "built (simulator-proven)"),
    ("racing line (out-in-out)", "driving", "racing genre", "wide entry, apex, wide exit for more speed through bends", "partly (outside aim in tight bends)"),
    ("braking points", "driving", "racing genre", "brake before the bend, not in it", "partly (speed for the bend ahead)"),
    ("slipstream / drafting", "racing", "racing genre", "tuck in behind a kart on a straight for a tow, then pass", "known, not built"),
    ("overtaking", "racing", "racing genre", "pick the side, pass on a straight or the inside of a bend", "known, not built"),
    ("defending", "racing", "racing genre", "hold the inside line when a kart is close behind", "known, not built (needs a look behind)"),
    ("position awareness", "racing", "the game's HUD", "reads its place from the standings ring; leaders keep leader-hitting powers", "built"),
    ("shortcuts", "tracks", "track exploration", "learned alternative routes per track", "known, not built"),
    ("jumps and ramps", "airborne", "racing genre", "straight and centred before a jump, no steering in the air", "known, not built"),
    ("track memorisation", "learning", "its own races", "per-track notes of trouble spots and good lines", "built (trouble spots)"),
    ("comeback plan", "racing", "racing genre", "when far behind: maximise items and nitro, take risks", "known, not built"),
    ("results honesty check", "safety", "3 Nov correction", "a win counts only if the results screen shows 1st and the right difficulty", "built"),
    ("command: menu / restart / race X", "commands", "owner 3 Nov", "voice or text makes the buddy go to the menu, restart, or start a race", "built"),
    ("command: stop / wait / take it back", "commands", "owner 3 Nov", "F12 / F9 / voice / text", "built"),
    ("command: driving tips", "commands", "owner 3 Nov", "more nitro / more items / dodge more / calmer, for this race", "built"),
    ("never silent", "commands", "owner 3 Nov", "the widget always says what the buddy is doing or waiting for", "built"),
]

FAMILY = {"controls": "pre-skill", "start": "pre-skill", "physics": "pre-skill", "driving": "pre-skill", "boosts": "pre-skill",
          "recovery": "pre-skill", "airborne": "pre-skill", "racing": "pre-skill", "tracks": "pre-skill", "safety": "pre-skill",
          "menus": "AI-skill", "reading": "AI-skill", "items": "AI-skill", "commands": "command-skill", "learning": "learned skill"}

# skill -> the file and the name that does the work, for every skill marked built (tests/test_stk_wiring.py checks they exist and are called)
WIRING = {
    "controls card": ("card.py", "Card"), "read lesson boxes": ("instructions.py", "parse_answer"), "race gate": ("live.py", "gate_seen"),
    "hand-over (F9) and stop (F12)": ("widget.py", "hand_over"), "rocket start": ("countdown.py", "Countdown"),
    "kart class from the game's data": ("drive.py", "def turn_radius"), "minimap localisation": ("minimap.py", "IconModel"),
    "heavy kart choice": ("mission.py", "kart_info("), "item line from the track's data": ("drive.py", "def plan_line"),
    "keep a held power": ("drive.py", "self.held_power is None"), "no counter-steer after a skid": ("drive.py", "no_steer_until"),
    "driveline pursuit": ("drive.py", "def _steer"), "calm straights": ("drive.py", "straight_road"),
    "speed for the bend ahead": ("drive.py", "def road_radius_ahead"), "outside line in tight bends": ("drive.py", "outside"),
    "track notes": ("catalogue.py", "def note_race"), "nitro on straights": ("drive.py", "nitro_every"),
    "nitro tapping on a fading boost": ("drive.py", "NITRO_OVERLAP"), "skid boost (yellow +16.2 km/h, red +23.4 km/h)": ("drive.py", "SKID_RED_TIME"),
    "reverse off walls": ("drive.py", "def _reverse"), "rescue": ("drive.py", "def _rescue"), "focus + pause recovery": ("live.py", "refocused_at"),
    "item hunt (SAM)": ("items.py", "def plan"), "obstacle avoidance (SAM)": ("items.py", "OBSTACLES"), "aimed firing (SAM)": ("powers.py", "def decide"),
    "predictive drift": ("drive.py", "def bend_at"), "fast banana eye": ("fasteye.py", "def bananas"), "learning at each lap end": ("live.py", "def learn_lap"),
    "steering damping + speed schedule": ("drive.py", "speed_gain"), "track memorisation": ("catalogue.py", "def load_notes"),
    "results honesty check": ("mission.py", "finish_and_read"), "command: menu / restart / race X": ("act.py", "def main"),
    "command: stop / wait / take it back": ("widget.py", "def command"), "command: driving tips": ("live.py", "read_tune"),
    "never silent": ("widget.py", "def status_text"), "held power reading": ("held.py", "class HeldPower"), "power rules per item": ("powers.py", "def decide"),
    "position awareness": ("held.py", "def read_place"),
}

RESEARCH = Path(__file__).with_name("research_skills.json")  # 96 skills from the 4 Nov research (source code + game data + guides)
# researched skill id -> the catalogue skill above whose code does it (only these count as built; the rest are researched)
RESEARCH_BUILT = {
    "start_set_press": "rocket start", "start_no_ready_press": "rocket start", "steer_dead_band": "calm straights",
    "steer_no_counter": "no counter-steer after a skid", "no_brake_wide_corner": "speed for the bend ahead",
    "brake_tight_corner": "speed for the bend ahead", "skid_enter": "predictive drift", "corner_plan": "predictive drift",
    "skid_three_level": "skid boost (yellow +16.2 km/h, red +23.4 km/h)", "skid_release_yellow": "skid boost (yellow +16.2 km/h, red +23.4 km/h)",
    "skid_hold_red": "skid boost (yellow +16.2 km/h, red +23.4 km/h)", "skid_no_yellow_in_red": "skid boost (yellow +16.2 km/h, red +23.4 km/h)",
    "nitro_tap": "nitro on straights", "nitro_on_fade": "nitro tapping on a fading boost",
    "nitro_collect_line": "item line from the track's data", "gift_collect_line": "item line from the track's data",
    "banana_avoid_data": "item line from the track's data", "gift_skip_keep": "keep a held power", "banana_avoid_seen": "fast banana eye",
    "menu_kart_heavy": "heavy kart choice", "read_place": "position awareness", "read_power": "held power reading",
    "rescue_key": "rescue", "reverse_unstick": "reverse off walls", "track_memory": "track notes", "lap_learn": "learning at each lap end",
    "fall_edge_margin": "track notes", "menu_read_press": "menu routes", "menu_difficulty": "menu routes",
    "cmd_left_right": "command: driving tips", "cmd_straight": "command: driving tips", "cmd_nitro": "command: driving tips",
    "cmd_drift": "command: driving tips", "cmd_brake": "command: driving tips", "narrate_plan": "never silent",
    "narrate_result": "results honesty check", "bowling_fire": "power rules per item", "cake_fire": "power rules per item",
    "swatter_use": "power rules per item", "bubble_shield": "power rules per item", "zipper_item": "power rules per item",
}


def research_rows() -> list[dict]:
    """The researched skills, each marked built (with the catalogue skill doing it) or researched (not built yet)."""
    try:
        rows = json.loads(RESEARCH.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    status = {n: st for n, _, _, _, st in SKILLS}
    for r in rows:
        by = RESEARCH_BUILT.get(r["id"])
        r["status"] = f"built as '{by}' ({status.get(by, '?')})" if by else "researched, not built"
    return rows


DIFFICULTY_NOTES = {
    "novice": "AI karts slow; clean laps win.",
    "intermediate": "AI karts faster and use items: the start boost, skid boosts, nitro and clean bends now decide it; fewer stalls.",
    "expert": "AI karts near top speed: every wall costs the race; the item hunt and aimed firing matter.",
    "supertux": "AI karts at full speed with rubber-banding: needs the cleanest lines and every boost.",
}


def note_race(drive_log: Path, track_id: str) -> dict:
    """Trouble spots from one race's drive log, merged into the track's notes file. Returns the notes."""
    data = json.loads(drive_log.read_text(encoding="utf-8"))
    log = data.get("log", [])
    ticks = [e for e in log if len(e) == 8]
    by_time = sorted(ticks, key=lambda e: e[0])
    spots: list[dict] = []
    for event in (e for e in log if len(e) == 4 and e[1] in ("reverse", "rescue")):
        before = [e for e in by_time if e[0] <= event[0]]
        if before:
            spots.append({"index": int(before[-1][3]), "what": event[1], "why": event[3]})
    for a, b in zip(by_time, by_time[1:]):  # a jump of more than 25 m in one look: fell off and was put back
        if abs(b[1] - a[1]) + abs(b[2] - a[2]) > 25 and b[0] - a[0] < 0.3 and a[7] == "seen" and b[7] == "seen":
            spots.append({"index": int(a[3]), "what": "fall", "why": "position jumped"})
    notes_file = PRESKILLS / "tracks" / f"{track_id}.json"
    notes_file.parent.mkdir(parents=True, exist_ok=True)
    try:
        notes = json.loads(notes_file.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        notes = {"track": track_id, "spots": {}, "races": 0}
    for s in spots:
        key = str(s["index"])
        notes["spots"].setdefault(key, {"count": 0, "what": []})
        notes["spots"][key]["count"] += 1
        notes["spots"][key]["what"] = sorted(set(notes["spots"][key]["what"]) | {s["what"]})
    notes["races"] += 1
    result = data.get("result", {})
    notes.setdefault("history", []).append({"at": time.strftime("%Y-%m-%dT%H:%M:%S"), "seconds": result.get("seconds"),
                                            "rescues": result.get("rescues"), "spots": len(spots)})
    notes_file.write_text(json.dumps(notes, indent=1), encoding="utf-8")
    return notes


def load_notes(track_id: str) -> list[int]:
    try:
        notes = json.loads((PRESKILLS / "tracks" / f"{track_id}.json").read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    return sorted(int(k) for k in notes.get("spots", {}))


def build(difficulty: str, track_id: str, wins: dict | None = None) -> list[str]:
    """Write catalogue-<difficulty>.md/.json and return short lines for the widget."""
    wins = wins or {}
    notes = load_notes(track_id)
    rows = [{"skill": n, "family": FAMILY.get(a, "pre-skill"), "area": a, "source": s, "does": d, "status": st} for n, a, s, d, st in SKILLS]
    doc = {"difficulty": difficulty, "track": track_id, "built": time.strftime("%Y-%m-%dT%H:%M:%S"),
           "difficulty_note": DIFFICULTY_NOTES.get(difficulty, ""), "wins_so_far": wins, "track_notes": notes, "skills": rows}
    PRESKILLS.mkdir(parents=True, exist_ok=True)
    (PRESKILLS / f"catalogue-{difficulty}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    lines = [f"# Skill catalogue: {difficulty} on {track_id}", "", DIFFICULTY_NOTES.get(difficulty, ""), "",
             f"Wins so far: {', '.join(f'{k} {v}' for k, v in wins.items()) or 'none'}", "",
             f"Track notes ({track_id}): trouble spots at driveline points {notes or 'none yet'}", "",
             "| skill | family | area | from | what it does | status |", "|---|---|---|---|---|---|"]
    lines += [f"| {r['skill']} | {r['family']} | {r['area']} | {r['source']} | {r['does']} | {r['status']} |" for r in rows]
    researched = research_rows()
    doc["researched"] = researched
    (PRESKILLS / f"catalogue-{difficulty}.json").write_text(json.dumps(doc, indent=1), encoding="utf-8")
    lines += ["", f"## Researched skills ({len(researched)}), 4 Nov", "", "| id | skill | family | area | trigger | keys | status |", "|---|---|---|---|---|---|---|"]
    lines += [f"| {r['id']} | {r['name']} | {r['family']} | {r['area']} | {r['trigger']} | {r['keys_and_timing']} | {r['status']} |" for r in researched]
    (PRESKILLS / f"catalogue-{difficulty}.md").write_text("\n".join(lines) + "\n", encoding="utf-8")
    built = sum(1 for r in rows if r["status"].startswith("built"))
    r_built = sum(1 for r in researched if r["status"].startswith("built"))
    return [f"Skill catalogue for {difficulty}: {len(rows)} skills, {built} built and in use, the rest marked honestly.",
            f"Researched skills: {len(researched)}, {r_built} of them covered by built code, the rest listed as not built yet.",
            DIFFICULTY_NOTES.get(difficulty, ""),
            f"From my last races on {track_id}: {len(notes)} trouble spots noted; I will come into them slower and wider." if notes
            else f"No notes yet on {track_id}; I will write them after this race."]
