"""The in-game widget: a slim bar docked at the top centre that slides open and closed, see-through by default and never invisible,
with the talk button on the bar itself. All of it is in the model and pure functions, tested without a window."""
from __future__ import annotations

from playfellow_coop.overlay.panel import DEFAULT_OPACITY, OPACITY_RANGE, PanelModel, dock_rect, slide_heights
from playfellow_coop.voice import CommandQueue


def test_the_widget_starts_collapsed_and_see_through_but_never_invisible():
    model = PanelModel(CommandQueue())
    assert model.collapsed is True and model.opacity == DEFAULT_OPACITY < 0.7
    assert model.set_opacity(0.0) == OPACITY_RANGE[0] > 0  # the slider's lowest point is still visible
    assert model.set_opacity(5) == 1.0


def test_expand_and_collapse_toggle_and_tell_the_view():
    model = PanelModel(CommandQueue())
    seen = []
    model.subscribe(lambda: seen.append(model.collapsed))
    assert model.toggle_collapsed() is False and model.toggle_collapsed() is True
    assert seen == [False, True]


def test_the_slide_eases_out_and_ends_exactly_on_the_target_both_ways():
    down = slide_heights(44, 360, ms=220, fps=60)
    up = slide_heights(360, 44, ms=220, fps=60)
    assert down[-1] == 360 and up[-1] == 44 and 10 <= len(down) <= 16
    steps = [b - a for a, b in zip([44] + down, down)]
    assert all(s >= 0 for s in steps) and steps[0] > steps[-1]  # fast first, gentle at the end
    assert slide_heights(44, 44, ms=220, fps=60) == [44]


def test_the_widget_is_docked_at_the_top_centre_of_the_screen():
    x, y, w, h = dock_rect(screen_left=0, screen_top=0, screen_width=1920, width=560, height=44)
    assert (x, y, w, h) == (680, 6, 560, 44)
    x, _, _, _ = dock_rect(screen_left=1920, screen_top=0, screen_width=2560, width=560, height=44)  # a second monitor
    assert x == 1920 + 1000
