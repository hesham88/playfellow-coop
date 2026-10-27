"""A Qt view of the PanelModel: the floating command center in Playfellow glass.

PySide6 draws the same model the Tk view draws, with the design-system look
(contract 13): a frosted panel on a deep indigo ground, a cyan-to-violet
light edge, gradient primary actions. The window is frameless, translucent,
topmost, a tool window, and it never takes focus: opening it must not steal
the keyboard from the game. winstyle excludes it from screen capture and
makes it click-through while only the pill is showing.

PySide6 is an optional dependency: this module imports it lazily, and the
runner falls back to the Tk view when Qt is not installed.

Run it only from a real desktop session. Tests build it offscreen."""
from __future__ import annotations

from typing import Callable

from playfellow_coop.overlay import winstyle
from playfellow_coop.overlay.panel import PanelModel

# Design tokens (contract 13, fixed names and values).
TOKENS = {
    "bg_0": "#04061a",
    "ink": "#eaf0ff",
    "ink_2": "#aab4e6",
    "cyan": "#43e3ff",
    "violet": "#9b6bff",
    "glass_line": "rgba(170, 180, 255, 0.28)",
}
PANEL_SIZE, PILL_SIZE = (360, 560), (220, 44)
MARGIN = 24

STRINGS = {
    "title": ("Command Center", "مركز الأوامر"),
    "hold_to_talk": ("Hold to Talk", "اضغط للتحدث"),
    "hand_over": ("Hand Over", "سلّم التحكم"),
    "stop": ("Stop", "إيقاف"),
    "click_through": ("Click-through active", "النقر الشفاف مفعّل"),
}


def glass_stylesheet() -> str:
    """The panel stylesheet: frosted glass fill, light edge, gradient pills."""
    t = TOKENS
    return f"""
    QWidget#panel {{
        background: qlineargradient(x1:0, y1:0, x2:0, y2:1,
            stop:0 rgba(38,46,110,0.94), stop:0.5 rgba(20,26,74,0.92), stop:1 rgba(10,16,48,0.94));
        border: 1px solid {t["glass_line"]};
        border-radius: 26px;
        color: {t["ink"]};
    }}
    QLabel#title {{ font-size: 17px; font-weight: 700; color: {t["ink"]}; }}
    QLabel#pill {{ font-size: 13px; font-weight: 700; color: {t["cyan"]}; }}
    QLabel#partial {{ font-size: 12px; font-style: italic; color: {t["cyan"]}; }}
    QLabel#caption {{ font-size: 11px; color: {t["ink_2"]}; }}
    QLabel.bubbleBuddy {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t["violet"]}, stop:1 #7a4fe0);
        color: white; border-radius: 12px; padding: 7px 11px; font-size: 13px;
    }}
    QLabel.bubblePlayer {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 #19b8d8, stop:1 {t["cyan"]});
        color: #04101e; border-radius: 12px; padding: 7px 11px; font-size: 13px;
    }}
    QPushButton {{
        background: rgba(255,255,255,0.10); color: {t["ink"]};
        border: 1px solid {t["glass_line"]}; border-radius: 12px;
        padding: 7px 10px; font-size: 13px;
    }}
    QPushButton:hover {{ background: rgba(255,255,255,0.18); }}
    QPushButton#talk {{ font-size: 14px; font-weight: 700; min-height: 52px; border-radius: 16px; }}
    QPushButton#primary {{
        background: qlineargradient(x1:0, y1:0, x2:1, y2:0,
            stop:0 {t["cyan"]}, stop:1 {t["violet"]});
        color: white; font-weight: 700; border: none;
    }}
    QPushButton:focus {{ border: 2px solid {t["cyan"]}; }}
    QLineEdit {{
        background: rgba(10,16,48,0.65); color: {t["ink"]};
        border: 1px solid {t["glass_line"]}; border-radius: 12px; padding: 8px 10px;
    }}
    """


class _AfterAdapter:
    """The runner schedules its next tick with `root.after(ms, fn)` (the Tk
    spelling). The Qt spelling of the same idea is a single-shot timer."""

    def __init__(self, qtimer_single_shot):
        self._single_shot = qtimer_single_shot

    def after(self, ms: int, fn) -> None:
        self._single_shot(ms, fn)


