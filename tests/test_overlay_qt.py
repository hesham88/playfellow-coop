"""The Qt floating command center: glass look, no focus, click-through pill,
English and Arabic. Built offscreen; skipped when PySide6 is not installed."""
from __future__ import annotations

import os

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest

pytest.importorskip("PySide6")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication  # noqa: E402

from playfellow_coop.overlay.panel import PanelModel  # noqa: E402
from playfellow_coop.overlay.qt_view import TOKENS, QtOverlay, glass_stylesheet  # noqa: E402
from playfellow_coop.voice import CommandQueue  # noqa: E402


@pytest.fixture(scope="module")
def app():
    return QApplication.instance() or QApplication([])


def build(language="english"):
    queue = CommandQueue()
    model = PanelModel(queue, language=lambda: language)
    view = QtOverlay(model)
    return view, model, queue


def test_the_glass_stylesheet_carries_the_design_tokens(app):
    sheet = glass_stylesheet()
    for value in (TOKENS["cyan"], TOKENS["violet"], TOKENS["glass_line"], "border-radius: 26px"):
        assert value in sheet


def test_the_window_never_takes_focus_and_stays_on_top_as_a_tool(app):
    view, _, _ = build()
    flags = view.window.windowFlags()
    assert flags & Qt.WindowType.WindowDoesNotAcceptFocus
    assert flags & Qt.WindowType.WindowStaysOnTopHint
    assert flags & Qt.WindowType.Tool
    assert flags & Qt.WindowType.FramelessWindowHint
    assert view.window.testAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
    assert view.window.testAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)


def test_click_through_follows_the_model_and_the_caption_says_so(app):
    view, model, _ = build()
    assert model.click_through is True
    assert view.caption_label.text() == "Click-through active"
    model.show()
    assert model.click_through is False
    assert view.caption_label.text() == ""


def test_english_and_arabic_are_separate_versions(app):
    english, _, _ = build()
    assert english.title_label.text() == "Command Center"
    assert english.talk_button.text() == "Hold to Talk"
    assert english.window.layoutDirection() == Qt.LayoutDirection.LeftToRight
    arabic, _, _ = build("arabic")
    assert arabic.title_label.text() == "مركز الأوامر"
    assert arabic.talk_button.text() == "اضغط للتحدث"
    assert arabic.window.layoutDirection() == Qt.LayoutDirection.RightToLeft
    assert arabic.pill_label.text() == "Fello · جاهز"


def test_chips_and_typed_text_reach_the_command_queue(app):
    view, model, queue = build()
    model.show()
    view.chip_buttons[0].click()
    assert queue.drain() == ["Collect the coins"]
    view.entry.setText("go to the door")
    view.entry.returnPressed.emit()
    assert queue.drain() == ["go to the door"]


def test_hold_to_talk_and_hand_over_and_stop_fire_their_callbacks(app):
    calls = []
    queue = CommandQueue()
    model = PanelModel(queue, language=lambda: "english")
    view = QtOverlay(
        model,
        on_talk_down=lambda: calls.append("down"),
        on_talk_up=lambda: calls.append("up"),
        on_stop=lambda: calls.append("stop"),
        on_hand_over=lambda: calls.append("hand"),
    )
    view.talk_button.pressed.emit()
    view.talk_button.released.emit()
    view.hand_button.click()
    view.stop_button.click()
    assert calls == ["down", "up", "hand", "stop"]


def test_without_qt_the_overlay_says_so_and_opens_nothing(app, monkeypatch):
    import sys
    from types import SimpleNamespace

    from playfellow_coop.overlay.runner import OverlayUnavailableError, build_overlay

    monkeypatch.setitem(sys.modules, "PySide6", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtCore", None)
    monkeypatch.setitem(sys.modules, "PySide6.QtWidgets", None)
    parts = SimpleNamespace(safety=SimpleNamespace(stop=lambda reason: None), card=None)
    handover = SimpleNamespace(toggle=lambda: None)
    with pytest.raises(OverlayUnavailableError, match="PySide6"):
        build_overlay(parts, CommandQueue(), handover)


def test_opacity_and_chat_lines_follow_the_model(app):
    view, model, _ = build()
    model.set_opacity(0.55)
    assert view.window.windowOpacity() == pytest.approx(0.55, abs=0.01)  # Qt stores opacity in 1/255 steps
    model.buddy_says("On my way.")
    model.submit("grab the coins")
    texts = [
        view.chat_layout.itemAt(i).widget().text()
        for i in range(view.chat_layout.count())
    ]
    assert texts == ["On my way.", "grab the coins"]

