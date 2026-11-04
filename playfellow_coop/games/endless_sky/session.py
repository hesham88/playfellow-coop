"""The buddy's hands and eyes on Endless Sky: every skill that touches the game goes through here.

Everything it does is keyboard on the game window, only while that window is in front (stk.io.Hands). After each step it looks again and logs
what it saw, so a run can be read back; a step that does not lead where it should is reported, not assumed. It never edits a save or data file.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

from playfellow_coop.games.endless_sky.where import GAME_DIR  # noqa: E402,F401  (sets the widget's game before it loads)

import cv2  # noqa: E402
import numpy as np  # noqa: E402

from playfellow_coop.games.endless_sky import flight, hud as hudlib  # noqa: E402
from playfellow_coop.games.endless_sky.card import load_card  # noqa: E402
from playfellow_coop.games.endless_sky.routes import StarMap  # noqa: E402
from playfellow_coop.games.endless_sky.save import Pilot, load_pilot, save_time  # noqa: E402
from playfellow_coop.games.endless_sky.screen import Line, View, bounty_line, classify, selected_model  # noqa: E402
from playfellow_coop.games.stk import widget  # noqa: E402
from playfellow_coop.games.stk.io import Eyes, GameWindow  # noqa: E402
from playfellow_coop.universal.winio import SCANCODES  # noqa: E402

TITLE = "Endless Sky"
WIDGET_BOX = (280, 72)  # half width, height of the widget docked at the window's top centre, avatar included


def start_widget_process() -> None:  # pragma: no cover - starts a real window
    """The widget as its own detached process, so it outlives whatever started it."""
    import subprocess
    import sys

    root = str(Path(__file__).resolve().parents[3])
    engine = os.environ.get("PLAYFELLOW_ENGINE", "")  # the engine's software folder when it is not installed (tests set it)
    env = dict(os.environ, PYTHONPATH=os.pathsep.join(p for p in (root, engine) if p))
    log = open(widget.GAME_DIR / "widget-err.log", "a")
    subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.widget"], env=env, stdout=log, stderr=log, stdin=subprocess.DEVNULL,
                     cwd=root, creationflags=0x00000008 | 0x00000200)


class Stopped(RuntimeError):
    """The owner pressed stop (F12)."""


class Session:  # pragma: no cover - drives the real game; its decisions live in flight, hud and screen, which are tested
    def __init__(self, out: Path, width: int = 1280, height: int = 860, place: bool = True):
        self.out = out
        out.mkdir(parents=True, exist_ok=True)
        (out / "steps").mkdir(exist_ok=True)
        self.window = GameWindow(TITLE)
        if place:
            self._place(width, height)
        self.card = load_card()
        self.hands = self.window.hands(frozenset(SCANCODES))
        self.eyes = Eyes(self.window)
        self._ocr = None
        self.step = 0
        self.log_file = open(out / "events.jsonl", "a", encoding="utf-8")
        self.last_view = "?"
        self.stars = StarMap.load()
        self.pilot_name = ""
        self._widget_checked = 0.0

    # ---- basics --------------------------------------------------------------------------------------------------------------------
    def _place(self, width: int, height: int) -> None:
        self.window.user32.ShowWindow(self.window.hwnd, 9)  # restore if snapped or maximised
        self.window.user32.SetWindowPos(self.window.hwnd, 0, 200, 40, width, height + 31, 0x0040)
        time.sleep(0.6)
        self.window.focus()

    def log(self, kind: str, **data) -> None:
        self.log_file.write(json.dumps({"at": time.strftime("%H:%M:%S"), "t": round(time.monotonic(), 2), "kind": kind, **data}) + "\n")
        self.log_file.flush()

    def say(self, text: str) -> None:
        widget.say_line(text)
        widget.set_status(text)
        self.log("say", text=text)
        print(time.strftime("%H:%M:%S"), text, flush=True)

    def guard(self) -> None:
        """Owner's controls: F12 stops the run, F9 hands the game over until F9 again. The game must be in front before keys go out."""
        if widget.STOP.exists():
            self.hands.release_all()
            raise Stopped("stop pressed")
        self._keep_widget_up()
        waited = False
        while widget.HANDOVER.exists():
            if not waited:
                self.hands.release_all()
                self.say("You have the controls; I wait.")
                waited = True
            if widget.STOP.exists():
                raise Stopped("stop pressed")
            time.sleep(0.3)
        if not self.window.in_front():
            self._wait_for_the_front()

    def _wait_for_the_front(self) -> None:
        """Owner 4 Nov: the player's other windows are the player's. When the game is not in front the buddy holds nothing, takes nothing back, looks at nothing
        (a screen rectangle would show whatever covers the game), and waits for the player to click the game again."""
        self.hands.release_all()
        self.log("paused-not-in-front")
        widget.set_status("paused: the game is not in front. Click the game and I carry on.")
        said = False
        while not self.window.in_front():
            if widget.STOP.exists():
                raise Stopped("stop pressed")
            if not said:
                widget.say_line("Paused: you are in another window. Click the game and I carry on.")
                said = True
            time.sleep(0.3)
        self.log("resumed")

    def _keep_widget_up(self) -> None:
        """The widget stays up for as long as the buddy has the game: checked every few seconds, started again if it died."""
        if time.monotonic() - self._widget_checked < 3.0:
            return
        self._widget_checked = time.monotonic()
        if not widget.widget_running():
            self.log("widget-restart")
            start_widget_process()

    def frame(self) -> np.ndarray:
        """The window now, with the widget's rectangle blacked out so the buddy never reads its own bar. Only while the game is in front."""
        if not self.window.in_front():
            self._wait_for_the_front()
        image = self.eyes.frame()
        w = image.shape[1]
        image[:WIDGET_BOX[1], max(0, w // 2 - WIDGET_BOX[0]):w // 2 + WIDGET_BOX[0]] = 0
        return image

    def shot(self, name: str, image: np.ndarray | None = None) -> Path:
        self.guard()  # never a picture of whatever window covers the game
        self.step += 1
        path = self.out / "steps" / f"{self.step:03d}-{name}.png"
        cv2.imwrite(str(path), self.eyes.frame() if image is None else image)
        return path

    def tap(self, key: str, hold: float = 0.08, settle: float = 0.25) -> None:
        self.guard()
        self.hands.tap(key, hold)
        self.log("tap", key=key)
        time.sleep(settle)

    def type_text(self, text: str) -> None:
        for c in text:
            self.guard()
            if c.isupper():
                self.hands.down("shift")
                self.hands.tap(c.lower(), 0.05)
                self.hands.up("shift")
            elif c == " ":
                self.hands.tap("space", 0.05)
            else:
                self.hands.tap(c, 0.05)
            time.sleep(0.04)

    def read(self, image: np.ndarray | None = None) -> list[Line]:
        if self._ocr is None:
            from rapidocr_onnxruntime import RapidOCR

            self._ocr = RapidOCR()
        result, _ = self._ocr(self.frame() if image is None else image)
        return [Line(r[1], int(r[0][0][0]), int(r[0][0][1])) for r in (result or [])]

    def view(self) -> View:
        image = self.frame()
        seen = classify(image, self.read(image))
        if seen.name != self.last_view:
            self.shot(seen.name)
            self.last_view = seen.name
        self.log("view", name=seen.name, text=" | ".join(l.text for l in seen.lines)[:600])
        return seen

    def pilot(self) -> Pilot | None:
        return load_pilot(self.pilot_name)

    # ---- menus ---------------------------------------------------------------------------------------------------------------------
    def settle_panels(self, limit: int = 40) -> View:
        """Reads through conversations and help dialogs with the first choice, until a working screen is up. Returns it."""
        seen = self.view()
        for _ in range(limit):
            if seen.name == "conversation":
                self.say("Reading the conversation: " + (seen.lines[0].text[:70] if seen.lines else ""))
                self.tap("enter", settle=0.6)
            elif seen.name == "dialog":
                self.say("Dialog: " + " ".join(l.text for l in seen.lines[:3])[:90])
                self.tap("enter", settle=0.6)
            else:
                return seen
            seen = self.view()
        return seen

    def press_until(self, key: str, wanted, tries: int = 4, settle: float = 1.5) -> View:
        """Presses a key, looks, and only goes on when the screen really is the next one. Menus can lag; a key is never assumed to have worked."""
        seen = self.view()
        for _ in range(tries):
            if wanted(seen):
                return seen
            self.tap(key, settle=settle)
            seen = self.view()
        return seen

    def to_start_screen(self) -> View:
        """From anywhere to the new-pilot start screen, each step checked: in-game > menu > load screen (it has the New Pilot button) > start."""
        seen = self.view()
        for _ in range(8):
            if seen.name == "start":
                return seen
            if seen.name in ("conversation", "dialog"):
                self.tap("enter", settle=0.8)
            elif seen.name == "menu" and seen.has("new pilot") and not seen.has("load game"):
                self.tap("n", settle=1.5)  # no pilot loaded: the menu itself offers it
            elif seen.has("new pilot", "load game") or seen.has("new pilot", "add snapshot"):
                self.tap("n", settle=1.5)  # the load screen
            elif seen.name == "menu":
                self.tap("l", settle=1.5)
            else:
                self.tap("esc", settle=2.0)  # leaves a panel, then the planet or flight, for the menu
            seen = self.view()
        return seen

    def new_pilot(self, first: str, last: str) -> None:
        seen = self.to_start_screen()
        if seen.name != "start":
            raise RuntimeError(f"expected the start screen, saw {seen.name}: " + " ".join(l.text for l in seen.lines)[:120])
        self.pilot_name = f"{first} {last}"
        self.say(f"New pilot: choosing the classic start at New Boston, {first} {last}.")
        self.tap("s", settle=1.5)
        self.type_text(first)
        self.tap("tab")
        self.type_text(last)
        self.shot("name")
        self.tap("enter", settle=1.2)
        self.settle_panels(3)

    def buy_ship(self, model: str = "Sparrow", name: str = "Fellow", presses: int = 3) -> None:
        seen = self.view()
        if seen.name != "shipyard":
            raise RuntimeError(f"expected the shipyard, saw {seen.name}")
        for _ in range(presses + 3):
            if selected_model(seen.lines) == model.lower():
                break
            self.tap("down", settle=0.5)
            seen = self.view()
        if selected_model(seen.lines) != model.lower():
            self.shot("wrong-ship")
            raise RuntimeError(f"could not select the {model}: the detail column says {selected_model(seen.lines)!r}")
        self.say(f"Buying the {model}: smallest real warship here, it can take bounties. Named her {name}.")
        self.shot("ship-chosen")
        self.tap("b", settle=0.8)
        self.type_text(name)
        self.tap("enter", settle=1.0)
        self.tap("l", settle=1.5)

    def outfit_count(self, seen: View, name: str) -> tuple[bool, int]:
        """(selected, installed) for the shop's selected outfit, from the detail column's title and the catalogue's 'installed: n' label under the first listing."""
        import re

        text = " ".join(l.text for l in seen.lines)
        match = re.search(r"install\w*:?\s*(\d+)", text.lower())
        return name.lower() in text.lower(), int(match.group(1)) if match else 0

    def refit(self, sell: str = "Beam", buy: str = "Energy", count: int = 4) -> dict:
        """The upgrade skill: sell the stock guns and fit more, longer-reaching ones, each step read back from the outfitter's own numbers. Key F searches the shop."""
        self.say(f"Refit: selling the stock Beam Lasers (range 300) for {count} Energy Blasters (range 510, twice the damage).")
        self.tap("o", settle=1.5)
        seen = self.settle_panels(4)
        self.shot("outfitter")
        self.tap("f", settle=0.8)
        self.type_text(sell)
        self.tap("enter", settle=1.0)
        for _ in range(2):
            self.tap("s", settle=0.8)
        self.tap("f", settle=0.8)
        self.type_text(buy)
        self.tap("enter", settle=1.0)
        for _ in range(count):
            self.tap("b", settle=0.8)
        seen = self.view()
        self.shot("refit-done")
        text = " ".join(l.text for l in seen.lines)
        self.log("refit", text=text[:900])
        self.tap("l", settle=1.2)
        self.settle_panels(4)
        return {"text": text[:900]}

    def depart(self) -> None:
        self.say("Taking off.")
        self.tap("d", settle=2.5)

    # ---- travel --------------------------------------------------------------------------------------------------------------------
    def click(self, x: int, y: int) -> None:
        """One left click at a point inside the window, only while it is in front; logged like a key. Used on the star map, as the game's own help says."""
        from playfellow_coop.universal.winio import MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, mouse_input

        self.guard()
        x0, y0, x1, y1 = self.window.client_box()
        if not (0 <= x < x1 - x0 and 0 <= y < y1 - y0) or not self.window.in_front():
            self.log("click-refused", x=x, y=y)
            return
        self.window.user32.SetCursorPos(x0 + x, y0 + y)
        time.sleep(0.15)
        self.window.send([mouse_input(MOUSEEVENTF_LEFTDOWN)])
        time.sleep(0.06)
        self.window.send([mouse_input(MOUSEEVENTF_LEFTUP)])
        self.log("click", x=x, y=y)
        time.sleep(0.3)

    def set_hop(self, here: str, near: str) -> None:
        """Map, click the next system on the route, back to flight. The plan is what stops the ship from wandering."""
        self.say(f"Course: {here} to {near} on the map.")
        self.tap(self.card["map"], settle=1.2)
        image = self.frame()
        h, w = image.shape[:2]
        dx, dy = self.stars.map_offset(here, near)
        self.click(int(w / 2 + dx), int(h / 2 + dy))
        self.shot("route")
        self.tap(self.card["map"], settle=1.0)

    def landed(self) -> bool:
        """The HUD stays lit behind the landed screen, so a lit HUD says nothing: the navigation box says 'Landed on:'; a panel over it means landed too."""
        image = self.frame()
        if not hudlib.is_bright(image):
            return True
        crop = image[8:50, 205:380]
        return any("landed" in l.text.lower() for l in self.read(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC)))

    def fuel_ok(self, jumps: int = 1) -> bool:
        """Only a lit HUD can be read: a help dialog dims the bars, and a dim bar must not read as an empty tank."""
        seen = hudlib.read_hud(self.frame())
        for _ in range(4):
            if seen.bright:
                break
            self.settle_panels(6)
            seen = hudlib.read_hud(self.frame())
        self.log("fuel", share=round(seen.fuel, 2), bright=seen.bright)
        return not seen.bright or self.stars.fuel_jumps(seen.fuel) >= jumps

    def location(self) -> str:
        """The system name in the HUD's top right box."""
        image = self.frame()
        crop = image[6:36, image.shape[1] - 170:image.shape[1] - 6]
        lines = self.read(cv2.resize(crop, None, fx=2, fy=2, interpolation=cv2.INTER_CUBIC))
        return lines[0].text if lines else ""

    def fly_until(self, done, what: str, seconds: float = 180.0, fight_back: bool = True) -> bool:
        """Lets the autopilot fly while watching the HUD: dialogs get answered, attackers get answered. Never coasts blind past the limit."""
        started = time.monotonic()
        while time.monotonic() - started < seconds:
            self.guard()
            image = self.frame()
            h = hudlib.read_hud(image)
            if not h.bright:
                self.hands.release_all()
                if done():
                    return True
                self.settle_panels(12)
                continue
            if fight_back and h.shields < 0.55 and h.nearest_hostile is not None:
                self.say("Under attack on the way: fighting back.")
                self.fight(lambda: False, seconds=60, stop_when_clear=True)
                return False
            if done():
                return True
            time.sleep(0.25)
        self.say(f"{what} took too long.")
        return False

    def here(self) -> str:
        """The system the HUD says the ship is in, matched to the star map (the reader can miss a letter). Blank during a jump's flash."""
        read = self.location().strip()
        if read in self.stars.positions:
            return read
        import difflib

        close = difflib.get_close_matches(read, list(self.stars.positions), n=1, cutoff=0.7)
        return close[0] if close else ""

    def here_settled(self, seconds: float = 15.0) -> str:
        """Waits out a jump's flash or a panel for a clean reading of the system's name."""
        ends = time.monotonic() + seconds
        while time.monotonic() < ends:
            self.guard()
            if not hudlib.is_bright(self.frame()):
                self.settle_panels(4)
            name = self.here()
            if name:
                return name
            time.sleep(0.4)
        return ""

    def jump(self, system: str, hops: int = 10) -> bool:
        """Hop by hop along the shortest route, working it out again from wherever the ship really arrived."""
        for _ in range(hops):
            here = self.here_settled()
            if here == system:
                self.say(f"Arrived in {system}.")
                self.shot("arrived")
                return True
            route = self.stars.route(here, system) if here else []
            if not route:
                self.say(f"I see no route from {here!r} to {system}.")
                return False
            if not self.fuel_ok():
                self.say(f"Fuel is out in {here}: a jump would strand me. Landing to refuel first.")
                self.land()
                self.depart()
                self.settle_panels(3)
                if not self.fuel_ok():
                    raise RuntimeError(f"no fuel in {here} and none gained by landing")
            self.set_hop(here, route[0])
            self.tap(self.card["jump"], settle=0.5)
            self.say(f"Jumping to {route[0]}.")
            self.fly_until(lambda: self.here() not in ("", here), f"The jump to {route[0]}", 90)
        return self.here() == system

    def land(self, planet: str = "") -> View:
        """Land on `planet` (the land key cycles through what the system has) or the nearest, and read through what greets the ship."""
        self.say(f"Landing{' on ' + planet if planet else ''}.")
        self.tap(self.card["land"], settle=0.8)
        if planet:
            for _ in range(5):
                bottom = self.frame()
                lines = self.read(bottom[bottom.shape[0] - 60:])
                if any(planet.lower() in l.text.lower() for l in lines):
                    break
                self.tap(self.card["land"], settle=0.8)
        self.fly_until(self.landed, "The landing", 120)
        seen = self.settle_panels()
        self.shot("landed")
        return seen

    # ---- jobs ----------------------------------------------------------------------------------------------------------------------
    def accept_job(self, words: str, limit: int = 40) -> bool:
        """On the job board, walks down the list until the job's text shows `words`, and accepts it."""
        self.tap("j", settle=1.2)
        seen = self.view()
        for _ in range(limit):
            if seen.has(words):
                break
            self.tap("down", settle=0.5)
            seen = self.view()
        if not seen.has(words):
            self.tap("d", settle=0.8)
            return False
        self.shot("job-found")
        self.tap("a", settle=1.0)
        self.settle_panels(6)
        self.shot("job-accepted")
        self.tap("d", settle=0.8)
        return True

    def fresh_pilot(self, since: float, seconds: float = 6.0) -> Pilot | None:
        """The pilot as saved after `since`: the game writes the file a moment after a panel closes, so an instant read would be the old one."""
        ends = time.monotonic() + seconds
        while time.monotonic() < ends and save_time(self.pilot_name) <= since:
            time.sleep(0.2)
        return self.pilot()

    def accept_bounty(self, limit: int = 30) -> str:
        """Reads the job board from the screen (the save is only written at takeoff). Returns the bounty's title, or '' when none is posted."""
        self.tap("j", settle=1.2)
        seen = self.view()
        self.shot("job-board")
        found = bounty_line(seen.lines)
        for _ in range(limit):
            if found is not None or seen.has("no jobs"):
                break
            before = " ".join(l.text for l in seen.lines)
            self.tap("down", settle=0.4)
            seen = self.view()
            found = bounty_line(seen.lines)
            if " ".join(l.text for l in seen.lines) == before:
                break
        if found is None:
            self.tap("d", settle=0.8)
            return ""
        title = found.text
        for _ in range(limit):  # the description box shows only the selected job; a Sparrow takes the smallest target on the board
            if seen.has("small pirate fighter", "destroy"):
                break
            self.tap("down", settle=0.5)
            seen = self.view()
        if not seen.has("small pirate fighter", "destroy"):
            self.tap("d", settle=0.8)
            return ""
        self.shot("bounty-selected")
        self.tap("a", settle=1.0)
        self.settle_panels(6)
        self.shot("bounty-accepted")
        self.log("accepted", title=title)
        self.tap("d", settle=0.8)
        return title

    # ---- combat --------------------------------------------------------------------------------------------------------------------
    def fight(self, done, seconds: float = 180.0, stop_when_clear: bool = False, rules: flight.Rules = flight.Rules(weapon_range=flight.BLASTER_RANGE), patience: float = 4.0) -> str:
        """The dogfight loop, 20 looks a second. Returns 'done', 'clear', 'retreat', 'panel' or 'timeout'."""
        started, clear_since, last_say, ticks = time.monotonic(), None, 0.0, 0
        rate, speedo = flight.RangeRate(), hudlib.Speedometer()
        try:
            while time.monotonic() - started < seconds:
                self.guard()
                image = self.frame()
                h = hudlib.read_hud(image)
                if not h.bright:
                    return "panel"
                if done():
                    return "done"
                now = time.monotonic()
                near = h.nearest_hostile
                closing = rate.update(now, near.distance if near else None)
                drift = speedo.update(image, now)
                order = flight.fight_tick(h, self.card, rules, closing, drift)
                if order.retreat:
                    self.say(order.say)
                    self.hands.release_all()
                    self.hands.tap(self.card["land"], 0.08)
                    return "retreat"
                for key in order.taps:
                    self.hands.tap(key, 0.05)
                self.hands.hold_only(order.keys)
                ticks += 1
                near = h.nearest_hostile
                if near is None and not h.has_target:
                    clear_since = clear_since or time.monotonic()
                    if time.monotonic() - clear_since > patience:
                        return "clear"
                    if ticks % 30 == 0:
                        self.hands.tap(self.card["hostile"], 0.05)  # selects a hostile anywhere in the system, even off the radar
                else:
                    clear_since = None
                if ticks % 20 == 0:
                    self.log("fight", shields=round(h.shields, 2), hull=round(h.hull, 2), energy=round(h.energy, 2), heat=round(h.heat, 2),
                             target_shields=round(h.target_shields, 2), target_hull=round(h.target_hull, 2),
                             range=round(near.distance) if near else None, closing=round(closing), drift=round(drift), keys=sorted(order.keys))
                if time.monotonic() - last_say > 6.0:
                    last_say = time.monotonic()
                    if near is not None:
                        self.say(f"Fighting: range {near.distance:.0f}, my shields {h.shields:.0%}, hull {h.hull:.0%}; target shields {h.target_shields:.0%}, hull {h.target_hull:.0%}.")
                time.sleep(0.03)
            return "timeout"
        finally:
            self.hands.release_all()
