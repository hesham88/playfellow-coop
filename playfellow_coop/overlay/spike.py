"""The H7 spike's measurements, as plain functions, so the numbers come from code and the logic is tested with fakes.

Four checks (from the design):  (a) opening and closing the panel never takes keyboard focus from the game;  (b) the panel is
absent from the buddy's own screen capture;  (c) it is click-through when pinned;  (d) F12 still stops the engine with the panel open
or closed. (a) and (b) are measured here; (c) is a window-style fact checked in winstyle; (d) is the engine's own listener.
Nothing here counts as "working" until the owner's live check has run it on a real game window."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Callable

from PIL import Image, ImageChops


@dataclass
class FocusResult:
    opens: int
    focus_losses: int
    foreground_before: int


def measure_focus_loss(opens: int, toggle: Callable[[], None], foreground: Callable[[], int], settle: Callable[[], None] = lambda: None) -> FocusResult:
    """Toggle the panel `opens` times (open and close each count as one) and count how often the foreground window changed from
    the one it started with. `foreground` returns a window handle; `settle` lets Windows finish between toggles."""
    before = foreground()
    losses = 0
    for _ in range(opens):
        toggle()
        settle()
        if foreground() != before:
            losses += 1
    return FocusResult(opens, losses, before)


def panel_pixels_in_capture(frame_with_panel: Image.Image, reference_frame: Image.Image, rect: tuple[int, int, int, int],
                            tolerance: int = 8) -> int:
    """How many pixels inside the panel's rectangle differ from a reference frame taken with the panel closed. 0 means the panel
    is invisible to this capture. The game keeps moving, so the caller should take the reference from a still moment."""
    left, top, right, bottom = rect
    a = frame_with_panel.convert("RGB").crop(rect)
    b = reference_frame.convert("RGB").crop(rect)
    diff = ImageChops.difference(a, b).convert("L")
    return sum(1 for value in diff.getdata() if value > tolerance)


def capture_check(grab: Callable[[], Image.Image], open_panel: Callable[[], None], close_panel: Callable[[], None],
                  rect: tuple[int, int, int, int], settle: Callable[[], None] = lambda: None) -> int:
    """(b) end to end: a reference frame with the panel closed, a frame with it open, and the pixel count that changed inside its rectangle."""
    close_panel()
    settle()
    reference = grab()
    open_panel()
    settle()
    with_panel = grab()
    close_panel()
    return panel_pixels_in_capture(with_panel, reference, rect)
