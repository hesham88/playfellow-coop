"""The PlayFellow widget, kept up for as long as the buddy has the game: one process, docked at the top centre of the game
window and following it, shown in recordings, its bar carrying the buddy's latest line.

    python -m playfellow_coop.games.stk.widget            # start once; every buddy part then writes to the feed

Never a black box (owner, 3 Nov): every part of the buddy appends its lines to the feed (`say_line`) and keeps a one-line
status (`set_status`: what it is doing, or what it is waiting for). When no new line has come for a while, the widget shows
that status, so the bar is never stale and the buddy never goes silent.

Keys and input, all of them working in this widget:
  F12        stop: every buddy session stops and lets go of every key
  F9         hand over: the buddy lets go of every key and waits; F9 again gives the controls back
  typing     the panel's text box: "stop", "wait" / "hand over" / "you take it", "go" / "take it back"; anything else is noted
  mic        hold the bar's mic button, speak, release: Muse Voice turns it into the same commands (English or Arabic)
"""
from __future__ import annotations

import argparse
import re
import threading
import time
from pathlib import Path

from playfellow_coop.games.stk.paths import BUDGET, HOME, KEY_FILE, VOICE_BUDGET

FEED = HOME / "live-feed.txt"
LOCK = HOME / "widget.pid"
STOP = HOME / "STOP"  # written by F12 / "stop": every buddy session stops on it
HANDOVER = HOME / "HANDOVER"  # F9 / "wait": while it exists the buddy holds no key and waits
STATUS = HOME / "STATUS"  # one line: what the buddy is doing or waiting for right now
COMMANDS = HOME / "commands.txt"  # everything typed or said, for the sessions and the record
QUIET_AFTER = 15.0  # seconds without a new line before the status is shown again


