"""The overlay's Windows-level rules, decided and tested with a fake user32 (no window is created and nothing is drawn)."""
from __future__ import annotations

import ctypes

import pytest
from PIL import Image

from playfellow_coop.overlay import hotkey, winstyle
from tests.test_session_and_handover import CARD, MOVE


class FakeUser32:
    def __init__(self, exstyle=0, refuse_affinity=False, refuse_hotkey=False):
        self.exstyle, self.refuse_affinity, self.refuse_hotkey = exstyle, refuse_affinity, refuse_hotkey
        self.calls, self.affinity = [], None

    def GetWindowLongPtrW(self, hwnd, index):  # noqa: N802
        self.calls.append(("get", index))
        return self.exstyle

    def SetWindowLongPtrW(self, hwnd, index, value):  # noqa: N802
        self.calls.append(("set", index, value))
        self.exstyle = value

    def SetWindowPos(self, *args):  # noqa: N802
        self.calls.append(("pos", args))
        return 1

    def SetWindowDisplayAffinity(self, hwnd, value):  # noqa: N802
        self.affinity = value
        return 0 if self.refuse_affinity else 1

    def RegisterHotKey(self, hwnd, ident, mods, vk):  # noqa: N802
        self.calls.append(("register", mods, vk))
        return 0 if self.refuse_hotkey else 1

    def UnregisterHotKey(self, hwnd, ident):  # noqa: N802
        self.calls.append(("unregister",))
        return 1


def test_the_overlay_never_takes_focus_has_no_taskbar_button_and_stays_on_top_and_keeps_other_bits():
    style = winstyle.overlay_exstyle(0x00000200, click_through=False)
    for bit in (winstyle.WS_EX_NOACTIVATE, winstyle.WS_EX_TOOLWINDOW, winstyle.WS_EX_TOPMOST, winstyle.WS_EX_LAYERED, 0x200):
        assert style & bit
    assert not style & winstyle.WS_EX_TRANSPARENT


def test_click_through_is_a_switch_that_works_both_ways():
    on = winstyle.overlay_exstyle(0, click_through=True)
    assert on & winstyle.WS_EX_TRANSPARENT
    assert not winstyle.overlay_exstyle(on, click_through=False) & winstyle.WS_EX_TRANSPARENT


def test_applying_the_style_sets_it_excludes_the_panel_from_capture_and_does_not_activate():
    api = FakeUser32(exstyle=0x100)
    applied = winstyle.apply_overlay_style(1234, click_through=True, user32=api)
    assert api.exstyle == applied.exstyle and applied.exstyle & winstyle.WS_EX_NOACTIVATE and applied.exstyle & 0x100
    assert api.affinity == winstyle.WDA_EXCLUDEFROMCAPTURE and applied.excluded_from_capture and applied.click_through
    pos = next(c for c in api.calls if c[0] == "pos")[1]
    assert pos[1] == winstyle.HWND_TOPMOST and pos[6] & winstyle.SWP_NOACTIVATE  # placed on top without activating it


def test_show_in_recordings_lifts_the_exclusion_so_the_panel_can_be_filmed():
    api = FakeUser32()
    applied = winstyle.apply_overlay_style(1, show_in_recordings=True, user32=api)
    assert api.affinity == winstyle.WDA_NONE and not applied.excluded_from_capture


def test_if_windows_refuses_the_capture_exclusion_it_is_an_error_not_a_silent_pass():
    with pytest.raises(OSError):
        winstyle.apply_overlay_style(1, user32=FakeUser32(refuse_affinity=True))


def test_the_panels_rectangle_is_blacked_out_of_the_frame_the_buddy_sees():
    frame = Image.new("RGB", (100, 80), (200, 200, 200))
    masked = winstyle.mask_rectangle(frame, (10, 20, 40, 50))
    assert masked.getpixel((15, 25)) == (0, 0, 0) and masked.getpixel((39, 49)) == (0, 0, 0)
    assert masked.getpixel((9, 25)) == (200, 200, 200) and masked.getpixel((40, 25)) == (200, 200, 200)
    assert frame.getpixel((15, 25)) == (200, 200, 200)  # the original is untouched


def test_the_mask_follows_the_game_windows_origin():
    frame = Image.new("RGB", (100, 80), (200, 200, 200))
    masked = winstyle.mask_rectangle(frame, (110, 120, 140, 150), window_origin=(100, 100))
    assert masked.getpixel((15, 25)) == (0, 0, 0)


class FakeShell:
    def __init__(self, value, status=0):
        self.value, self.status = value, status

    def SHQueryUserNotificationState(self, pointer):  # noqa: N802
        ctypes.cast(pointer, ctypes.POINTER(ctypes.c_int))[0] = self.value
        return self.status


@pytest.mark.parametrize("value,word", [(3, "exclusive"), (2, "borderless"), (4, "presentation"), (5, "none"), (1, "none")])
def test_the_full_screen_state_is_what_windows_says(value, word):
    assert winstyle.full_screen_state(FakeShell(value)) == word


def test_a_failed_question_is_unknown_never_a_guess():
    assert winstyle.full_screen_state(FakeShell(3, status=-1)) == "unknown"


# ---- the summon key ------------------------------------------------------------------------------------------------
def test_the_default_summon_key_is_ctrl_alt_p():
    bits, code, key = hotkey.parse(hotkey.DEFAULT)
    assert bits == hotkey.MOD_CONTROL | hotkey.MOD_ALT and code == ord("P") and key == "p"


@pytest.mark.parametrize("text", ["", "p", "ctrl+", "hyper+p", "ctrl+alt+ß", "ctrl+f99"])
def test_a_bad_key_is_refused_in_plain_words(text):
    with pytest.raises(hotkey.HotkeyError):
        hotkey.parse(text)


def test_a_key_the_game_uses_is_refused():
    with pytest.raises(hotkey.HotkeyError) as caught:
        hotkey.Hotkey("ctrl+up", card=CARD, user32=FakeUser32())
    assert "UP" in str(caught.value) and "uses" in str(caught.value) and MOVE is not None


@pytest.mark.parametrize("name", ["f9", "f12"])
def test_the_hand_over_and_stop_keys_cannot_be_the_summon_key(name):
    with pytest.raises(hotkey.HotkeyError):
        hotkey.Hotkey(f"ctrl+{name}", card=CARD, user32=FakeUser32())


def test_registering_uses_the_windows_hotkey_call_and_no_repeat_and_unregisters_cleanly():
    api = FakeUser32()
    key = hotkey.Hotkey("ctrl+alt+p", card=CARD, user32=api)
    key.register()
    registered = next(c for c in api.calls if c[0] == "register")
    assert registered[1] & hotkey.MOD_NOREPEAT and registered[2] == ord("P") and key.registered
    key.unregister()
    key.unregister()  # twice is harmless
    assert [c[0] for c in api.calls].count("unregister") == 1 and not key.registered


def test_a_key_combination_another_program_holds_is_a_plain_error():
    with pytest.raises(hotkey.HotkeyError) as caught:
        hotkey.Hotkey("ctrl+alt+p", user32=FakeUser32(refuse_hotkey=True)).register()
    assert "another program" in str(caught.value)


def test_the_overlay_package_has_no_hook_or_injection_calls():
    import inspect

    for module in (winstyle, hotkey):
        source = inspect.getsource(module)
        for banned in ("SetWindowsHookEx", "WriteProcessMemory", "CreateRemoteThread", "LoadLibrary", "VirtualAllocEx"):
            assert banned not in source
