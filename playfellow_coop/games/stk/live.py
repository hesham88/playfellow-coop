"""The racing pre-skill on the real game window: looks at the minimap 20 times a second, reads the on-screen instructions as
they appear, and presses keys through the guarded door.

    python -m playfellow_coop.games.stk.live --track tutorial --out runs/tutorial-1 --icon <png> [--read-key-file <txt>]

F12 (held) stops at once and releases every key. The run ends by itself when the minimap has been gone for a few seconds
(the race is over and the results are up) or after --max-seconds. The driver's log, the instructions read and what was done
about them, and every key event go to --out.

Load is kept low on purpose (two power cuts on 3 November, see power.py): 20 looks a second on small screen regions, the
whole-map search at most twice a second, the message strip checked five times a second, model reads on a worker thread.
"""
from __future__ import annotations

import argparse
import json
import threading
import time
from pathlib import Path

import numpy as np

from playfellow_coop.games.stk.countdown import Countdown
from playfellow_coop.games.stk.drive import Driver, Keys, learn_steer_sign
from playfellow_coop.games.stk.instructions import MessageWatch, Reader
from playfellow_coop.games.stk.fasteye import bananas, dodge
from playfellow_coop.games.stk.held import HeldPower, read_place
from playfellow_coop.games.stk.items import ItemEye, aim, plan
from playfellow_coop.games.stk.powers import Moment, decide
from playfellow_coop.games.stk.widget import HANDOVER, NUDGE, TUNE


def learn_lap(driver, lap: int, say) -> None:
    """Runs beside the driving: this lap's trouble spots (stalls, reverses, rescues) join the notes for the next lap."""
    n = len(driver.track.centre)
    new = set()
    for entry in list(driver.log):
        if len(entry) == 4 and entry[1] in ("reverse", "rescue") and driver.index is not None:
            ticks = [e for e in driver.log if len(e) == 8 and e[0] <= entry[0]]
            if ticks:
                new.add(int(ticks[-1][3]) % n)
    added = new - set(driver.notes)
    if added:
        driver.notes = tuple(sorted(set(driver.notes) | added))
    say(f"Lap {lap} done. Learned while driving: {len(added)} new trouble spot{'s' if len(added) != 1 else ''}; I take {'them' if len(added) != 1 else 'it'} slower and wider next lap." if added else f"Lap {lap} done, clean: nothing new to learn.")


class Nudges:
    """New lines in the widget's nudge file since this race started (the file is only appended to)."""

    def __init__(self):
        self.start = time.time()
        self.pos = NUDGE.stat().st_size if NUDGE.exists() else 0

    def new(self) -> list[str]:
        if not NUDGE.exists() or NUDGE.stat().st_size <= self.pos:
            return []
        with open(NUDGE, encoding="utf-8") as fh:
            fh.seek(self.pos)
            lines = fh.read().splitlines()
            self.pos = fh.tell()
        return [line.split(" ", 1)[1] for line in lines if " " in line]


def apply_move(driver, keys, move: str, now: float) -> None:
    """A direct command from the player, done at once (left/right/straight last about a second)."""
    if move in ("left", "right"):
        driver.forced_bias, driver.forced_until = (0.35 if move == "left" else -0.35), now + 1.0
    elif move == "straight":
        driver.hold_straight_until = now + 1.2
    elif move == "nitro":
        driver.taps.add(keys.nitro)
    elif move == "fire":
        driver.taps.add(keys.fire)
    elif move == "look_back":
        driver.taps.add(keys.look_back)
    elif move == "rescue":
        driver.taps.add(keys.rescue)
    elif move == "brake":
        driver.brake_until = now + 0.6
    elif move == "drift":
        driver.skid_start = -99.0
        driver.force_drift = True
    elif move == "faster":
        driver.speed_scale = min(driver.speed_scale * 1.1, 1.4)
    elif move == "slower":
        driver.speed_scale = max(driver.speed_scale * 0.9, 0.7)


