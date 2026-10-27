"""The overlay's toolkit-free model and the spike's measurement functions, with no window anywhere."""
from __future__ import annotations

import pytest
from PIL import Image, ImageDraw

from playfellow_coop.overlay.panel import CHIPS, MAX_LINES, OPACITY_RANGE, PanelModel
from playfellow_coop.overlay.spike import capture_check, measure_focus_loss, panel_pixels_in_capture
from playfellow_coop.voice import CommandQueue


def model(language="english"):
    queue = CommandQueue()
    return PanelModel(queue, language=lambda: language), queue


def test_the_summon_key_opens_and_closes_with_the_same_press_and_views_are_told():
    panel, _ = model()
    seen = []
    panel.subscribe(lambda: seen.append(panel.visible))
    assert panel.toggle() is True and panel.toggle() is False
    assert seen == [True, False]


def test_click_through_is_on_only_for_the_pinned_pill():
    panel, _ = model()
    assert panel.click_through is True  # hidden: only the small pill is there, and it never steals a click
    panel.show()
    assert panel.click_through is False  # open: its buttons must be usable
    panel.hide()
    assert panel.click_through is True


def test_show_and_hide_do_nothing_twice():
    panel, _ = model()
    seen = []
    panel.subscribe(lambda: seen.append(1))
    panel.show()
    panel.show()
    panel.hide()
    panel.hide()
    assert len(seen) == 2


def test_the_pill_says_the_state_in_both_languages_and_the_arabic_panel_mirrors():
    english, _ = model()
    arabic, _ = model("arabic")
    assert english.pill_text == "Fello · ready" and english.right_to_left is False
    assert arabic.pill_text == "Fello · جاهز" and arabic.right_to_left is True
    english.set_state("player")
    assert english.pill_text == "Fello · you have the controls"
    with pytest.raises(ValueError):
        english.set_state("flying")


def test_the_chips_are_the_quick_commands_in_the_players_language_and_go_to_the_queue():
    panel, queue = model()
    assert panel.chips == [e for e, _ in CHIPS]
    assert panel.press_chip(0) is True
    assert queue.drain() == ["Collect the coins"] and panel.lines[-1].who == "player"
    arabic, aqueue = model("arabic")
    assert arabic.chips == [a for _, a in CHIPS]
    arabic.press_chip(2)
    assert aqueue.drain() == ["خذها"]


def test_the_you_take_it_chip_is_a_control_word_so_it_works_without_the_ai():
    from playfellow_coop.control_words import BUDDY_TAKES, control_action

    panel, queue = model()
    panel.press_chip(2)
    assert queue.take_controls() == [BUDDY_TAKES] and control_action("You take it") == BUDDY_TAKES


def test_typed_text_becomes_a_command_blank_text_does_not_and_the_partial_clears():
    panel, queue = model()
    panel.partial("  grab the co ")
    assert panel.heard_partial == "grab the co"
    assert panel.submit("grab the coins") is True and panel.heard_partial == ""
    assert panel.submit("   ") is False
    assert queue.drain() == ["grab the coins"]


def test_the_chat_keeps_only_the_last_few_lines_and_skips_empty_ones():
    panel, _ = model()
    for number in range(MAX_LINES + 3):
        panel.buddy_says(f"line {number}")
    panel.buddy_says("   ")
    assert len(panel.lines) == MAX_LINES and panel.lines[-1].text == f"line {MAX_LINES + 2}"


def test_opacity_never_goes_fully_invisible_or_above_opaque():
    panel, _ = model()
    assert panel.set_opacity(0) == OPACITY_RANGE[0] and panel.set_opacity(5) == OPACITY_RANGE[1] and panel.set_opacity(0.5) == 0.5


def test_the_model_never_imports_a_toolkit():
    import inspect

    from playfellow_coop.overlay import panel as module

    source = inspect.getsource(module)
    for toolkit in ("tkinter", "PySide6", "PyQt", "customtkinter"):
        assert toolkit not in source


