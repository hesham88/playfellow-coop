"""The in-game widget, drawn: a slim bar at the top centre with the mic and the open arrow, a panel that slides down and up, an
opacity slider that never reaches invisible, and "stay on top" re-asserted so it remains over full-screen games. Built offscreen."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtWidgets import QApplication  # noqa: E402

from playfellow_coop.overlay.panel import BAR_HEIGHT, OPACITY_RANGE, PANEL_HEIGHT, PanelModel  # noqa: E402
from playfellow_coop.overlay.qt_view import QtOverlay  # noqa: E402
from playfellow_coop.voice import CommandQueue  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(**kw):
    model = PanelModel(CommandQueue(), language=lambda: "english")
    talks = []
    view = QtOverlay(model, on_talk_down=lambda: talks.append("down"), on_talk_up=lambda: talks.append("up"), **kw)
    return view, model, talks


def test_the_bar_carries_the_mic_and_the_open_arrow_and_is_docked_at_the_top_centre(app):
    view, model, talks = build()
    assert model.collapsed and view.window.height() == BAR_HEIGHT
    geo = view.window.screen().availableGeometry()
    assert abs(view.window.x() + view.window.width() // 2 - (geo.left() + geo.width() // 2)) <= 1
    assert view.window.y() - geo.top() < 20
    assert not view.bar_talk.isHidden() and not view.toggle_button.isHidden() and view.toggle_button.text() == "▾"
    view.bar_talk.pressed.emit()
    view.bar_talk.released.emit()
    assert talks == ["down", "up"]  # voice works from the bar, without opening anything


def test_opening_slides_down_frame_by_frame_and_closing_slides_back_up(app):
    view, model, _ = build(animate=False)
    view.toggle_button.click()
    assert not model.collapsed and view.slide_plan[-1] == PANEL_HEIGHT and len(view.slide_plan) > 5
    view.finish_slide()
    assert view.window.height() == PANEL_HEIGHT
    view.toggle_button.click()
    assert model.collapsed and view.slide_plan[-1] == BAR_HEIGHT
    view.finish_slide()
    assert view.window.height() == BAR_HEIGHT


def test_the_opacity_slider_cannot_make_the_widget_invisible(app):
    view, model, _ = build()
    view.opacity_slider.setValue(view.opacity_slider.minimum())
    assert model.opacity == OPACITY_RANGE[0] > 0 and view.opacity_slider.minimum() == round(OPACITY_RANGE[0] * 100)
    assert abs(view.window.windowOpacity() - OPACITY_RANGE[0]) < 0.02


def test_stay_on_top_is_re_asserted_on_a_timer(app):
    view, _, _ = build()
    assert view.top_timer.interval() <= 500 and view.top_timer.isActive() is False  # starts with start()
    calls = []
    view._reassert = lambda: calls.append(1)
    view.top_timer.timeout.disconnect()
    view.top_timer.timeout.connect(view._reassert)
    view.top_timer.timeout.emit()
    assert calls == [1]