class QtOverlay:
    """Draws a PanelModel. Same callbacks and lifecycle as the Tk view:
    start(), mainloop(), close(), and `root.after` for the runner."""

    def __init__(self, model: PanelModel, on_talk_down: Callable[[], None] = lambda: None,
                 on_talk_up: Callable[[], None] = lambda: None,
                 on_stop: Callable[[], None] = lambda: None, on_hand_over: Callable[[], None] = lambda: None,
                 show_in_recordings: bool = False, app=None):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import QApplication, QHBoxLayout, QLabel, QLineEdit, QPushButton, QVBoxLayout, QWidget

        self._qt, self._widgets = Qt, (QLabel, QLineEdit, QPushButton)
        self.model = model
        self._talk_down, self._talk_up, self._stop, self._hand_over = on_talk_down, on_talk_up, on_stop, on_hand_over
        self._show_in_recordings = show_in_recordings
        self.app = app or QApplication.instance() or QApplication([])
        self.root = _AfterAdapter(lambda ms, fn: QTimer.singleShot(ms, fn))

        self.window = QWidget()
        self.window.setWindowTitle("Playfellow")
        self.window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.window.setWindowFlags(
            Qt.WindowType.FramelessWindowHint
            | Qt.WindowType.WindowStaysOnTopHint
            | Qt.WindowType.Tool
            | Qt.WindowType.WindowDoesNotAcceptFocus
        )
        self.window.setStyleSheet(glass_stylesheet())
        self.window.setWindowOpacity(model.opacity)

        # A top-level translucent window does not paint its own background;
        # the glass fill lives on this inner panel, which fills the window.
        self.panel = QWidget(self.window)
        self.panel.setObjectName("panel")
        outer = QVBoxLayout(self.window)
        outer.setContentsMargins(0, 0, 0, 0)
        outer.addWidget(self.panel)

        layout = QVBoxLayout(self.panel)
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(9)

        self.pill_label = QLabel("", self.window)
        self.pill_label.setObjectName("pill")

        self.title_label = QLabel("", self.window)
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.chat_box = QWidget(self.window)
        self.chat_layout = QVBoxLayout(self.chat_box)
        self.chat_layout.setContentsMargins(0, 0, 0, 0)
        self.chat_layout.setSpacing(6)

        self.partial_label = QLabel("", self.window)
        self.partial_label.setObjectName("partial")

        self.talk_button = QPushButton("", self.window)
        self.talk_button.setObjectName("talk")
        self.talk_button.pressed.connect(lambda: self._talk_down())
        self.talk_button.released.connect(lambda: self._talk_up())

        self.chip_box = QWidget(self.window)
        self.chip_layout = QHBoxLayout(self.chip_box)
        self.chip_layout.setContentsMargins(0, 0, 0, 0)
        self.chip_layout.setSpacing(6)
        self.chip_buttons: list = []

        self.entry = QLineEdit(self.window)
        self.entry.returnPressed.connect(self._on_enter)

        actions = QHBoxLayout()
        self.hand_button = QPushButton("", self.window)
        self.hand_button.setObjectName("primary")
        self.hand_button.clicked.connect(lambda: self._hand_over())
        self.stop_button = QPushButton("", self.window)
        self.stop_button.setObjectName("primary")
        self.stop_button.clicked.connect(lambda: self._stop())
        actions.addWidget(self.hand_button)
        actions.addWidget(self.stop_button)

        self.caption_label = QLabel("", self.window)
        self.caption_label.setObjectName("caption")
        self.caption_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        layout.addWidget(self.pill_label)
        layout.addWidget(self.title_label)
        layout.addWidget(self.chat_box)
        layout.addWidget(self.partial_label)
        layout.addWidget(self.talk_button)
        layout.addWidget(self.chip_box)
        layout.addWidget(self.entry)
        layout.addLayout(actions)
        layout.addWidget(self.caption_label)

        self.hwnd = 0
        self.applied: winstyle.Applied | None = None
        model.subscribe(self._redraw)
        self._redraw()

    # ---- helpers -----------------------------------------------------------------------------------
    def _text(self, key: str) -> str:
        english, arabic = STRINGS[key]
        return arabic if self.model.arabic else english

    def _on_enter(self) -> None:
        if self.model.submit(self.entry.text()):
            self.entry.clear()

    # ---- drawing -----------------------------------------------------------------------------------
    def _redraw(self) -> None:
        from PySide6.QtCore import Qt

        model = self.model
        rtl = model.right_to_left
        self.window.setLayoutDirection(
            Qt.LayoutDirection.RightToLeft if rtl else Qt.LayoutDirection.LeftToRight
        )
        self.window.setWindowOpacity(model.opacity)
        self.pill_label.setText(model.pill_text)
        self.title_label.setText(self._text("title"))
        self.talk_button.setText(self._text("hold_to_talk"))
        self.hand_button.setText(self._text("hand_over"))
        self.stop_button.setText(self._text("stop"))
        self.caption_label.setText("" if model.visible else self._text("click_through"))
        self.entry.setPlaceholderText(model.placeholder())
        self.partial_label.setText(("… " + model.heard_partial) if model.heard_partial else "")

        while self.chat_layout.count():
            widget = self.chat_layout.takeAt(0).widget()
            if widget is not None:
                widget.setParent(None)
                widget.deleteLater()
        QLabel = self._widgets[0]
        for line in model.lines:
            bubble = QLabel(line.text, self.chat_box)
            bubble.setProperty("class", "bubblePlayer" if line.who == "player" else "bubbleBuddy")
            bubble.setWordWrap(True)
            bubble.setStyleSheet(glass_stylesheet())
            self.chat_layout.addWidget(bubble)

        for button in self.chip_buttons:
            self.chip_layout.removeWidget(button)
            button.setParent(None)
            button.deleteLater()
        self.chip_buttons = []
        QPushButton = self._widgets[2]
        for index, text in enumerate(model.chips):
            button = QPushButton(text, self.chip_box)
            button.clicked.connect(lambda _=False, i=index: model.press_chip(i))
            self.chip_layout.addWidget(button)
            self.chip_buttons.append(button)

        for widget in (self.title_label, self.chat_box, self.partial_label, self.talk_button,
                       self.chip_box, self.entry, self.hand_button, self.stop_button):
            widget.setVisible(model.visible)
        self.pill_label.setVisible(not model.visible)
        width, height = PANEL_SIZE if model.visible else PILL_SIZE
        self.window.resize(width, height)
        screen = self.window.screen()
        if screen is not None:
            geo = screen.availableGeometry()
            left = geo.left() + MARGIN if rtl else geo.right() - width - MARGIN
            self.window.move(left, geo.top() + MARGIN)
        if self.hwnd:
            self.applied = winstyle.apply_overlay_style(
                self.hwnd, click_through=model.click_through,
                show_in_recordings=self._show_in_recordings,
            )

    def start(self) -> None:
        """Show the pill and apply the Windows overlay style. Never activates."""
        self._redraw()
        self.window.show()
        self.hwnd = int(self.window.winId())
        self._redraw()  # now with a window handle, so the style is applied

    def mainloop(self) -> None:
        self.app.exec()

    def close(self) -> None:
        self.window.close()
