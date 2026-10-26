"""Window styles for an overlay that must never disturb the game underneath (rules 1, 2, 4 of the design):

  - an ordinary top-level window: NO injection into the game, no hooks of its graphics, memory or input;
  - non-activating and a tool window: opening it never takes keyboard focus from the game, and it has no taskbar button;
  - topmost, so Windows draws it over a windowed or borderless game;
  - click-through when pinned, so it never steals a click;
  - excluded from screen capture, so the buddy never sees (and reasons about) its own panel.

The Windows calls go through an injectable `user32`, so every decision here is tested with a fake one."""
from __future__ import annotations

import ctypes
from dataclasses import dataclass

GWL_EXSTYLE = -20
WS_EX_TOPMOST = 0x00000008
WS_EX_TRANSPARENT = 0x00000020  # click-through
WS_EX_TOOLWINDOW = 0x00000080  # no taskbar button
WS_EX_LAYERED = 0x00080000  # needed for per-pixel alpha and for click-through
WS_EX_NOACTIVATE = 0x08000000  # never takes focus
WDA_NONE = 0x00
WDA_EXCLUDEFROMCAPTURE = 0x11  # Windows 10 build 2004 and later
HWND_TOPMOST = -1
SWP_NOSIZE, SWP_NOMOVE, SWP_NOACTIVATE, SWP_FRAMECHANGED = 0x0001, 0x0002, 0x0010, 0x0020


def overlay_exstyle(current: int, click_through: bool) -> int:
    """The extended style bits for an overlay, keeping whatever else the window already had."""
    style = current | WS_EX_NOACTIVATE | WS_EX_TOOLWINDOW | WS_EX_TOPMOST | WS_EX_LAYERED
    return style | WS_EX_TRANSPARENT if click_through else style & ~WS_EX_TRANSPARENT


@dataclass
class Applied:
    exstyle: int
    excluded_from_capture: bool
    click_through: bool


def apply_overlay_style(hwnd: int, click_through: bool = False, show_in_recordings: bool = False, user32=None) -> Applied:
    """Make `hwnd` an overlay. With show_in_recordings the capture exclusion is lifted (the buddy's frames then mask the panel's
    rectangle instead, see mask_rectangle). Raises OSError when Windows refuses the capture setting, so a panel the buddy can
    still see is never silently accepted."""
    api = user32 or ctypes.windll.user32
    current = api.GetWindowLongPtrW(hwnd, GWL_EXSTYLE) & 0xFFFFFFFF
    style = overlay_exstyle(current, click_through)
    api.SetWindowLongPtrW(hwnd, GWL_EXSTYLE, style)
    api.SetWindowPos(hwnd, HWND_TOPMOST, 0, 0, 0, 0, SWP_NOSIZE | SWP_NOMOVE | SWP_NOACTIVATE | SWP_FRAMECHANGED)
    affinity = WDA_NONE if show_in_recordings else WDA_EXCLUDEFROMCAPTURE
    if not api.SetWindowDisplayAffinity(hwnd, affinity):
        raise OSError("Windows refused to set the capture exclusion for the overlay")
    return Applied(style, not show_in_recordings, click_through)


def mask_rectangle(image, rect: tuple[int, int, int, int], window_origin: tuple[int, int] = (0, 0)):
    """A copy of `image` with the overlay's rectangle (screen coordinates: left, top, right, bottom) blacked out, for recordings
    where the panel is visible: the buddy must not see its own panel even then."""
    from PIL import ImageDraw

    left, top, right, bottom = rect
    copy = image.convert("RGB").copy()
    ImageDraw.Draw(copy).rectangle((left - window_origin[0], top - window_origin[1], right - window_origin[0] - 1,
                                    bottom - window_origin[1] - 1), fill=(0, 0, 0))
    return copy


QUNS_BUSY, QUNS_RUNNING_D3D_FULL_SCREEN, QUNS_PRESENTATION_MODE = 2, 3, 4  # shell32 SHQueryUserNotificationState answers


def full_screen_state(shell32=None) -> str:
    """What Windows itself says about a full-screen app: "exclusive" (a Direct3D exclusive full screen: no overlay can be drawn),
    "borderless" (a full-screen window Windows still composes: an overlay works), "presentation", "none", or "unknown" when the
    question fails. This asks the shell; it does not guess from window sizes (a borderless window and an exclusive one look alike)."""
    api = shell32 or ctypes.windll.shell32
    state = ctypes.c_int(0)
    if api.SHQueryUserNotificationState(ctypes.byref(state)) != 0:  # S_OK is 0
        return "unknown"
    return {QUNS_RUNNING_D3D_FULL_SCREEN: "exclusive", QUNS_BUSY: "borderless", QUNS_PRESENTATION_MODE: "presentation"}.get(state.value, "none")
