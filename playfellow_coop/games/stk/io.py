"""The only door between the SuperTuxKart pre-skills and Windows.

Three promises, each enforced here and tested with fakes (tests/test_stk_io.py):
  1. nothing is sent unless the game window is the foreground window, checked before EVERY send (a press can never land in
     another program; when the owner clicks away, the buddy's keys simply stop);
  2. only keys on the allow-list go out (the controls card's keys plus the menu keys), never the mouse;
  3. every key the buddy holds comes back up: on release_all, on stop, and when the game loses the front (then nothing is sent:
     the game itself drops held keys when it loses focus, and a key-up must not land in another program either).
Every event that went out is appended to an audit list (written next to the run's recording), so a run can show what was pressed.
"""
from __future__ import annotations

import ctypes
import sys
import time
from dataclasses import dataclass, field
from typing import Callable

import numpy as np

from playfellow_coop.universal.winio import INPUT, key_input

WINDOW_TITLE = "SuperTuxKart"
MENU_KEYS = frozenset({"up", "down", "left", "right", "enter", "esc"})


class NotInFront(RuntimeError):
    """The game is not the foreground window, so nothing was sent."""


@dataclass
class Hands:
    """Keyboard only. `send` is SendInput (or a recorder in tests); `in_front` says whether the game window is the foreground window now."""

    allowed: frozenset[str]
    send: Callable[[list[INPUT]], int]
    in_front: Callable[[], bool]
    clock: Callable[[], float] = time.monotonic
    held: set[str] = field(default_factory=set)
    audit: list[tuple[float, str, str]] = field(default_factory=list)
    refused: int = 0
    owed: set[str] = field(default_factory=set)

    def _check(self, key: str) -> None:
        if key not in self.allowed:
            raise PermissionError(f"key {key!r} is not on this card's allow-list")

    def _out(self, key: str, up: bool) -> bool:
        if not self.in_front():
            self.refused += 1
            self.owed |= self.held  # nothing may be sent to another window, but the game may still think these are down:
            if up:                  # the key-ups are owed, and go out as soon as the game is back in front (settle)
                self.owed.add(key)
            self.held.clear()
            return False
        self.send([key_input(key, up=up)])
        self.audit.append((self.clock(), "up" if up else "down", key))
        return True

    def down(self, key: str) -> bool:
        self._check(key)
        if key in self.held:
            return True
        if self._out(key, up=False):
            self.held.add(key)
            return True
        return False

    def up(self, key: str) -> bool:
        self._check(key)
        if key not in self.held:
            return True
        self.held.discard(key)
        return self._out(key, up=True)

    def settle(self) -> None:
        """Send the key-ups owed from when the game was not in front."""
        if self.owed and self.in_front():
            for key in sorted(self.owed):
                self.send([key_input(key, up=True)])
                self.audit.append((self.clock(), "up", key))
            self.owed.clear()

    def clear(self) -> bool:
        """Key-up for every allowed key, whatever we think is held: the game starts from nothing pressed. A key still down
        when a race begins earns the game's start penalty (4 Nov). False when the game is not in front (nothing sent)."""
        if not self.in_front():
            return False
        for key in sorted(self.allowed):
            self.send([key_input(key, up=True)])
            self.audit.append((self.clock(), "up", key))
        self.held.clear()
        self.owed.clear()
        return True

    def hold_only(self, keys: set[str] | frozenset[str]) -> None:
        """Make exactly `keys` held: press the new ones, release the rest. One call per control tick."""
        self.settle()
        for key in sorted(self.held - set(keys)):
            self.up(key)
        for key in sorted(set(keys) - self.held):
            self.down(key)

    def tap(self, key: str, hold_s: float = 0.07, sleep: Callable[[float], None] = time.sleep) -> bool:
        if not self.down(key):
            return False
        sleep(hold_s)
        return self.up(key)

    def release_all(self) -> None:
        for key in sorted(self.held):
            self.up(key)
        self.held.clear()


class GameWindow:  # pragma: no cover - needs a real desktop
    """The SuperTuxKart window: where it is, whether it is in front, and bringing it to the front without pressing anything."""

    def __init__(self, title: str = WINDOW_TITLE):
        if sys.platform != "win32":
            raise OSError("needs Windows")
        try:
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except OSError:
            pass
        self.user32 = ctypes.WinDLL("user32", use_last_error=True)
        self.kernel32 = ctypes.WinDLL("kernel32")
        self.hwnd = int(self.user32.FindWindowW(None, title) or 0)
        if not self.hwnd:
            raise LookupError(f"no window titled {title!r}: start the game first")

    def client_box(self) -> tuple[int, int, int, int]:
        from ctypes import wintypes
        rect, point = wintypes.RECT(), wintypes.POINT(0, 0)
        self.user32.GetClientRect(self.hwnd, ctypes.byref(rect))
        self.user32.ClientToScreen(self.hwnd, ctypes.byref(point))
        return point.x, point.y, point.x + rect.right, point.y + rect.bottom

    def in_front(self) -> bool:
        return int(self.user32.GetForegroundWindow() or 0) == self.hwnd

    def focus(self) -> bool:
        """Bring the game up by attaching to the foreground thread's input queue (no key tap, no click). True when it is in front."""
        if self.in_front():
            return True
        foreground = self.user32.GetForegroundWindow()
        current, other = self.kernel32.GetCurrentThreadId(), self.user32.GetWindowThreadProcessId(foreground, None)
        attached = bool(other and other != current and self.user32.AttachThreadInput(current, other, True))
        try:
            self.user32.BringWindowToTop(self.hwnd)
            self.user32.SetForegroundWindow(self.hwnd)
        finally:
            if attached:
                self.user32.AttachThreadInput(current, other, False)
        time.sleep(0.25)
        return self.in_front()

    def send(self, packets: list[INPUT]) -> int:
        array = (INPUT * len(packets))(*packets)
        return int(self.user32.SendInput(len(packets), array, ctypes.sizeof(INPUT)))

    def key_is_down(self, vk: int) -> bool:
        """Reads a key's state (the owner's stop key); reading presses nothing."""
        return bool(self.user32.GetAsyncKeyState(vk) & 0x8000)

    def hands(self, allowed: frozenset[str]) -> Hands:
        return Hands(allowed=allowed, send=self.send, in_front=self.in_front)


class Eyes:  # pragma: no cover - needs a real desktop
    """Frames of the game's client area as numpy BGR arrays. `masks` are screen rectangles blacked out of what the buddy sees
    (its own widget, which stays visible in recordings)."""

    def __init__(self, window: GameWindow, masks: list[tuple[int, int, int, int]] | None = None):
        import mss

        self.window, self.masks = window, list(masks or [])
        self._grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    def frame(self) -> np.ndarray:
        x0, y0, x1, y1 = self.window.client_box()
        shot = self._grabber.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0})
        image = np.asarray(shot)[:, :, :3].copy()
        for mx0, my0, mx1, my1 in self.masks:
            image[max(my0 - y0, 0):max(my1 - y0, 0), max(mx0 - x0, 0):max(mx1 - x0, 0)] = 0
        return image
