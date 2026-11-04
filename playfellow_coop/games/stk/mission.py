"""One SuperTuxKart session with the buddy: the widget glued to the game window, the recording, the menu route and the drive.

    python -m playfellow_coop.games.stk.mission --mission tutorial

The widget runs on the main thread (Qt), docked at the top centre of the game window and following it (windowed, snapped,
full screen), shown in recordings; its bar carries the buddy's latest line. The mission runs on a worker thread. The recorder
is a separate low-priority process that captures only the game window. F12 stops everything and lets go of every key.
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
import threading
import time
from pathlib import Path
from typing import Callable

from playfellow_coop.games.stk import live
from playfellow_coop.games.stk.paths import BUDGET, HOME, KEY_FILE, PRESKILLS as PRESKILLS_HOME, SESSIONS, player_name
from playfellow_coop.games.stk.widget import STOP
from playfellow_coop.games.stk.io import GameWindow, MENU_KEYS

VK_F12 = 0x7B
TRACKS = {"tutorial": "tutorial"}


class Session:  # pragma: no cover - needs a real desktop
    def __init__(self, out: Path, say):
        self.out, self.say = out, say
        self.window = GameWindow()
        self.stop = threading.Event()
        self.results: list[dict] = []
        self.nav = None
        self._grabber = None
        self.read_results = None
        self.sam_marker = None
        self.player = player_name()  # the game's player profile: its row on the results table

    def frame(self, mask_widget: bool = True):
        """The game window now (BGR). With mask_widget, the widget's rectangle at the top centre is blacked out, so a model
        never reads the buddy's own words as part of the game."""
        import mss
        import numpy as np

        from playfellow_coop.overlay.panel import BAR_HEIGHT, BAR_WIDTH, DOCK_TOP

        if self._grabber is None:
            self._grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
        x0, y0, x1, y1 = self.window.client_box()
        image = np.asarray(self._grabber.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3].copy()
        if mask_widget:
            left = (x1 - x0 - BAR_WIDTH) // 2
            image[max(DOCK_TOP - 2, 0):DOCK_TOP + BAR_HEIGHT + 4, max(left - 4, 0):left + BAR_WIDTH + 4] = 0
        return image

    def tap(self, key: str) -> bool:
        if not self.window.focus():
            return False
        return self.window.hands(MENU_KEYS).tap(key)

    def menu(self, steps: list[str], pause: float = 0.35) -> bool:
        """Keyboard-only route through the game's menus (never the mouse; Online and Addons are never entered)."""
        if not self.window.focus():
            self.say("The game is not in front, so I pressed nothing.")
            return False
        hands = self.window.hands(MENU_KEYS)
        for step in steps:
            if step.startswith("wait:"):
                time.sleep(float(step[5:]))
                continue
            key, _, n = step.partition("*")
            for _ in range(int(n or 1)):
                if self.stop.is_set() or not hands.tap(key):
                    return False
                time.sleep(pause)
        return True


LEARNED = PRESKILLS_HOME / "learned.json"


def save_preskills(result: dict) -> None:  # pragma: no cover
    """What the tutorial taught, kept for every later race: the steering direction and the lessons acted on."""
    lessons = sorted({entry[2] for entry in result.get("instructions_obeyed", []) if entry[2] not in ("none", "collect", "steer", "accel")})
    old = load_preskills() or {}
    data = {"steer_sign": result.get("steer_sign", old.get("steer_sign", 1.0)), "lessons": sorted(set(old.get("lessons", [])) | set(lessons)),
            "from": "tutorial", "updated": time.strftime("%Y-%m-%dT%H:%M:%S%z")}
    LEARNED.parent.mkdir(parents=True, exist_ok=True)
    LEARNED.write_text(json.dumps(data, indent=1), encoding="utf-8")


