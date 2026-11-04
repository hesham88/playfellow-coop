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
SEE_THROUGH = "see_through"
DONE = "__done__"


class OverlayRunner:
    def __init__(self, model: PanelModel, view, handover=None, safety=None, pump=None):
        self.model, self.view, self.handover, self.safety, self.pump = model, view, handover, safety, pump
        self._events: queue.SimpleQueue = queue.SimpleQueue()
        self._closed = False
        self.closes = 0
        self.extra_pumps: list = []  # more widget keys (the see-through key), started and stopped with the window

    # ---- from any thread -----------------------------------------------------------------------------------------
    def event(self, kind: str, data) -> None:
        """The session's on_event: safe to call from any thread."""
        self._events.put((kind, data))

    def summon(self) -> None:
        """The summon hotkey's press (it arrives on the hotkey thread)."""
        self._events.put((SUMMON, None))

    def step_opacity(self) -> None:
        """The see-through key's press (it arrives on its hotkey thread)."""
        self._events.put((SEE_THROUGH, None))

    def finish(self) -> None:
        """The session ended: close the window (the main thread does it)."""
        self._events.put((DONE, None))

    # ---- on the main thread --------------------------------------------------------------------------------------
    def _apply(self, kind: str, data) -> None:
        if kind == SUMMON:
            self.model.toggle()
        elif kind == SEE_THROUGH:
            self.model.step_opacity()
        elif kind in ("say", "status") and data:
            self.model.buddy_says(str(data))
        elif kind == "control" and data:  # an agent's widget control, from the shared files (overlay/bridge.py)
            action, value = data
            if action == "open":
                self.model.show()
            elif action == "fold":
                self.model.hide()
            elif action == "opacity":
                self.model.set_opacity(value)
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
        for pump in [self.pump, *self.extra_pumps]:
            if pump is not None:
                pump.stop()
        self.view.close()

    def run(self) -> None:
        """Show the pill, start the summon key, and run the window loop until the session finishes (main thread only)."""
        self.view.start()
        for pump in [self.pump, *self.extra_pumps]:
            if pump is not None:
                pump.start()
        self.view.root.after(POLL_MS, self.tick)
        self.view.mainloop()


class OverlayUnavailableError(RuntimeError):
    """The overlay cannot open, said in plain words (for example Qt missing)."""


def panel_focus_listener(model, set_typing: Callable[[bool], None]) -> Callable[[], None]:
    """A model listener: the open panel may take the keyboard for typing, folded it never does; `set_typing` runs only on a change."""
    state = {"on": False}

    def listener() -> None:
        want = bool(model.visible)
        if want != state["on"]:
            state["on"] = want
            set_typing(want)
    return listener


def _qt_typing(view, model) -> Callable[[bool], None]:  # pragma: no cover - needs a desktop
    """The Qt/Windows side of typing in the panel (the same steps as the SuperTuxKart widget)."""
    def set_typing(want: bool) -> None:
        from PySide6.QtCore import Qt

        from playfellow_coop.overlay import winstyle

        view.allow_focus = want
        view.window.setWindowFlag(Qt.WindowType.WindowDoesNotAcceptFocus, not want)
        view.window.show()
        view.hwnd = int(view.window.winId())
        try:  # keep the view's own recording and click-through choices; only the focus bit changes
            winstyle.apply_overlay_style(view.hwnd, click_through=bool(getattr(model, "click_through", False)),
                                         show_in_recordings=bool(getattr(view, "_show_in_recordings", False)), allow_focus=want)
        except OSError:
            pass
        if want:
            view.window.activateWindow()
            view.entry.setFocus()
    return set_typing


def game_follow(screen, title: str) -> Callable[[], tuple[int, int, int, int] | None]:
    """The widget's anchor: the chosen game's client area (left, top, right, bottom) from the engine's own window finder, or
    None while the game is minimised or gone (the widget then keeps its last place). Never raises: a desktop hiccup is not a crash."""
    def follow() -> tuple[int, int, int, int] | None:
        try:
            box = screen.find(title)
        except Exception:  # the finder talks to the desktop; any failure means "not visible now"
            return None
        if box is None:
            return None
        return box.left, box.top, box.left + box.width, box.top + box.height
    return follow


def build_overlay(parts, commands, handover, summon_key: str = "ctrl+alt+p", on_talk_down: Callable[[], None] = lambda: None,
                  on_talk_up: Callable[[], None] = lambda: None, see_through_key: str = "ctrl+alt+o") -> OverlayRunner:
    """The real thing: the Qt glass view, the panel model, and the summon
    hotkey (refused if the game's controls card uses that key). The overlay
    is Qt only: when PySide6 is not installed it says so and does not open
    any window. Imports the toolkit here, so nothing else needs it."""
    from playfellow_coop.overlay.hotkey import Hotkey
    from playfellow_coop.overlay.pump import HotkeyPump

    model = PanelModel(commands)
    try:
        from playfellow_coop.overlay.qt_view import QtOverlay

        view = QtOverlay(model, on_talk_down=on_talk_down, on_talk_up=on_talk_up,
                         on_stop=lambda: parts.safety.stop("stopped_button"), on_hand_over=lambda: handover.toggle(),
                         follow=getattr(parts, "follow", None))  # docked at the top centre of the chosen game, moving with it
    except ImportError as error:
        raise OverlayUnavailableError(
            "The command center needs Qt (PySide6), which is not installed, so it cannot open."
        ) from error
    # Changing the focus flag re-creates the window and Qt would take that moment for "the last window closed": the loop ends only
    # when the session ends (view.close quits it), as in the SuperTuxKart widget.
    view.app.setQuitOnLastWindowClosed(False)
    model.subscribe(panel_focus_listener(model, _qt_typing(view, model)))  # open to type; folded it never takes focus
    model.on_submitted = getattr(parts, "give_back_focus", None)  # the command is in: the game gets the front back
    runner = OverlayRunner(model, view, handover=handover, safety=parts.safety)
    runner.pump = HotkeyPump(Hotkey(summon_key, card=parts.card), on_press=runner.summon)
    see_through_key = getattr(parts, "see_through_key", None) or see_through_key  # --see-through-key
    runner.extra_pumps.append(HotkeyPump(Hotkey(see_through_key, card=parts.card, hotkey_id=0x5047), on_press=runner.step_opacity))
    model.set_keys(talk=getattr(parts, "talk_key", "") or None, panel=summon_key, see_through=see_through_key)
    from playfellow_coop.overlay.hotkey import widget_key_note
    note = widget_key_note(parts.card, summon_key, see_through_key)
    if note:
        model.buddy_says(note)  # in full screen the terminal is hidden: the widget's chat carries the warning too
    return runner