def say_line(text: str, feed: Path = FEED) -> None:
    """Hand one line to the running widget (and keep it in the feed file as a transcript)."""
    feed.parent.mkdir(parents=True, exist_ok=True)
    with open(feed, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {text}\n")


def set_status(text: str) -> None:
    """What the buddy is doing or waiting for, shown whenever the bar would otherwise go quiet."""
    STATUS.parent.mkdir(parents=True, exist_ok=True)
    STATUS.write_text(text, encoding="utf-8")


def hand_over(on: bool) -> str:
    if on:
        HANDOVER.write_text("you", encoding="utf-8")
        return "You have the controls: I let go of every key and wait. F9 or 'go' gives them back to me."
    HANDOVER.unlink(missing_ok=True)
    return "I have the controls again."


def command(text: str) -> str:
    """What a typed or spoken command does, in words for the bar."""
    said = text.strip()
    low = said.lower()
    with open(COMMANDS, "a", encoding="utf-8") as fh:
        fh.write(f"{time.strftime('%H:%M:%S')} {said}\n")
    if re.search(r"\b(stop|halt)\b|توقف|قف", low):
        STOP.write_text("stop", encoding="utf-8")
        return f"Heard '{said}': stopping everything and letting go of every key."
    # hand-over and go count only when the message STARTS with them ("go faster on the straights" is advice, not "go");
    # "stop" anywhere stops, the safe direction
    if re.match(r"\s*(wait|hand over|you take it|my turn|i got it|i've got it)\b|\s*(استنى|انتظر|خدها|اخذها)", low):
        return f"Heard '{said}'. " + hand_over(True)
    if re.match(r"\s*(go|continue|resume)\W*$|\s*(take it back|your turn)\b|\s*(كمل|يلا)", low):
        STOP.unlink(missing_ok=True)
        return f"Heard '{said}'. " + hand_over(False)
    move = driving_command(low)
    if move:  # a direct racing command: straight to the driver, no model in between (it acts within a tick)
        with open(NUDGE, "a", encoding="utf-8") as fh:
            fh.write(f"{time.time():.2f} {move}\n")
        return f"Heard '{said}': {MOVE_WORDS[move]}."
    if CHAT is not None:  # anything else: the buddy's brain answers properly (on its own thread; the bar says it is thinking)
        threading.Thread(target=CHAT, args=(said,), daemon=True).start()
        return f"Heard '{said}'. Thinking..."
    return f"Heard '{said}'. Noted for the next race; right now: {status_text()}"


NUDGE = HOME / "nudge.txt"  # direct racing commands for the running driver (it reads new lines each tick)
MOVE_WORDS = {"left": "steering left now", "right": "steering right now", "straight": "holding it straight",
              "nitro": "nitro now", "fire": "firing my item", "drift": "drifting into this bend", "brake": "braking",
              "rescue": "rescue now", "look_back": "looking back", "faster": "pushing harder this race",
              "slower": "taking it calmer this race"}
MOVE_PATTERNS = (("look_back", r"look(ing)? back|behind|ورا"), ("left", r"\bleft\b|يسار|شمال"), ("right", r"\bright\b|يمين"),
                 ("straight", r"\bstraight\b|دغري|على طول|مستقيم"), ("nitro", r"\bnitro|\bboost\b|\bturbo\b|نيترو"),
                 ("fire", r"\bfire\b|\bshoot\b|\bthrow\b|اضرب"), ("drift", r"\bdrift|\bskid\b|درفت"),
                 ("brake", r"\bbrake\b|\bslow down\b|فرامل"), ("rescue", r"\brescue\b|\bstuck\b|انقاذ"),
                 ("faster", r"\bfaster\b|\bpush\b|\bquicker\b|اسرع"), ("slower", r"\bslower\b|\bcalm(er)?\b|براحة"))


def driving_command(low: str) -> str | None:
    """A short racing command ('left', 'nitro!', 'shoot now', ...) or None. Long sentences go to the brain instead."""
    if len(low.split()) > 4:
        return None
    for name, pattern in MOVE_PATTERNS:
        if re.search(pattern, low):
            return name
    return None


CHAT = None  # set by the running widget: (text) -> None, answers in the bar through Muse


TUNE = HOME / "tune.json"  # live driving tweaks from the player's tips, read by the race loop
TUNINGS = ("more_nitro", "more_items", "dodge_more", "calmer")

CHAT_SYSTEM = ("You are Fello, a friendly game buddy playing SuperTuxKart for the player, who talks to you through a small bar "
               "over the game. Reply with JSON only: {\"reply\": one or two short, warm, concrete sentences, \"action\": one of "
               "stop, hand_over, take_back, menu, restart, race, press, goal, none, \"keys\": for press, a list of up, down, left, right, enter, esc, \"goal\": for goal, what to reach in the game's menus in plain words, \"difficulty\": novice, intermediate, expert or empty, "
               "\"tune\": a list from more_nitro, more_items, dodge_more, calmer (or empty)}. "
               "hand_over = the player wants to drive now; take_back = the player wants you to drive; stop = stop everything; "
               "menu = YOU go back to the game's main menu with the keyboard (you can: never say you can't); press = you press those menu keys now (for 'press enter', 'go down'); goal = you reach a menu item by reading the screen ('open singleplayer', 'pick Expert'); restart = you "
               "restart the current race; race = you start a single-player Normal Race at the given difficulty (for 'next "
               "difficulty' pick the one after the last one in the context; the order is novice, intermediate, expert). "
               "tune changes your driving live: more_nitro = nitro taps more often on straights; more_items = pull harder "
               "toward gift boxes and nitro; dodge_more = steer harder around bananas and crates; calmer = slower into bends. "
               "Promise ONLY what an action or a tune you return will do; if a tip cannot be done, say so plainly. Never claim "
               "something the context does not show. Reply in the player's language.")


def make_chat(say, recent_lines):  # pragma: no cover - network
    """The widget's brain for free text: Muse reads the context (status, recent bar lines) and answers, maybe with an action."""
    from playfellow_coop.budget import DailyBudget
    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

    brain_box: dict = {}

    def chat(text: str) -> None:
        try:
            if "b" not in brain_box:
                from playfellow_coop.games.stk.brains import load_key

                key = load_key(KEY_FILE)
                brain_box["b"] = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(
                    BUDGET, 30.0, 20000), effort="minimal", cache_key=None)
                brain_box["b"].max_tokens = 800
            context = f"Right now: {status_text()}\nRecent bar lines:\n" + "\n".join(recent_lines()[-12:])
            answer = brain_box["b"].ask(CHAT_SYSTEM, f"{context}\n\nThe player says: {text}", [])
            match = re.search(r"\{.*\}", answer, re.S)
            import json

            data = json.loads(match.group(0)) if match else {"reply": answer.strip()[:200], "action": "none"}
        except Exception as error:  # noqa: BLE001 - said in the bar, never silent
            say(f"I couldn't think that through ({type(error).__name__}: {str(error)[:80]}). Commands always work: stop, wait, take it back.")
            return
        action = data.get("action", "none")
        extra = ""
        if action == "stop":
            STOP.write_text("stop", encoding="utf-8")
            extra = " (stopping now)"
        elif action == "hand_over":
            extra = " " + hand_over(True)
        elif action == "take_back":
            STOP.unlink(missing_ok=True)
            extra = " " + hand_over(False)
        elif action in ("menu", "restart", "race", "press", "goal"):  # game actions, carried out through the guarded keyboard
            import subprocess
            import sys as _sys

            STOP.unlink(missing_ok=True)
            HANDOVER.unlink(missing_ok=True)
            args = [action] + ([data.get("difficulty") or "intermediate"] if action == "race" else [])
            if action == "press":
                args += [k for k in (data.get("keys") or []) if k in ("up", "down", "left", "right", "enter", "esc")][:6] or ["enter"]
            if action == "goal":
                args.append(str(data.get("goal") or text)[:200])
            subprocess.Popen([_sys.executable, "-m", "playfellow_coop.games.stk.act", *args],
                             creationflags=0x00000008 | 0x00000200)
            extra = f" (doing it now: {' '.join(args)})"
        tunes = [t for t in (data.get("tune") or []) if t in TUNINGS]
        if tunes:
            import json

            try:
                current = json.loads(TUNE.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                current = {}
            for t in tunes:
                current[t] = True
            TUNE.write_text(json.dumps(current), encoding="utf-8")
            extra += f" (live now: {', '.join(t.replace('_', ' ') for t in tunes)})"
        say(str(data.get("reply", "")).strip() + extra)

    return chat


def status_text() -> str:
    if HANDOVER.exists():
        return "you have the controls; I'm holding no key and waiting for F9 or 'go'."
    if STOP.exists():
        return "stopped (F12 or 'stop'); nothing is pressed. Say 'go' when you want me back."
    try:
        text = STATUS.read_text(encoding="utf-8").strip()
    except OSError:
        text = ""
    return text or "not driving right now; nothing is pressed."


def widget_running() -> bool:
    try:
        pid = int(LOCK.read_text())
    except (OSError, ValueError):
        return False
    try:
        import ctypes

        handle = ctypes.windll.kernel32.OpenProcess(0x1000, False, pid)
        if not handle:
            return False
        code = ctypes.c_ulong()
        ctypes.windll.kernel32.GetExitCodeProcess(handle, ctypes.byref(code))
        ctypes.windll.kernel32.CloseHandle(handle)
        return code.value == 259  # STILL_ACTIVE
    except OSError:
        return LOCK.exists()


class PushToTalk:  # pragma: no cover - needs a microphone and the network
    """Hold the mic: record; release: Muse Voice transcribes on a worker thread and the words become a command."""

    def __init__(self, on_text, on_say):
        self.on_text, self.on_say = on_text, on_say
        self.mic = None
        self.reader = None

    def down(self) -> None:
        try:
            from playfellow_coop.microphone import Microphone

            self.mic = Microphone()
            self.mic.start()
            self.on_say("Listening... (release the mic when done)")
        except Exception as error:  # noqa: BLE001 - said in the bar, never silent
            self.mic = None
            self.on_say(f"The mic could not start ({type(error).__name__}): type the command instead.")

    def up(self) -> None:
        mic, self.mic = self.mic, None
        if mic is None:
            return
        mic.stop()
        frames = list(mic.chunks())
        threading.Thread(target=self._transcribe, args=(frames,), daemon=True).start()

    def _transcribe(self, frames: list[bytes]) -> None:
        import io
        import wave

        if not frames:
            self.on_say("I didn't hear anything.")
            return
        self.on_say("Got it, working out what you said...")
        try:
            from playfellow_coop.budget import DailyBudget
            from playfellow_coop.voice import MuseVoiceTranscriber

            buffer = io.BytesIO()
            with wave.open(buffer, "wb") as clip:
                clip.setnchannels(1)
                clip.setsampwidth(2)
                clip.setframerate(24000)
                clip.writeframes(b"".join(frames))
            if self.reader is None:
                from playfellow_coop.games.stk.brains import load_key

                key = load_key(KEY_FILE)
                self.reader = MuseVoiceTranscriber(key, budget=DailyBudget(
                    VOICE_BUDGET, 2.0, 500))
            text = self.reader.transcribe(buffer.getvalue()).strip()
        except Exception as error:  # noqa: BLE001 - said in the bar
            self.on_say(f"I couldn't make out the words ({type(error).__name__}); type it instead.")
            return
        if not text:
            self.on_say("I didn't hear anything.")
            return
        self.on_text(text)


def main(argv=None) -> None:  # pragma: no cover - needs a real desktop
    import os

    p = argparse.ArgumentParser()
    p.add_argument("--feed", default=str(FEED))
    a = p.parse_args(argv)
    feed = Path(a.feed)
    feed.parent.mkdir(parents=True, exist_ok=True)
    feed.touch()
    LOCK.write_text(str(os.getpid()))

    try:  # the 3D character's web engine must be loaded before the Qt application exists
        import PySide6.QtWebEngineWidgets  # noqa: F401
    except ImportError:
        pass
    from playfellow_coop.games.stk.io import GameWindow
    from playfellow_coop.overlay.panel import PanelModel
    from playfellow_coop.overlay.qt_view import QtOverlay
    from playfellow_coop.overlay.runner import OverlayRunner
    from playfellow_coop.voice import CommandQueue

    window = GameWindow()
    commands = CommandQueue()
    model = PanelModel(commands)
    model.ticker = True
    runner_box: dict = {}

    def bar(text: str) -> None:
        runner_box["r"].event("say", text)
        with open(feed, "a", encoding="utf-8") as fh:  # also into the transcript (marked so the tail does not repeat it)
            fh.write(f"{time.strftime('%H:%M:%S')} ~{text}\n")

    def recent_lines() -> list[str]:
        try:
            return feed.read_text(encoding="utf-8").splitlines()[-30:]
        except OSError:
            return []

    global CHAT
    CHAT = make_chat(bar, recent_lines)
    talk = PushToTalk(on_text=lambda text: bar(command(text)), on_say=bar)
    view = QtOverlay(model, show_in_recordings=True, follow=window.client_box, on_talk_down=talk.down, on_talk_up=talk.up,
                     on_stop=lambda: bar(command("stop")), on_hand_over=lambda: bar(hand_over(not HANDOVER.exists())))
    model.chip_set = (("Wait, my turn", "استنى، دوري"), ("Take it back", "كمل"), ("Stop", "توقف"))
    runner = OverlayRunner(model, view)
    runner_box["r"] = runner
    typing = {"on": False}

    def on_panel_change():  # on the Qt thread: the open panel may take focus for typing; folded, it never does
        want = bool(model.visible)
        if want == typing["on"]:
            return
        typing["on"] = want
        from PySide6.QtCore import Qt

        view.allow_focus = want
        view.window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not want)
        view.window.show()
        view.hwnd = int(view.window.winId())
        from playfellow_coop.overlay import winstyle

        winstyle.apply_overlay_style(view.hwnd, click_through=False, show_in_recordings=True, allow_focus=want)
        if want:
            view.window.activateWindow()
            view.entry.setFocus()
            bar("Type a command and press Enter (stop / wait / take it back), or hold the mic.")

    model.subscribe(on_panel_change)
    model.set_opacity(0.90)  # owner 3 Nov: 90% by default over the game
    from playfellow_coop.overlay.avatar import Avatar
    from playfellow_coop.overlay.avatar3d import Avatar3D

    avatar_box: dict = {}
    model.show_name = False  # the character beside the bar says who is talking
    try:
        try:
            avatar_box["a"] = Avatar3D(view.window, height=84)  # the real 3D model (lite Meshy GLB, its own clips)
        except Exception as error3d:  # noqa: BLE001 - no web engine or GPU: the 2D sheets, said
            print(f"3D avatar could not start ({type(error3d).__name__}: {error3d}); using the 2D frames", flush=True)
            avatar_box["a"] = Avatar(view.window, height=64)
        choice_row = avatar_box["a"].make_choice(view.panel)
        view.panel_layout.insertWidget(1, choice_row)  # in the expanded panel, under the bar
        choice_row.setVisible(bool(model.visible))
        model.subscribe(lambda: choice_row.setVisible(bool(model.visible)))
    except Exception as error:  # noqa: BLE001 - the bar works without the character; said, never silent
        print(f"avatar could not start: {type(error).__name__}: {error}", flush=True)
    from PySide6.QtCore import QTimer

    mood_inbox: list = []

    def feed_avatar():  # on the Qt thread: the feed thread drops lines in, the character reacts here
        while mood_inbox and "a" in avatar_box:
            avatar_box["a"].react(mood_inbox.pop(0))

    mood_timer = QTimer()
    mood_timer.setInterval(150)
    mood_timer.timeout.connect(feed_avatar)
    mood_timer.start()
    last_line = {"at": time.monotonic()}

    def tail():
        with open(feed, encoding="utf-8") as fh:
            fh.seek(0, 2)  # only lines written from now on
            runner.event("say", "Fello is here. " + status_text())
            while True:
                line = fh.readline()
                if line:
                    body = line.strip()[9:] if line[2:3] == ":" else line.strip()
                    if not body.startswith("~"):
                        runner.event("say", body)
                    mood_inbox.append(body.lstrip("~"))
                    last_line["at"] = time.monotonic()
                    continue
                if not window.user32.IsWindow(window.hwnd):  # the game closed: so does the widget
                    runner.finish()
                    from PySide6.QtCore import QMetaObject, Qt

                    QMetaObject.invokeMethod(view.app, "quit", Qt.ConnectionType.QueuedConnection)
                    return
                if time.monotonic() - last_line["at"] > QUIET_AFTER:  # never silent: say what it is doing or waiting for
                    runner.event("say", "Now: " + status_text())
                    last_line["at"] = time.monotonic()
                time.sleep(0.15)

    def keys():  # F12 stop, F9 hand over; reading key state presses nothing
        was12, was9 = False, False
        while True:
            down9 = window.key_is_down(0x78)
            if down9 and not was9:
                bar("F9: " + hand_over(not HANDOVER.exists()))
            was9 = down9
            down12 = window.key_is_down(0x7B)
            if down12 and not was12:
                bar("F12: " + command("stop").split(": ", 1)[1])
            was12 = down12
            for text in commands.drain():  # typed in the panel's box (or a chip)
                bar(command(text))
                window.focus()  # the command is in: the game gets the front back (it pauses itself without it)
            time.sleep(0.05)

    threading.Thread(target=tail, name="feed", daemon=True).start()
    threading.Thread(target=keys, name="keys", daemon=True).start()
    try:
        runner.run()
    finally:
        LOCK.unlink(missing_ok=True)


if __name__ == "__main__":
    main()
