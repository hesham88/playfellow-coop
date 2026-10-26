"""The summon-key message loop, with a fake user32 and kernel32 (no real hotkey is registered, no window exists)."""
from __future__ import annotations

import threading

import pytest

from playfellow_coop.overlay import hotkey, pump
from tests.test_overlay_windows import FakeUser32


class PumpUser32(FakeUser32):
    """A user32 whose GetMessageW hands out scripted messages, then WM_QUIT (return 0)."""

    def __init__(self, messages, **kw):
        super().__init__(**kw)
        self._messages = list(messages)
        self.thread_messages = []
        self.registered_on = None
        self.unregistered_on = None
        self.gate = threading.Event()

    def RegisterHotKey(self, hwnd, ident, mods, vk):  # noqa: N802
        self.registered_on = threading.get_ident()
        return super().RegisterHotKey(hwnd, ident, mods, vk)

    def UnregisterHotKey(self, hwnd, ident):  # noqa: N802
        self.unregistered_on = threading.get_ident()
        return super().UnregisterHotKey(hwnd, ident)

    def GetMessageW(self, pointer, hwnd, low, high):  # noqa: N802
        if not self._messages:
            self.gate.wait(5)  # idle until stop() posts WM_QUIT
            return 0
        kind = self._messages.pop(0)
        pump_message = pointer._obj
        pump_message.message = kind
        return 1

    def PostThreadMessageW(self, thread_id, message, a, b):  # noqa: N802
        self.thread_messages.append((thread_id, message))
        self.gate.set()
        return 1


class FakeKernel:
    def GetCurrentThreadId(self):  # noqa: N802
        return 4242


def make(api, calls, card=None):
    key = hotkey.Hotkey("ctrl+alt+p", card=card, user32=api)
    return pump.HotkeyPump(key, lambda: calls.append(1), user32=api, kernel32=FakeKernel())


def test_each_hotkey_message_calls_back_and_other_messages_do_not():
    api, calls = PumpUser32([pump.WM_HOTKEY, 0x0100, pump.WM_HOTKEY, pump.WM_HOTKEY]), []
    p = make(api, calls)
    p.start()
    p.stop()
    assert len(calls) == 3


def test_the_key_is_registered_and_unregistered_on_the_pump_thread_and_stop_posts_wm_quit():
    api, calls = PumpUser32([]), []
    p = make(api, calls)
    p.start()
    registered_on = api.registered_on
    p.stop()
    assert registered_on != threading.get_ident() and api.unregistered_on == registered_on
    assert api.thread_messages == [(4242, pump.WM_QUIT)] and not p._thread.is_alive()


def test_a_taken_key_is_raised_by_start_and_the_thread_ends():
    api = PumpUser32([], refuse_hotkey=True)
    p = make(api, [])
    with pytest.raises(hotkey.HotkeyError) as caught:
        p.start()
    assert "another program" in str(caught.value) and not p._thread.is_alive()


def test_a_callback_that_fails_does_not_end_the_loop():
    api, calls = PumpUser32([pump.WM_HOTKEY, pump.WM_HOTKEY]), []

    def flaky():
        calls.append(1)
        if len(calls) == 1:
            raise RuntimeError("view not ready")

    key = hotkey.Hotkey("ctrl+alt+p", user32=api)
    p = pump.HotkeyPump(key, flaky, user32=api, kernel32=FakeKernel())
    p.start()
    p.stop()
    assert len(calls) == 2


def test_stopping_twice_or_before_starting_is_harmless():
    api = PumpUser32([])
    p = make(api, [])
    p.stop()
    p.start()
    p.stop()
    p.stop()
    assert len(api.thread_messages) == 1
