"""The in-game widget: a slim bar docked at the top centre that slides open and closed, see-through by default and never invisible,
with the talk button on the bar itself. All of it is in the model and pure functions, tested without a window."""
from __future__ import annotations

from playfellow_coop.overlay.panel import DEFAULT_OPACITY, OPACITY_RANGE, PanelModel, dock_rect, slide_heights
from playfellow_coop.voice import CommandQueue


def test_the_widget_starts_collapsed_and_see_through_but_never_invisible():
    model = PanelModel(CommandQueue())
    assert model.collapsed is True and model.opacity == DEFAULT_OPACITY == 0.90
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


def test_the_see_through_key_steps_through_levels_and_wraps_but_never_reaches_invisible():
    model = PanelModel(CommandQueue())
    seen = [model.step_opacity() for _ in range(5)]
    assert all(v >= OPACITY_RANGE[0] > 0 for v in seen)
    assert seen == [1.0, OPACITY_RANGE[0], 0.55, 0.8, 1.0]  # from the default 0.9: up to fully solid, then back to the floor


def test_the_bar_writes_every_key_so_a_full_screen_game_without_a_mouse_is_still_usable():
    """Owner, 2 Nov: in full-screen games the mouse is often gone, so the shortcuts must be clear and visible."""
    model = PanelModel(CommandQueue(), language=lambda: "english")
    model.set_keys(talk="f8", panel="ctrl+alt+p", see_through="ctrl+alt+o")
    hint = model.shortcut_hint
    for part in ("F8 talk", "Ctrl+Alt+P", "Ctrl+Alt+O", "F9", "F12"):
        assert part in hint
    assert "F8" not in PanelModel(CommandQueue(), language=lambda: "english").shortcut_hint  # no talk key set: none is promised
    arabic = PanelModel(CommandQueue(), language=lambda: "arabic")
    arabic.set_keys(talk="f8", panel="ctrl+alt+p", see_through="ctrl+alt+o")
    assert "F8" in arabic.shortcut_hint and "Ctrl+Alt+O" in arabic.shortcut_hint


def test_the_chat_keeps_only_the_last_few_short_lines_so_the_panel_cannot_outgrow_its_height():
    """Owner run, 2 Nov: a long spoken request made the panel ask for 525 to 697 px and Windows refused the size."""
    from playfellow_coop.overlay.panel import CHAT_CHARS, CHAT_LINES

    model = PanelModel(CommandQueue())
    for n in range(30):
        model.buddy_says(f"line {n} " + "word " * 80)
    shown = model.shown_lines()
    assert len(shown) == CHAT_LINES and all(len(line.text) <= CHAT_CHARS for line in shown) and shown[-1].text.startswith("line 29")