def read_tune() -> dict:
    try:
        return json.loads(TUNE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
from playfellow_coop.games.stk.io import GameWindow
from playfellow_coop.games.stk.minimap import IconModel, MapGeometry, find_icon, in_kart_zone, map_visible
from playfellow_coop.games.stk.paths import kart_info
from playfellow_coop.games.stk.track import Track, load_items

VK_F12 = 0x7B


class MapEyes:  # pragma: no cover - needs a real desktop
    """Grabs just the minimap square (a few milliseconds), and the bottom strip where the game writes its messages."""

    def __init__(self, window: GameWindow, geo_for):
        import mss

        self.window, self.geo_for = window, geo_for
        self.grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    def look(self):
        x0, y0, x1, y1 = self.window.client_box()
        geo = self.geo_for(x1 - x0, y1 - y0)
        bx0, by0, bx1, by1 = geo.box()
        bx0, by0 = max(bx0, 0), max(by0, 0)
        bx1, by1 = min(bx1, x1 - x0), min(by1, y1 - y0)
        shot = np.asarray(self.grabber.grab({"left": x0 + bx0, "top": y0 + by0, "width": bx1 - bx0, "height": by1 - by0}))[:, :, :3]
        canvas = np.zeros((by1, bx1, 3), dtype=np.uint8)  # minimap pixels at their window coordinates, the rest black
        canvas[by0:by1, bx0:bx1] = shot
        return canvas, geo

    def forward(self, width: int = 480) -> np.ndarray:
        """The road ahead (items.VIEW band of the view), scaled to `width` pixels across, for the item eye."""
        import cv2

        from playfellow_coop.games.stk.items import VIEW

        x0, y0, x1, y1 = self.window.client_box()
        w, h = x1 - x0, y1 - y0
        top, bot = int(h * VIEW[0]), int(h * VIEW[1])
        shot = np.asarray(self.grabber.grab({"left": x0, "top": y0 + top, "width": w, "height": bot - top}))[:, :, :3]
        return cv2.resize(shot, (width, int(shot.shape[0] * width / w)), interpolation=cv2.INTER_AREA)

    def centre(self) -> np.ndarray:
        """The middle band where the countdown is written, as a full-size frame with only that band filled."""
        x0, y0, x1, y1 = self.window.client_box()
        w, h = x1 - x0, y1 - y0
        top, bot, left, right = int(h * 0.33), int(h * 0.47), int(w * 0.3), int(w * 0.7)
        shot = np.asarray(self.grabber.grab({"left": x0 + left, "top": y0 + top, "width": right - left, "height": bot - top}))[:, :, :3]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[top:bot, left:right] = shot
        return canvas

    def road(self) -> np.ndarray:
        """The road ahead (fasteye.BAND) at full size, in a full-size frame (the fast banana eye works in view coordinates)."""
        from playfellow_coop.games.stk.fasteye import BAND

        x0, y0, x1, y1 = self.window.client_box()
        w, h = x1 - x0, y1 - y0
        top, bot = int(h * BAND[0]), int(h * BAND[1])
        shot = np.asarray(self.grabber.grab({"left": x0, "top": y0 + top, "width": w, "height": bot - top}))[:, :, :3]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[top:bot] = shot
        return canvas

    def top(self) -> np.ndarray:
        """The top third of the view (the held power and the standings list), in a full-size frame. Only the power watcher's
        own thread calls this, with its own eyes (mss handles are per thread)."""
        x0, y0, x1, y1 = self.window.client_box()
        w, h = x1 - x0, y1 - y0
        bot = int(h * 0.34)
        shot = np.asarray(self.grabber.grab({"left": x0, "top": y0, "width": w, "height": bot}))[:, :, :3]
        canvas = np.zeros((h, w, 3), dtype=np.uint8)
        canvas[:bot] = shot
        return canvas

    def bottom(self) -> np.ndarray:
        """The bottom 8% of the view, as a full-height frame with only that band filled (find_box works in view coordinates)."""
        x0, y0, x1, y1 = self.window.client_box()
        h = y1 - y0
        top = int(h * 0.92)
        shot = np.asarray(self.grabber.grab({"left": x0, "top": y0 + top, "width": x1 - x0, "height": h - top}))[:, :, :3]
        canvas = np.zeros((h, x1 - x0, 3), dtype=np.uint8)
        canvas[top:h] = shot
        return canvas


_TRACKS: dict = {}  # track maps, loaded once per session


def race_tracks() -> list[str]:
    """Every race track the game has: only race tracks carry a driveline (quads.xml); the tutorial and the story hub are
    left out, and so is anything marked as an arena or a cut-scene."""
    import re

    from playfellow_coop.games.stk.paths import game_data

    out = []
    for folder in sorted((game_data() / "tracks").iterdir()):
        meta = folder / "track.xml"
        if not ((folder / "quads.xml").exists() and meta.exists()):
            continue
        text = meta.read_text(encoding="utf-8", errors="replace")
        if re.search(r'(arena|internal|cutscene)\s*=\s*"[Yy]', text) or folder.name in ("tutorial", "overworld"):
            continue
        out.append(folder.name)
    return out


def which_track(window: GameWindow, w: int, h: int, skip: str = "") -> str | None:  # pragma: no cover - needs a real desktop
    """The race track whose minimap outline is on screen now (5 Nov: the buddy should race on any track, and the menus once
    put it on another track than planned). Looks once at the window and tries every race track's own map."""
    import mss

    x0, y0, x1, y1 = window.client_box()
    with (mss.MSS() if hasattr(mss, "MSS") else mss.mss()) as grab:
        frame = np.asarray(grab.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3].copy()
    for tid in race_tracks():
        if tid == skip:
            continue
        try:
            tr = _TRACKS.get(tid) or _TRACKS.setdefault(tid, Track.load(tid))
            if map_visible(frame, MapGeometry.for_view(tr, frame.shape[1], frame.shape[0]), tr):
                return tid
        except Exception:  # noqa: BLE001 - a track whose files do not parse is skipped
            continue
    return None


class PowerWatch:  # pragma: no cover - needs a real desktop
    """The held power, its charges and our place, read on a thread of its own about once a second.

    5 Nov profile: reading the power icon inside the race loop took 39% of the loop's time (the masked icon match is slow
    during a race), so the loop looked at the road 2-6 times a second instead of 16-17, the speed read 0 and the kart
    reversed and turned round. The race loop now only takes the latest answer and never waits for it."""

    def __init__(self, window: GameWindow, geo_for, every: float = 1.0):
        self.window, self.geo_for, self.every = window, geo_for, every
        self.power, self.charges, self.place, self.at = None, 0, None, 0.0
        self._stop = threading.Event()
        self._thread = threading.Thread(target=self._run, name="power-watch", daemon=True)

    def start(self) -> "PowerWatch":
        self._thread.start()
        return self

    def stop(self) -> None:
        self._stop.set()

    def _run(self) -> None:
        eyes = MapEyes(self.window, self.geo_for)  # its own screen grabber (mss handles are per thread)
        reader = HeldPower()
        while not self._stop.is_set():
            try:
                view = eyes.top()
                power, charges = reader.read(view)
                place = read_place(view)
                self.power, self.charges = power, charges
                self.place = place or self.place
                self.at = time.monotonic()
            except Exception:  # noqa: BLE001 - a missed look is retried next time; the race never waits on this
                pass
            self._stop.wait(self.every)


def run(track_id: str, out: Path, max_seconds: float = 400.0, learn: bool = True, steer_sign: float = 1.0, hz: float = 20.0,
        icon_path: Path | None = None, say=print, reader: Reader | None = None, guard=None,
        stop: threading.Event | None = None, preskills: dict | None = None, sam_marker=None, notes: list | None = None,
        kart: str = "tux") -> dict:  # pragma: no cover - needs a real desktop
    out.mkdir(parents=True, exist_ok=True)
    window = GameWindow()
    if not window.focus():
        raise RuntimeError("the game window could not be brought to the front; nothing was pressed")
    keys = Keys()
    hands = window.hands(keys.all() | {"esc"})  # esc only to leave the pause menu the game opens when it loses focus
    track = Track.load(track_id)
    geos: dict = {}
    eyes = MapEyes(window, lambda w, h: geos.setdefault((w, h), MapGeometry.for_view(track, w, h)))
    info = kart_info(kart)
    driver = Driver(track, keys=keys, steer_sign=steer_sign, kart_class=info.get("class", "medium"), items=load_items(track))
    say(f"Kart {info.get('name') or kart} ({driver.kart_class}); {len(driver.bends)} bends and {len(driver.items)} items on the map: "
        f"skids planned per bend, the line goes through side boxes and cans and stays clear of bananas.")
    learned_tux = IconModel.load(icon_path) if icon_path is not None and Path(icon_path).exists() else None
    if kart != "tux" and info.get("icon"):  # a kart other than the one learned live: its minimap look from the game's own icon file
        model = IconModel.from_game_icon(info["icon"])
        fallbacks = [("Tux", learned_tux, "medium")]
    else:
        model = learned_tux
        fallbacks = []
    watch = MessageWatch()
    t_start = time.monotonic()
    tick = 1.0 / hz
    gone_since, seen, stopped_by, last_icon, last_seen_at = None, 0, "max_seconds", None, 0.0
    last_full_search, last_strip_look, paused_for, gate_at, moving_at = -1.0, -1.0, None, 0.0, None
    last_map_check, map_gone_since = -1.0, None
    phase = "gate"  # no race key goes out until the kart has been seen on a minimap three looks in a row (never drive a menu)
    after_gate = "learn" if learn else "countdown"
    countdown = Countdown()
    driver.notes = tuple(notes or ())
    TUNE.unlink(missing_ok=True)  # a spoken or typed tip lasts for the race it was given in, never for every race after
    last_banana_look, last_banana_said, laps_learned = -1.0, -99.0, 0
    looks_done, sightings, rate_since = 0, 0, None  # the race loop's pace, measured while racing
    banana_streak = 0
    power_watch = None  # started with the race: the power reading on its own thread
    nudges = Nudges()
    held_power, held_since, place, last_power_look = None, 0.0, None, -1.0
    charges, shots_at = 0, -99.0
    set_at = None
    item_eye = ItemEye(grab=eyes.forward, marker=sam_marker).start() if sam_marker is not None else None
    last_why, last_why_at = "", -99.0
    last_focus_try, refocused_at, handed, last_tune_read = -99.0, None, False, -99.0
    if preskills:  # what earlier play taught (the tutorial): used from the first second, not relearned in every race
        driver.steer_sign = float(preskills.get("steer_sign", driver.steer_sign))
        lessons = set(preskills.get("lessons", []))
        if "drift" in lessons:
            driver.skid_until = 1e9
        say("Using what the tutorial taught me: " + (", ".join(sorted(lessons)) or "steering") + ".")
    gate_seen, gate_deadline, outline_seen, icon_only = 0, 25.0, False, 0
    learn_marks: dict[str, list[float]] = {"before": [], "after": []}
    say(f"Waiting to see my kart on the {track_id} minimap before I touch a key.")
    from playfellow_coop.games.stk.widget import set_status
    set_status(f"racing on {track_id}: steering from the minimap, reading the screen, watching for items.")
    try:
        while True:
            now = time.monotonic() - t_start
            if now > max_seconds:
                break
            if not window.user32.IsWindow(window.hwnd):  # the game was closed: nothing to look at or press
                stopped_by = "game_closed"
                say("The game was closed, so I stopped.")
                break
            if window.key_is_down(VK_F12) or (stop is not None and stop.is_set()):
                stopped_by = "F12" if window.key_is_down(VK_F12) else "stopped"
                break
            if HANDOVER.exists():  # F9: the player has the controls; hold nothing, wait
                if not handed:
                    hands.release_all()
                    handed = True
                time.sleep(0.1)
                continue
            handed = False
            if not window.in_front():  # something else took the front: nothing can be pressed; take it back, say so
                if now - last_focus_try > 2.0:
                    last_focus_try = now
                    say("The game lost the front, so my keys stopped. Taking it back.")
                    if window.focus():
                        refocused_at = now  # the game paused itself when it lost focus: unpause below once the map stays hidden
                time.sleep(0.2)
                continue
            if now - last_tune_read > 2.0:  # the player's tips, as live tuning (widget.TUNE)
                last_tune_read = now
                tune = read_tune()
                driver.nitro_every = 1.2 if tune.get("more_nitro") else 2.0
                driver.item_cap = 0.16 if tune.get("more_items") else 0.10
                driver.dodge_cap = 0.30 if tune.get("dodge_more") else 0.22
                driver.speed_scale = 0.88 if tune.get("calmer") else 1.0
            danger = guard.danger() if guard is not None else None
            if danger:  # let go and wait: better a paused race than a laptop that switches off
                if paused_for != danger:
                    hands.release_all()
                    say(f"Pausing my keys: {danger}.")
                    paused_for = danger
                time.sleep(0.5)
                continue
            if paused_for:
                say("Power is fine again; driving on.")
                paused_for = None
            frame, geo = eyes.look()
            if refocused_at is not None and now - refocused_at > 0.6:
                if phase not in ("gate",) and not map_visible(frame, geo, track):
                    hands.release_all()
                    hands.tap("esc")  # the pause menu's first choice is "Back to Race"; Esc is the same
                    say("The game had paused itself; back to the race.")
                refocused_at = None
            # the kart: track the icon where it can physically be, around the predicted spot
            lost_for = (now - last_seen_at) if last_icon is not None else 99.0
            predicted = driver.predict(now)
            near = tuple(geo.to_pixel(predicted)) if predicted is not None else last_icon
            teleported = now - driver.last_rescue < 3.0  # Rescue puts the kart back on the road somewhere else: search wide
            icon = None
            if model is None:  # no learned look yet: a ring sighting off the kart model, then learn what the icon looks like
                ring = find_icon(frame, geo, track=track)
                on_road = ring is not None and float(np.min(np.linalg.norm(track.centre - geo.to_world(np.array(ring)), axis=1))) < 15.0
                if ring is not None and on_road and not in_kart_zone(ring, geo):
                    model = IconModel.learn(frame, ring, geo.size / 180.0)
                    if model is not None:
                        if icon_path is not None:
                            model.save(icon_path)
                        say("Learned what my kart looks like on the minimap.")
            if model is not None:
                hit = None
                if near is not None and not teleported and lost_for < 0.6:
                    hit = model.match(frame, geo, near=near, radius=min(14.0 + 40.0 * lost_for, 40.0))
                # 5 Nov: with slow looks the near search kept failing and the whole map was searched only twice a second, so the
                # kart was "lost" most of the time, drove blind and stalled (1.6 sightings a second). The whole map costs about
                # 40 ms: search it at once whenever the near search misses.
                if hit is None and (teleported or near is None or lost_for >= 0.0) and now - last_full_search >= 0.15:
                    last_full_search = now
                    hit = model.match(frame, geo)
                if hit is None and seen == 0 and fallbacks and now - last_full_search < 0.01:
                    # not one sighting yet: the kart on the grid may not be the one asked for (4 Nov: the menu kept Tux while
                    # Puffy was asked, so the buddy never found itself and missed the start). Try every look it might have.
                    for other, other_model, other_class in fallbacks:
                        if other_model is None:
                            continue
                        hit = other_model.match(frame, geo)
                        if hit is not None:
                            model, driver.kart_class = other_model, other_class
                            say(f"My kart is {other} ({other_class}), not the one I asked for; driving it as a {other_class} kart.")
                            fallbacks = []
                            break
                icon = hit[0] if hit is not None else None
            if icon is not None:
                last_icon, last_seen_at = icon, now
                gone_since, seen, map_gone_since = None, seen + 1, None
                driver.blind_limit = 0.8
            else:
                # the icon is not seen: hidden behind a message box (the map is still up), or the race is over (no map)
                gone_since = gone_since if gone_since is not None else now
                if now - last_map_check >= 0.5:
                    last_map_check = now
                    map_up = map_visible(frame, geo, track)
                    map_gone_since = None if map_up else (map_gone_since if map_gone_since is not None else now)
                    driver.blind_limit = 2.5 if map_up else 0.8
                if seen > 50 and map_gone_since is not None and now - map_gone_since > 3.0:
                    stopped_by = "minimap_gone"
                    break
            xz = geo.to_world(np.array(icon)) if icon is not None else None
            # the game's messages: a new one goes to the reader; what was read is acted on with its timing
            if reader is not None and now - last_strip_look >= 0.2:
                last_strip_look = now
                strip = watch.look(eyes.bottom())
                if strip is not None:
                    reader.submit(strip)
                for inst in reader.ready():
                    todo = driver.apply(inst, now)
                    say(f"{inst.describe()} {todo.capitalize()}." if todo != "noted" else inst.describe())
            if phase == "gate":
                # a race on this track is on screen: the kart icon is seen, or this track's map outline is (the icon can be
                # hidden behind a lesson box while the kart is parked under it; it only comes out once the kart moves)
                # 5 Nov: the kart icon alone also shows on ANOTHER track's minimap: two races were driven on Ravenbridge
                # Mansion with Abyss's map. The map's outline must be this track's before any race key.
                outline = map_visible(frame, geo, track)
                outline_seen = outline_seen or outline
                race_up = outline or (outline_seen and icon is not None and model is not None)
                gate_seen = gate_seen + 1 if race_up else 0
                icon_only = icon_only + 1 if (icon is not None and not outline_seen) else icon_only
                if icon_only in (10, 30, 50):  # the kart is on a race, but not on this track's map: which track is it?
                    h_, w_ = frame.shape[:2]
                    found_id = which_track(window, w_, h_, track_id)
                    if found_id:
                        track_id, track = found_id, Track.load(found_id)
                        geos.clear()  # the map geometry follows the new track (the eyes read `track` at each look)
                        driver = Driver(track, keys=keys, steer_sign=steer_sign, kart_class=driver.kart_class, items=load_items(track))
                        last_icon, outline_seen, icon_only = None, True, 0
                        say(f"This race is on {found_id.replace('_', ' ')}, not the track I expected: I drive it with its own map.")
                        continue
                if icon_only >= 60:  # about 3 s of seeing the kart on a minimap that is no race track's we know
                    stopped_by = "wrong_track"
                    say(f"My kart is on a race, but the minimap is not {track_id}'s: I'm on the wrong track, so I press nothing.")
                    break
                if gate_seen >= 3:
                    phase, gate_at = after_gate, now
                    hands.clear()  # nothing the game thinks is pressed: a key down at "Ready!" earns a penalty
                    if phase == "countdown":
                        say(f"On the {track_id} grid. Waiting for 'Set!' to floor it (the start boost from the help page).")
                    else:
                        say(f"I see the {track_id} race on screen. Driving: the road comes from the game's own map file.")
                elif now > gate_deadline:
                    stopped_by = "no_race_view"
                    say("I never saw my kart on a race map, so I pressed nothing.")
                    break
                time.sleep(tick)
                continue
            if phase == "countdown":
                # ready on the grid: nothing pressed during "Ready!" (the game punishes it), full throttle from "Set!" on
                driver.step(now, xz, racing=False)
                was_go = countdown.go_now
                countdown.look(eyes.centre())
                if countdown.go_now and not was_go:
                    say("Set! Full throttle.")
                heading_now, speed_now = driver.heading(now)
                wanted = {keys.accel} if countdown.go_now else set()
                if countdown.go_now and set_at is None:
                    set_at = now
                if set_at is not None and now - set_at > 1.3:  # past "Go!" and not moving: the game is ignoring the held key
                    wanted = driver.kick(now, speed_now, wanted)
                hands.hold_only(wanted)
                if heading_now is not None or (countdown.go_now and now - gate_at > 12.0) or (not countdown.go_now and now - gate_at > 15.0):
                    phase = "race"  # rolling (or the countdown was missed): race
                    driver.begin_race(now)
                time.sleep(max(0.0, tick - ((time.monotonic() - t_start) - now)))
                continue
            if phase == "learn":
                # learn which way Left turns the kart on the map: 1.6 s straight, 0.5 s Left, read the heading before and after
                driver.step(now, xz, racing=False)
                heading, speed_now = driver.heading(now)
                if moving_at is None:  # the countdown: the kart cannot move before "Go!", so the clock starts at its first motion
                    if heading is None and now - gate_at < 12.0:
                        hands.hold_only({keys.accel} if now - gate_at > 2.2 else set())  # accelerate from about "Set!" (the start boost)
                        time.sleep(tick)
                        continue
                    moving_at = now
                lt = now - moving_at
                if lt < 2.2:
                    held = {keys.accel}
                    if heading is not None and speed_now > 4.0 and lt > 1.2:
                        learn_marks["before"].append(heading)
                elif lt < 2.7:
                    held = {keys.accel, keys.left}
                elif lt < 3.2:
                    held = {keys.accel}
                    if heading is not None:
                        learn_marks["after"].append(heading)
                else:
                    held = {keys.accel}
                    if learn_marks["before"] and learn_marks["after"]:
                        driver.steer_sign = learn_steer_sign(learn_marks["before"], learn_marks["after"])
                        say(f"Learned the steering: Left turns my kart {'anti-clockwise' if driver.steer_sign > 0 else 'clockwise'} on the map.")
                    else:
                        say("Could not see the kart turn while learning; keeping the default steering.")
                    phase = "race"
                hands.hold_only(held)
            else:
                if item_eye is not None:  # SAM's sightings (tracked between keyframes): hunt one item, dodge obstacles
                    t_now = time.monotonic()
                    bias, why, _target = plan(item_eye.seen, t_now)
                    aim_bias, _lined_up, foe = aim(item_eye.seen, t_now)
                    if not bias and foe is not None:  # nothing to dodge or grab: line up on the opponent ahead
                        bias = aim_bias
                    driver.item_bias = bias
                    driver.dodging = bool(_target is not None and _target.kind == "banana")
                    driver.auto_fire = False  # powers are used by the rules in powers.py, never on a timer
                    if now - last_power_look >= 0.25:  # what is in hand and our place: the power watcher's latest reading
                        last_power_look = now
                        if power_watch is None:
                            power_watch = PowerWatch(window, lambda w, h: geos.setdefault((w, h), MapGeometry.for_view(track, w, h))).start()
                        power, charges = power_watch.power, power_watch.charges
                        driver.held_power = power  # a box would replace it: the item line stops chasing boxes while one is in hand
                        if power != held_power:
                            held_power, held_since = power, now
                            if power:
                                say(f"Holding {power}" + (f" x{charges}" if charges > 1 else "") + ".")
                        place = power_watch.place or place
                        karts = [s for s in item_eye.seen if s.kind == "kart" and t_now - s.at <= 0.8 and 0.20 < s.y < 0.66]
                        road_bend = driver.curvature_ahead(driver.index, metres=40.0) if driver.index is not None else 0.0
                        shoot, backwards, reason = decide(Moment(held_power, charges, karts, place, road_bend,
                                                                 banana_in_path=banana_streak >= 2, held_for=now - held_since,
                                                                 since_last=now - shots_at))
                        if shoot:
                            shots_at = driver.last_fire = now
                            driver.taps |= {keys.fire, keys.look_back} if backwards else {keys.fire}
                            why = reason

                    if why and (why != last_why or now - last_why_at > 4.0):
                        last_why, last_why_at = why, now
                        say(why.capitalize() + ".")
                if now - last_banana_look >= 0.1:  # the fast eye: bananas ten times a second, no model (SAM is 2-3 s late)
                    last_banana_look = now
                    push = dodge(bananas(eyes.road()))
                    # 5 Nov: single false sightings made it swerve ("scared"): a banana must be seen on two looks in a row
                    banana_streak = banana_streak + 1 if push else 0
                    if push and banana_streak < 2:
                        push = 0.0
                    if push:  # a gentle push around it, as raced on 3 Nov; the 4 Nov "take the wheel at full lock for 0.5 s"
                        # swung the kart into walls on false sightings (5 Nov 02:12: two "banana" swerves, two crashes)
                        driver.item_bias, driver.dodging = push, True
                        if now - last_banana_said > 3.0:
                            last_banana_said = now
                            say("Banana ahead: steering around it.")
                for move in nudges.new():  # the player's direct commands (widget.NUDGE), acted on this tick
                    apply_move(driver, keys, move, now)
                lap = int(driver.progress // driver.lap_length) if driver.lap_length else 0
                if lap > laps_learned and lap >= 1:  # a lap is done: learn from it in parallel, use it on the next lap
                    laps_learned = lap
                    threading.Thread(target=learn_lap, args=(driver, lap, say), daemon=True).start()
                hands.hold_only(driver.step(now, xz, racing=True))
                if rate_since is None:
                    rate_since = now
                looks_done += 1
                sightings += xz is not None
                if now - rate_since >= 10.0:  # the loop's real pace, said and logged: 5 Nov it fell to 1.6 a second unseen
                    rate = looks_done / (now - rate_since)
                    driver.log.append((now, "pace", round(rate, 1), f"{sightings} sightings of {looks_done} looks"))
                    if rate < 12.0 or sightings < 0.7 * looks_done:
                        say(f"I'm only looking {rate:.0f} times a second and saw my kart {sightings} of {looks_done} times: "
                            "my driving gets worse like this.")
                    looks_done, sightings, rate_since = 0, 0, now
            time.sleep(max(0.0, tick - ((time.monotonic() - t_start) - now)))
    finally:
        hands.release_all()
        if power_watch is not None:
            power_watch.stop()
        if item_eye is not None:
            item_eye.stop()
    result = {"track": track_id, "stopped_by": stopped_by, "seconds": round(time.monotonic() - t_start, 1), "steer_sign": driver.steer_sign,
              "progress_m": round(driver.progress, 1), "lap_length_m": round(driver.lap_length, 1), "laps_driven": round(driver.progress / driver.lap_length, 2),
              "rescues": sum(1 for e in driver.log if len(e) == 4 and e[1] == "rescue"), "refused_sends": hands.refused, "key_events": len(hands.audit),
              "instructions_obeyed": driver.obeyed, "reads": reader.log if reader is not None else [],
              "power_trips": getattr(guard, "trips", 0), "sam_keyframes": item_eye.keyframes if item_eye else 0,
              "sam_calls": getattr(sam_marker, "calls", 0), "sam_tracked_pictures": getattr(sam_marker, "tracked_pictures", 0),
              "kart": kart, "items_estimate": driver.item_passes(), "skids": {tier: sum(1 for e in driver.log if len(e) == 4 and e[1] == "drift end" and e[3] == tier) for tier in ("red", "yellow", "none")}}
    (out / "drive-log.json").write_text(json.dumps({"result": result, "log": driver.log[-4000:]}, default=str), encoding="utf-8")
    (out / "key-audit.json").write_text(json.dumps(hands.audit), encoding="utf-8")
    say(f"Run over ({stopped_by}): {result['laps_driven']} laps of road, {result['rescues']} rescues, {len(driver.obeyed)} instructions acted on.")
    est, sk = result.get("items_estimate") or {}, result.get("skids") or {}
    say(f"Skid boosts: {sk.get('red', 0)} red, {sk.get('yellow', 0)} yellow, {sk.get('none', 0)} skids with no boost. Items (estimate "
        f"from the map): {est.get('boxes_in_reach', 0)} boxes and {est.get('cans_in_reach', 0)} cans passed within reach, "
        f"{est.get('bananas_close', 0)} bananas passed too close.")
    return result


def main(argv=None):  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--track", required=True)
    p.add_argument("--out", required=True)
    p.add_argument("--max-seconds", type=float, default=400.0)
    p.add_argument("--no-learn", action="store_true")
    p.add_argument("--steer-sign", type=float, default=1.0)
    p.add_argument("--icon", default=None, help="the learned minimap icon (read if it exists, written once learned)")
    a = p.parse_args(argv)
    print(json.dumps(run(a.track, Path(a.out), a.max_seconds, learn=not a.no_learn, steer_sign=a.steer_sign,
                         icon_path=Path(a.icon) if a.icon else None, kart=a.kart), default=str))


if __name__ == "__main__":
    main()