# ---- the spike's numbers ----------------------------------------------------------------------------------------
def test_no_focus_loss_is_counted_when_the_foreground_stays_the_games():
    state = {"open": False}

    def toggle():
        state["open"] = not state["open"]

    result = measure_focus_loss(50, toggle, foreground=lambda: 1234)
    assert (result.opens, result.focus_losses, result.foreground_before) == (50, 0, 1234)


def test_every_focus_loss_is_counted_and_the_start_window_is_the_reference():
    handles = iter([100] + [100, 7, 100, 7, 7])  # the foreground at the start, then after each of five toggles
    result = measure_focus_loss(5, lambda: None, foreground=lambda: next(handles))
    assert result.focus_losses == 3 and result.foreground_before == 100


def test_the_settle_hook_runs_between_toggles():
    calls = []
    measure_focus_loss(3, lambda: calls.append("t"), foreground=lambda: 1, settle=lambda: calls.append("s"))
    assert calls == ["t", "s"] * 3


def _frame(panel_drawn: bool):
    image = Image.new("RGB", (200, 120), (30, 90, 40))
    ImageDraw.Draw(image).rectangle((10, 10, 40, 40), fill=(200, 200, 0))  # the game's own content
    if panel_drawn:
        ImageDraw.Draw(image).rectangle((100, 20, 180, 100), fill=(255, 255, 255))
    return image


def test_zero_panel_pixels_when_the_panel_is_excluded_from_the_capture():
    assert panel_pixels_in_capture(_frame(False), _frame(False), (100, 20, 181, 101)) == 0


def test_the_pixels_of_a_visible_panel_are_counted():
    found = panel_pixels_in_capture(_frame(True), _frame(False), (100, 20, 181, 101))
    assert found == 81 * 81 or found > 6000  # the whole rectangle changed


def test_changes_outside_the_panels_rectangle_do_not_count():
    moving = _frame(False)
    ImageDraw.Draw(moving).rectangle((10, 10, 60, 60), fill=(0, 0, 255))  # the game moved elsewhere
    assert panel_pixels_in_capture(moving, _frame(False), (100, 20, 181, 101)) == 0


def test_the_capture_check_opens_closes_and_grabs_in_order_and_leaves_the_panel_closed():
    log = []
    frames = iter([_frame(False), _frame(False)])
    count = capture_check(lambda: (log.append("grab"), next(frames))[1], lambda: log.append("open"), lambda: log.append("close"),
                          (100, 20, 181, 101))
    assert count == 0 and log == ["close", "grab", "open", "grab", "close"]


# ---- gaps found by mutating the overlay ---------------------------------------------------------------------------
def test_setting_the_state_it_already_has_tells_no_view():
    panel, _ = model()
    seen = []
    panel.subscribe(lambda: seen.append(1))
    panel.set_state("ready")
    assert seen == []
    panel.set_state("listening")
    assert seen == [1]


def test_a_long_typed_command_is_cut_in_the_chat_line_but_not_in_the_queue():
    panel, queue = model()
    assert panel.submit("x" * 500) is True
    assert len(panel.lines[-1].text) == 300


def test_each_other_window_that_took_the_front_is_listed_once():
    handles = iter([100, 7, 7, 8, 7])
    result = measure_focus_loss(4, lambda: None, foreground=lambda: next(handles))
    assert result.others == (7, 8) and result.losses_by == {7: 3, 8: 1}


def test_a_change_exactly_at_the_tolerance_does_not_count_and_one_above_does():
    reference = Image.new("RGB", (10, 10), (100, 100, 100))
    at_tolerance = Image.new("RGB", (10, 10), (108, 108, 108))
    above = Image.new("RGB", (10, 10), (109, 109, 109))
    assert panel_pixels_in_capture(at_tolerance, reference, (0, 0, 10, 10), tolerance=8) == 0
    assert panel_pixels_in_capture(above, reference, (0, 0, 10, 10), tolerance=8) == 100


def test_the_reference_is_compared_pixel_by_pixel_not_by_its_corner():
    pattern = Image.new("RGB", (40, 40), (0, 0, 0))
    ImageDraw.Draw(pattern).rectangle((20, 0, 39, 39), fill=(255, 0, 0))  # a game scene that is not one flat colour
    assert panel_pixels_in_capture(pattern.copy(), pattern, (0, 0, 40, 40)) == 0
