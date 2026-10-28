"""The engine's hands, pressing hardware scan codes instead of virtual-key messages.

The engine's `Hands` talks to a backend that looks like `pydirectinput` (keyDown, keyUp, click, moveRel, moveTo, mouseDown, mouseUp, position, FAILSAFE). `DirectInputCompat` is that backend
on top of `winio.ScanBackend`: the same engine, the same controls cards and the same safety rules, but every key is a scan code with the extended flag where needed and the mouse is
absolute or relative the way games expect (research R1 section 2.1 and 3.6). The corner fail-safe is kept: with FAILSAFE on, a cursor in the top-left corner raises the same exception the
engine already turns into a stop.
"""
from __future__ import annotations

import ctypes
import sys
from ctypes import wintypes
from typing import Callable

from playfellow_coop.universal.winio import (MOUSEEVENTF_ABSOLUTE, MOUSEEVENTF_LEFTDOWN, MOUSEEVENTF_LEFTUP, MOUSEEVENTF_MOVE, MOUSEEVENTF_RIGHTDOWN, MOUSEEVENTF_RIGHTUP, ScanBackend,
                                             Win32Api, mouse_input, to_absolute)


class FailSafeException(Exception):
    """The mouse reached the top-left corner. (The name is what the engine's hands look for.)"""


class DirectInputCompat:
    def __init__(self, send: Callable | None = None, cursor: Callable[[], tuple[int, int]] | None = None, screen: tuple[int, int] | None = None):
        if send is None:
            api = Win32Api()
            send = api.send
            screen = screen or api.screen_size()

            def cursor() -> tuple[int, int]:  # noqa: F811
                point = wintypes.POINT()
                api.user32.GetCursorPos(ctypes.byref(point))
                return point.x, point.y
        self._send = send
        self._scan = ScanBackend(send)
        self._cursor = cursor or (lambda: (500, 500))
        self.screen = screen or (1920, 1080)
        self.FAILSAFE = True
        self.PAUSE = 0.0

    def _check(self) -> None:
        if self.FAILSAFE and self._cursor() == (0, 0):
            raise FailSafeException("the mouse is in the top-left corner")

    # ---- the pydirectinput surface the engine uses ---------------------------------------------------------------------------------
    def keyDown(self, key: str) -> None:  # noqa: N802
        self._check()
        self._scan.key_down(key)

    def keyUp(self, key: str) -> None:  # noqa: N802
        self._scan.key_up(key)  # a release is never refused: held keys must always be able to let go

    def position(self) -> tuple[int, int]:
        return self._cursor()

    def moveTo(self, x: int, y: int) -> None:  # noqa: N802
        self._check()
        self._scan.mouse_absolute(int(x), int(y), *self.screen)

    def moveRel(self, dx: int, dy: int, relative: bool = True) -> None:  # noqa: N802
        self._check()
        self._scan.mouse_move(int(dx), int(dy))

    def mouseDown(self, button: str = "left") -> None:  # noqa: N802
        self._check()
        self._send([mouse_input(MOUSEEVENTF_RIGHTDOWN if button == "right" else MOUSEEVENTF_LEFTDOWN)])

    def mouseUp(self, button: str = "left") -> None:  # noqa: N802
        self._send([mouse_input(MOUSEEVENTF_RIGHTUP if button == "right" else MOUSEEVENTF_LEFTUP)])

    def click(self, x: int | None = None, y: int | None = None, button: str = "left") -> None:
        self._check()
        if x is not None and y is not None:
            self._scan.mouse_absolute(int(x), int(y), *self.screen)
        self._scan.click(right=button == "right")


def available() -> bool:
    return sys.platform == "win32"


__all__ = ["DirectInputCompat", "FailSafeException", "MOUSEEVENTF_ABSOLUTE", "MOUSEEVENTF_MOVE", "to_absolute", "available"]
