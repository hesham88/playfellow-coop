"""Runs the floating command center next to the game session, so `--overlay` is a real switch and not a loose module.

The window toolkit must be driven from ONE thread (the main thread) while the game session runs on another, so nothing here touches
the window from the session's thread: events go into a queue, and the main thread empties it a few times a second. Like a mail
slot in a door: the session drops notes in, the window owner collects them.
"""
from __future__ import annotations

import queue
from typing import Callable

from playfellow_coop.overlay.panel import PanelModel

POLL_MS = 60
SUMMON = "summon"
DONE = "__done__"


class OverlayRunner:
    def __init__(self, model: PanelModel, view, handover=None, safety=None, pump=None):
        self.model, self.view, self.handover, self.safety, self.pump = model, view, handover, safety, pump
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._closed = False
        self.closes = 0

    # ---- from any thread -----------------------------------------------------------------------------------------
    def event(self, kind: str, data) -> None:
        """The session's on_event: safe to call from any thread."""
        self._events.put((kind, data))

    def summon(self) -> None:
        """The summon hotkey's press (it arrives on the hotkey thread)."""
        self._events.put((SUMMON, None))

    def finish(self) -> None:
        """The session ended: close the window (the main thread does it)."""
        self._events.put((DONE, None))

    # ---- on the main thread --------------------------------------------------------------------------------------
    def _apply(self, kind: str, data) -> None:
        if kind == SUMMON:
            self.model.toggle()
        elif kind in ("say", "status") and data:
            self.model.buddy_says(str(data))
        elif kind == DONE:
            self._close()

    def _sync_state(self) -> None:
        if self.safety is not None and getattr(self.safety, "stopped", False):
            self.model.set_state("stopped")
        elif self.handover is not None and self.handover.human_has_controls:
            self.model.set_state("player")
        elif self.model.state in ("player", "stopped"):
            self.model.set_state("ready")

    def tick(self) -> None:
        """Empty the queue, follow the hand-over, and schedule the next look."""
        while True:
            try:
                kind, data = self._events.get_nowait()
            except queue.Empty:
                break
            self._apply(kind, data)
        if not self._closed:
            self._sync_state()
            self.view.root.after(POLL_MS, self.tick)

    def _close(self) -> None:
        if self._closed:
            return
        self._closed = True
        self.closes += 1
        if self.pump is not None:
            self.pump.stop()
        self.view.close()

    def run(self) -> None:
        """Show the pill, start the summon key, and run the window loop until the session finishes (main thread only)."""
        self.view.start()
        if self.pump is not None:
            self.pump.start()
        self.view.root.after(POLL_MS, self.tick)
        self.view.mainloop()


def build_overlay(parts, commands, handover, summon_key: str = "ctrl+alt+p", on_talk_down: Callable[[], None] = lambda: None,
                  on_talk_up: Callable[[], None] = lambda: None) -> OverlayRunner:
    """The real thing: the Qt glass view when PySide6 is installed (the Tk
    view otherwise), the panel model, and the summon hotkey (refused if the
    game's controls card uses that key). Imports the toolkit here, so
    nothing else needs it."""
    from playfellow_coop.overlay.hotkey import Hotkey
    from playfellow_coop.overlay.pump import HotkeyPump

    model = PanelModel(commands)
    try:
        from playfellow_coop.overlay.qt_view import QtOverlay

        view = QtOverlay(model, on_talk_down=on_talk_down, on_talk_up=on_talk_up,
                         on_stop=lambda: parts.safety.stop("stopped_button"), on_hand_over=lambda: handover.toggle())
    except ImportError:
        from playfellow_coop.overlay.tk_view import TkOverlay

        view = TkOverlay(model, on_talk_down=on_talk_down, on_talk_up=on_talk_up,
                         on_stop=lambda: parts.safety.stop("stopped_button"), on_hand_over=lambda: handover.toggle())
    runner = OverlayRunner(model, view, handover=handover, safety=parts.safety)
    runner.pump = HotkeyPump(Hotkey(summon_key, card=parts.card), on_press=runner.summon)
    return runner
