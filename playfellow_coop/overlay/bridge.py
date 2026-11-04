"""One widget, however it was started. The main command's widget (`--window ... --overlay`) follows the same small files as the game
packs' widget (`games.stk.widget`): STOP, HANDOVER, the feed and the lock. So `python -m playfellow_coop mcp --game "<the same title>"`
lets Meta's Muse Code, or any MCP agent, drive it: say a line, stop, hand over and take back, open or fold it, set its see-through
level, and pass words to the buddy. The player's own F9 is written to the hand-over file, so an agent can never undo it, and an
agent's words wait while the player holds the controls. Polled a few times a second; nothing here reaches the network."""
from __future__ import annotations

import os
import threading
from pathlib import Path
from typing import Callable

POLL_SECONDS = 0.2


class WidgetBridge:
    def __init__(self, files: dict, on_event: Callable[[tuple], None], handover, safety, commands, pid: int | None = None):
        self.files, self.on_event, self.handover, self.safety, self.commands = files, on_event, handover, safety, commands
        self.pid = os.getpid() if pid is None else pid
        self._offset = 0
        self._last_file = False
        self._last_human = False
        self._stop = threading.Event()

    def _emit(self, kind: str, data) -> None:
        self.on_event((kind, data))

    def start_files(self) -> None:
        """Make the game's folder, say this widget is running, and read the feed only from now on."""
        folder: Path = self.files["dir"]
        folder.mkdir(parents=True, exist_ok=True)
        self.files["lock"].write_text(str(self.pid), encoding="utf-8")
        feed: Path = self.files["feed"]
        self._offset = feed.stat().st_size if feed.exists() else 0
        self._last_file = self.files["handover"].exists()
        self._last_human = bool(self.handover.human_has_controls)

    def _player_holds(self) -> bool:
        if self.files["stop"].exists():
            return True
        try:
            return self.files["handover"].exists() and self.files["handover"].read_text(encoding="utf-8").strip() != "agent"
        except OSError:
            return True

    def poll(self) -> None:
        from messages import tr

        from playfellow_coop.games.stk.widget import parse_control
        from playfellow_coop.handover import taken_line

        # a stop from the file (an agent, the pack's widget, or "stop" typed anywhere) is the same stop as F12
        if self.files["stop"].exists() and not getattr(self.safety, "stopped", False):
            self.safety.stop("stopped_button")
            self._emit("say", tr("Stopped: every key is up.", "توقفت: كل الأزرار مرفوعة."))
        # the hand-over, both ways: a changed file drives the session; the player's own F9 is written to the file
        file_now, human_now = self.files["handover"].exists(), bool(self.handover.human_has_controls)
        if file_now != self._last_file:
            if file_now and not human_now and self.handover.take_over():
                self._emit("say", taken_line())
            elif not file_now and human_now:
                line = self.handover.give_back()
                if line:
                    self._emit("say", line)
        elif human_now != self._last_human:
            if human_now:
                self.files["handover"].write_text("you", encoding="utf-8")
            else:
                self.files["handover"].unlink(missing_ok=True)
        self._last_file, self._last_human = self.files["handover"].exists(), bool(self.handover.human_has_controls)
        # new feed lines: shown, applied to the widget, or passed to the buddy as typed words
        feed: Path = self.files["feed"]
        if not feed.exists():
            return
        with open(feed, encoding="utf-8") as fh:
            fh.seek(self._offset)
            chunk = fh.read()
            self._offset = fh.tell()
        for line in chunk.splitlines():
            body = line.strip()[9:] if line[2:3] == ":" else line.strip()
            if not body or body.startswith("~"):
                continue
            control = parse_control(body)
            if control is None:
                if not body.startswith("!"):
                    self._emit("say", body)
                continue
            if control[0] == "type":
                if self._player_holds():
                    self._emit("say", tr(f"An agent asked '{control[1]}', but you have the controls (or everything is stopped), so I left it.",
                                         f"طلب وكيل '{control[1]}'، لكن التحكم معك (أو كل شيء متوقف)، فتركته."))
                else:
                    self.commands.put(control[1])
            else:
                self._emit("control", control)

    def run(self) -> None:  # pragma: no cover - the thread loop around poll()
        while not self._stop.is_set():
            try:
                self.poll()
            except OSError:
                pass  # a file being written right now: the next poll reads it
            self._stop.wait(POLL_SECONDS)

    def start(self) -> None:  # pragma: no cover - starts a thread
        self.start_files()
        threading.Thread(target=self.run, name="widget-bridge", daemon=True).start()

    def close(self) -> None:
        self._stop.set()
        try:
            if self.files["lock"].read_text(encoding="utf-8").strip() == str(self.pid):
                self.files["lock"].unlink()
        except OSError:
            pass