def load_preskills() -> dict | None:  # pragma: no cover
    try:
        return json.loads(LEARNED.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return None


def race_seen(s: Session, track_id: str, icon: Path) -> Callable[[], bool]:  # pragma: no cover
    """The local test that a race on this track is on screen: the learned kart icon matches on that track's minimap."""
    from playfellow_coop.games.stk.minimap import IconModel, MapGeometry
    from playfellow_coop.games.stk.track import Track

    track, model = Track.load(track_id), IconModel.load(icon)

    from playfellow_coop.games.stk.minimap import map_visible

    def seen() -> bool:
        """This track's minimap is on screen: its outline (even with the kart icon hidden behind a lesson box), or the icon."""
        frame = s.frame(mask_widget=False)
        h, w = frame.shape[:2]
        geo = MapGeometry.for_view(track, w, h)
        return map_visible(frame, geo, track) or (model is not None and model.match(frame, geo) is not None)

    return seen


def mission_tutorial(s: Session, reader, guard, icon: Path) -> None:  # pragma: no cover
    s.say("Tutorial: I find it in the menus with the keyboard, checking the screen at each step.")
    if s.nav is None:
        s.say("Menu reading needs the model key; stopping.")
        return
    from playfellow_coop.games.stk.menus import walk_bar

    seen = race_seen(s, "tutorial", icon)
    if seen():
        s.say("The tutorial is already on screen; I carry on from here.")
        ok = True
    else:
        ok = walk_bar("tutorial", s.frame, s.read_label, s.tap, say=s.say)
    if ok:
        deadline = time.monotonic() + 20.0
        while time.monotonic() < deadline and not seen():
            time.sleep(0.5)
        ok = seen()
    if not ok:
        s.say("I could not reach the tutorial from the menus; I pressed no race keys.")
        return
    s.results.append(live.run("tutorial", s.out / "tutorial", max_seconds=360, learn=True, icon_path=icon, say=s.say,
                              reader=reader, guard=guard, stop=s.stop))
    save_preskills(s.results[-1])


def finish_and_read(s: Session, label: str) -> None:  # pragma: no cover
    """After a race: wait for the results table and read the buddy's place off it (the game's word, not the buddy's guess)."""
    if s.results and isinstance(s.results[-1], dict) and s.results[-1].get("stopped_by") == "game_closed":
        return  # no game window, no results table to read
    shots = s.out / "results"
    shots.mkdir(exist_ok=True)
    import cv2

    for attempt in range(8):
        time.sleep(3.0)
        frame = s.frame()
        cv2.imwrite(str(shots / f"{label}-results-{attempt}.png"), frame)
        result = s.read_results(frame, s.player) if s.read_results else {}
        if result.get("results_shown"):
            s.results.append({"results_screen": result, "screenshot": str(shots / f"{label}-results-{attempt}.png")})
            pos = result.get("player_position")
            s.say(f"The results table says I finished {ordinal(pos)}." if pos else "I can see the results table but not my row.")
            return
    s.say("I did not see a results table.")


def ordinal(n) -> str:
    try:
        n = int(n)
    except (TypeError, ValueError):
        return str(n)
    return f"{n}{'th' if 10 <= n % 100 <= 20 else {1: 'st', 2: 'nd', 3: 'rd'}.get(n % 10, 'th')}"


DIFFICULTY_ORDER = ("novice", "intermediate", "expert", "supertux")


def setup_route(s: Session, difficulty: str, seen) -> bool:  # pragma: no cover
    """Main menu to a running Normal Race. The model reads the screens up to the kart choice (it does that reliably); Race
    Setup is then driven with fixed keys learned on 3 Nov (the focus opens on the difficulty row), every key after taking
    the front back, and the race is confirmed by the map check before any race key."""
    from playfellow_coop.games.stk.widget import set_status

    set_status("going through the menus to the race (each step is shown here).")
    ok = s.nav.reach("Get to the Race Setup screen (headings 'Select a difficulty' and 'Select a game mode'). From the main "
                     "menu: Singleplayer (enter), then on the kart screen keep Tux and press enter. If a Paused menu or results "
                     "screen is up, go back to the main menu first. Done (press none) when Race Setup is on screen.", max_steps=14)
    if not ok:
        return False
    from playfellow_coop.games.stk.setup_screen import selected_difficulty

    # the difficulty by sight: look at the gold glow, press toward the target, look again (a blind count left it on Novice)
    for _ in range(14):
        now_on = selected_difficulty(s.frame())
        if now_on == difficulty:
            break
        if now_on is None:
            s.say("I can't see the difficulty row; moving up to it.")
            s.tap("up")
            time.sleep(0.5)
            continue
        s.tap("right" if DIFFICULTY_ORDER.index(difficulty) > DIFFICULTY_ORDER.index(now_on) else "left")
        time.sleep(0.5)
        if selected_difficulty(s.frame()) == now_on:  # the glow did not move: the focus is in the game modes below
            s.say("The focus is on the game modes; moving up to the difficulty row.")
            s.tap("up")
            time.sleep(0.4)
    now_on = selected_difficulty(s.frame())
    if now_on != difficulty:
        s.say(f"The difficulty row shows {now_on}, not {difficulty}; I stop here rather than race the wrong one.")
        return False
    s.say(f"Race Setup: I can see {difficulty.capitalize()} selected. Now Normal Race.")
    # the game mode by its caption (3 Nov: a fixed 'down, left x3' landed on Time Trial): read the words under the mode grid
    # after every key, Enter only on 'Normal Race'; the difficulty glow is re-checked so a stray key never changes it
    def caption() -> str:
        frame = s.frame()
        h, w = frame.shape[:2]
        return s.read_label(frame[int(h * 0.84):int(h * 0.94), int(w * 0.10):int(w * 0.90)]).strip().lower()

    s.tap("down")
    time.sleep(0.6)
    chosen = False
    for _ in range(10):
        words = caption()
        s.say(f"Game mode under the cursor: '{words or 'nothing yet'}'.")
        if "normal race" in words:
            chosen = True
            break
        before = words
        s.tap("left")
        time.sleep(0.6)
        if selected_difficulty(s.frame()) != difficulty:  # the key moved the difficulty instead: put it back, go down
            s.tap("right")
            time.sleep(0.4)
            s.tap("down")
            time.sleep(0.6)
            continue
        if caption() == before:  # first column already: Normal Race is above
            s.tap("up")
            time.sleep(0.6)
    if not chosen or selected_difficulty(s.frame()) != difficulty:
        s.say("I could not put the cursor on Normal Race at the right difficulty; I stop here.")
        return False
    if not s.tap("enter"):
        return False
    time.sleep(2.0)
    # the track by its name (3 Nov: the focus opened on a locked Grand Prix and Enter did nothing): read the caption under
    # the grid, move toward Antediluvian Abyss (the grid's first track), Enter only when the caption names it
    def track_caption() -> str:
        frame = s.frame()
        h, w = frame.shape[:2]
        return s.read_label(frame[int(h * 0.88):int(h * 0.955), int(w * 0.05):int(w * 0.95)]).strip().lower()

    found = False
    for _ in range(10):
        words = track_caption()
        s.say(f"Track under the cursor: '{words or 'nothing yet'}'.")
        if "abyss" in words:
            found = True
            break
        if "locked" in words or "grand prix" in words or not words:
            s.tap("down")  # from the Grand Prix row down into the tracks
        else:
            s.tap("left")  # Abyss is the first track: left until the row starts, then up
            time.sleep(0.6)
            if track_caption() == words:
                s.tap("up")
        time.sleep(0.6)
    if not found:
        s.say("I could not put the cursor on Antediluvian Abyss; I stop here.")
        return False
    s.say("Antediluvian Abyss it is. Start Race.")
    for key, pause in (("enter", 2.0), ("enter", 1.0)):
        if not s.tap(key):
            return False
        time.sleep(pause)
    deadline = time.monotonic() + 30.0
    while time.monotonic() < deadline:
        if seen():
            return True
        time.sleep(0.5)
    return False


def mission_race(s: Session, reader, guard, icon: Path, track_id: str = "abyss", track_name: str = "Antediluvian Abyss") -> None:  # pragma: no cover
    from playfellow_coop.games.stk.catalogue import build, load_notes, note_race

    difficulty = s.difficulty
    learned = load_preskills() or {}
    for line in build(difficulty, track_id, learned.get("wins", {})):  # first the skill catalogue for this difficulty
        if line:
            s.say(line)
    s.say(f"Single-player race: {difficulty.capitalize()}, the game's default kart count, {track_name}, its default laps. I find it in the menus.")
    if s.nav is None:
        s.say("Menu reading needs the model key; stopping.")
        return
    seen = race_seen(s, track_id, icon)
    if s.no_menus:  # the race is being started by hand: wait for it, press nothing in the menus
        deadline = time.monotonic() + 600.0
        while time.monotonic() < deadline and not seen():
            time.sleep(0.5)
        ok = seen()
    else:
        ok = setup_route(s, difficulty, seen)
    if False:
      ok = s.nav.reach(f"Start a single-player Normal Race on '{track_name}' at difficulty {difficulty.capitalize()} with the kart Tux, keeping "
                     "the default number of karts and laps. If a Paused menu or a race results screen is on screen, go back to the main "
                     "menu first (Back to menu / Exit Race). From the main menu: Singleplayer, then Tux on the kart screen (enter), then "
                     f"on the next screen choose the difficulty {difficulty.capitalize()} in the difficulty row first (left/right), then "
                     f"Normal Race, then '{track_name}' (the first track of the grid), then Start Race. Done when the race view is on screen.",
                     confirm=seen, max_steps=40)
    if not ok:
        s.say("I could not reach the race from the menus; I pressed no race keys.")
        return
    s.results.append(live.run(track_id, s.out / track_id, max_seconds=600, learn=False, icon_path=icon, say=s.say,
                              reader=reader, guard=guard, stop=s.stop, preskills=learned, sam_marker=s.sam_marker,
                              notes=load_notes(track_id)))
    finish_and_read(s, track_id)
    notes = note_race(s.out / track_id / "drive-log.json", track_id)  # learn from this race for the next one
    s.say(f"Race notes written: {len(notes['spots'])} trouble spots on {track_id} in my notes now.")
    place = (s.results[-1].get("results_screen") or {}).get("player_position") if s.results and isinstance(s.results[-1], dict) else None
    if place == 1:
        learned.setdefault("wins", {})[difficulty] = f"{track_id} {time.strftime('%Y-%m-%d %H:%M')}"
        LEARNED.write_text(json.dumps(learned, indent=1), encoding="utf-8")
        s.say(f"{difficulty.capitalize()} won. Next difficulty unlocked for me.")


MISSIONS = {"tutorial": mission_tutorial, "race": mission_race}


def main(argv=None):  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--mission", choices=sorted(MISSIONS), required=True)
    p.add_argument("--out", default=str(SESSIONS))
    p.add_argument("--read-key-file", default=None, help="key file for the instruction reader (read in memory only)")
    p.add_argument("--budget-file", default=str(BUDGET))
    p.add_argument("--cap-usd", type=float, default=30.0)
    p.add_argument("--icon", default=str(PRESKILLS_HOME / "icon-kart.png"))
    p.add_argument("--no-record", action="store_true")
    p.add_argument("--no-model", action="store_true", help="no model calls: no menu or instruction reading")
    p.add_argument("--no-menus", action="store_true")
    p.add_argument("--difficulty", default="novice", choices=["novice", "intermediate", "expert", "supertux"])
    a = p.parse_args(argv)

    stamp = time.strftime("%Y%m%d-%H%M%S")
    out = Path(a.out) / f"{a.mission}-{stamp}"
    out.mkdir(parents=True, exist_ok=True)

    from playfellow_coop.games.stk.widget import say_line, widget_running

    window = GameWindow()
    if not widget_running():  # one widget for as long as the buddy has the game, shared by every session
        subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.widget"], creationflags=0x00000008 | 0x00000200)
        time.sleep(2.0)
    transcript = out / "widget-lines.txt"

    def say(text: str) -> None:
        line = f"{time.strftime('%H:%M:%S')} {text}"
        print(line, flush=True)
        with open(transcript, "a", encoding="utf-8") as fh:
            fh.write(line + "\n")
        say_line(text)

    session = Session(out, say)
    session.difficulty = a.difficulty
    session.no_menus = a.no_menus

    reader = None
    if not a.no_model:
        from playfellow_coop.games.stk.brains import load_key, muse_reader
        from playfellow_coop.games.stk.card import Card
        from playfellow_coop.games.stk.instructions import Reader

        key = load_key(Path(a.read_key_file) if a.read_key_file else KEY_FILE)
        if key:
            reader = Reader(muse_reader(key, Path(a.budget_file), a.cap_usd, out / "model-calls.jsonl"), Card.load()).start()
            from playfellow_coop.games.stk.brains import muse_menu_eye
            from playfellow_coop.games.stk.menus import Navigator

            session.nav = Navigator(look=session.frame, ask=muse_menu_eye(key, Path(a.budget_file), a.cap_usd, out / "model-calls.jsonl"),
                                    press=session.tap, say=say)
            from playfellow_coop.games.stk.brains import muse_label_reader

            session.read_label = muse_label_reader(key, Path(a.budget_file), a.cap_usd, out / "model-calls.jsonl")
            from playfellow_coop.games.stk.brains import muse_results_reader

            session.read_results = muse_results_reader(key, Path(a.budget_file), a.cap_usd, out / "model-calls.jsonl")
            from playfellow_coop.budget import DailyBudget
            from playfellow_coop.games.stk.items import PROMPTS
            from playfellow_coop.sam_marks import SamMarker
            from playfellow_coop.tracking import Tracker

            session.sam_marker = SamMarker(key, prompts=PROMPTS, budget=DailyBudget(Path(a.budget_file), a.cap_usd, 20000), tracker=Tracker())
    from playfellow_coop.games.stk.power import PowerGuard

    guard = PowerGuard().start()
    stop_file = out / "stop-recording"
    recorder = None
    if not a.no_record:
        recorder = subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.record", "--out", str(out / f"{a.mission}.mp4"),
                                     "--stop-file", str(stop_file)], creationflags=0x08000000)

    def work():
        try:
            time.sleep(1.5)  # the widget is up and docked before anything moves
            say("Hi, I'm Fello. " + ("I read the game's instructions as they appear." if reader else "Instruction reading is off (no key)."))
            from playfellow_coop.games.stk.widget import set_status
            set_status(f"on the {a.mission} mission ({a.difficulty}); every step is shown here.")
            MISSIONS[a.mission](session, reader, guard, Path(a.icon))
        except Exception as error:
            say(f"Stopped on a problem: {type(error).__name__}: {error}")
        finally:
            time.sleep(2.0)
            stop_file.write_text("stop", encoding="utf-8")
            if reader is not None:
                reader.stop()
            guard.stop()
            from playfellow_coop.games.stk.widget import set_status
            set_status("not driving: the session is over and nothing is pressed; waiting for the next order.")
            (out / "session.json").write_text(json.dumps({"mission": a.mission, "results": session.results}, default=str, indent=1), encoding="utf-8")

    def watch_f12():
        last_widget_check = 0.0
        while not session.stop.is_set():
            if time.monotonic() - last_widget_check > 3.0:  # the widget must stay up the whole time the buddy has the game
                last_widget_check = time.monotonic()
                if not widget_running():
                    subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.widget"], creationflags=0x00000008 | 0x00000200,
                                     stderr=open(HOME / "widget-err.log", "a"))
            if window.key_is_down(VK_F12) or STOP.exists():
                session.stop.set()
            time.sleep(0.1)

    worker = threading.Thread(target=work, name="mission", daemon=True)
    worker.start()
    threading.Thread(target=watch_f12, name="f12", daemon=True).start()
    worker.join()
    if recorder is not None:
        try:
            recorder.wait(timeout=20)
        except subprocess.TimeoutExpired:
            recorder.kill()
    print(json.dumps({"out": str(out)}))


if __name__ == "__main__":
    main()