"""Receive the summon key without a keyboard hook: Windows posts WM_HOTKEY to the thread that registered the key, so that thread
runs a tiny message loop and calls us back. Everything goes through an injectable `user32`, so the loop is tested without a window.

The thread is a daemon and stops cleanly: stop() posts WM_QUIT to it, the loop ends, and the key is unregistered by the same thread
(Windows only lets the registering thread do that)."""
from __future__ import annotations

import ctypes
import threading
from ctypes import wintypes
from typing import Callable

from playfellow_coop.overlay.hotkey import Hotkey

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012


class HotkeyPump:
    def __init__(self, hotkey: Hotkey, on_press: Callable[[], None], user32=None, kernel32=None):
        self._hotkey, self._on_press = hotkey, on_press
        self._api = user32 or ctypes.windll.user32
        self._kernel = kernel32 or ctypes.windll.kernel32
        self._ready = threading.Event()
        self._thread: threading.Thread | None = None
        self._thread_id = 0
        self.error: Exception | None = None

    def start(self, timeout: float = 5.0) -> None:
        """Start the thread and wait until the key is registered; raises what the registration raised (for example a taken key)."""
        self._thread = threading.Thread(target=self._run, daemon=True)
        self._thread.start()
        if not self._ready.wait(timeout):
            raise RuntimeError("the summon key was not registered in time")
        if self.error is not None:
            raise self.error

    def stop(self, timeout: float = 5.0) -> None:
        if self._thread is not None and self._thread.is_alive():
            self._api.PostThreadMessageW(self._thread_id, WM_QUIT, 0, 0)
            self._thread.join(timeout)

    def _run(self) -> None:
        self._thread_id = self._kernel.GetCurrentThreadId()
        try:
            self._hotkey._api = self._api  # the key is registered on THIS thread, with the same api object
            self._hotkey.register(None)
        except Exception as error:  # a taken key, for example: told to start(), which raises it
            self.error = error
            self._ready.set()
            return
        self._ready.set()
        message = wintypes.MSG()
        try:
            while self._api.GetMessageW(ctypes.byref(message), None, 0, 0) > 0:  # 0 means WM_QUIT; -1 means an error
                if message.message == WM_HOTKEY:
                    try:
                        self._on_press()
                    except Exception:  # a failing callback must never end the loop or the thread
                        pass
        finally:
            self._hotkey.unregister(None)
