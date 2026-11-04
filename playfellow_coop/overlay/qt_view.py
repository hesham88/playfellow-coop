"""A Qt view of the PanelModel: the floating command center in Playfellow glass.

PySide6 draws the same model the Tk view draws, with the design-system look
(contract 13): a frosted panel on a deep indigo ground, a cyan-to-violet
light edge, gradient primary actions. The window is frameless, translucent,
topmost, a tool window, and it never takes focus: opening it must not steal
the keyboard from the game. winstyle excludes it from screen capture and
makes it click-through while only the pill is showing.

PySide6 is imported lazily, so importing this module never fails; the
runner refuses to open the overlay (with a plain message) when Qt is not
installed. There is no Tk fallback in the product path.

Run it only from a real desktop session. Tests build it offscreen."""
from __future__ import annotations

from typing import Callable

from playfellow_coop.overlay import winstyle
from playfellow_coop.overlay.panel import BAR_HEIGHT, BAR_WIDTH, OPACITY_RANGE, PANEL_HEIGHT, PanelModel, dock_rect, slide_heights

CHAT_HEIGHT = 130  # the chat's fixed window inside the open panel (the panel's other rows take the rest of PANEL_HEIGHT)

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
    QLabel#keys {{ font-size: 10px; color: {t["ink_2"]}; }}
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
    QPushButton#talk {{ font-size: 14px; font-weight: 700; min-height: 22px; border-radius: 14px; }}
    QPushButton#barButton {{ font-size: 15px; padding: 0px; border-radius: 15px; }}
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
                 show_in_recordings: bool = False, app=None, animate: bool = True,
                 follow: Callable[[], tuple[int, int, int, int] | None] | None = None):
        """`follow`, when given, returns the game window's client rectangle (left, top, right, bottom, physical screen
        pixels) or None; the widget then docks at the top centre of that window and follows it, instead of the screen's."""
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtWidgets import (QApplication, QFrame, QHBoxLayout, QLabel, QLineEdit, QPushButton, QScrollArea, QSizePolicy, QSlider,
                                       QVBoxLayout, QWidget)

        self._qt, self._widgets = Qt, (QLabel, QLineEdit, QPushButton)
        self.model = model
        self._talk_down, self._talk_up, self._stop, self._hand_over = on_talk_down, on_talk_up, on_stop, on_hand_over
        self._show_in_recordings = show_in_recordings
        self._follow = follow
        self.allow_focus = False  # True while the panel is open for typing (set by the host)
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
        self.panel_layout = layout
        layout.setContentsMargins(18, 16, 18, 14)
        layout.setSpacing(9)

        # the slim bar, always there: who and what state, the mic (hold to talk) and the arrow that opens or closes the panel
        self.bar = QWidget(self.window)
        bar = QHBoxLayout(self.bar)
        bar.setContentsMargins(0, 0, 0, 0)
        bar.setSpacing(8)
        self.pill_label = QLabel("", self.window)
        self.pill_label.setObjectName("pill")
        self.bar_talk = QPushButton("🎙", self.window)
        self.bar_talk.setObjectName("barButton")
        self.bar_talk.setToolTip("Hold to talk")
        self.bar_talk.pressed.connect(lambda: self._talk_down())
        self.bar_talk.released.connect(lambda: self._talk_up())
        self.toggle_button = QPushButton("▾", self.window)
        self.toggle_button.clicked.connect(self._toggle)
        self.toggle_button.setObjectName("barButton")
        for button in (self.bar_talk, self.toggle_button):  # compact, so the folded bar keeps BAR_HEIGHT
            button.setFixedSize(30, 30)
        self.keys_label = QLabel("", self.window)  # every key written out: in full screen the mouse is often gone
        self.keys_label.setObjectName("keys")
        for label in (self.pill_label, self.keys_label):  # a long line is clipped, never widens the docked window
            label.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)
            label.setMinimumWidth(0)
        words = QVBoxLayout()
        words.setContentsMargins(0, 0, 0, 0)
        words.setSpacing(0)
        words.addWidget(self.pill_label)
        words.addWidget(self.keys_label)
        bar.addLayout(words, 1)
        bar.addWidget(self.bar_talk)
        bar.addWidget(self.toggle_button)

        self.opacity_slider = QSlider(Qt.Orientation.Horizontal, self.window)
        self.opacity_slider.setRange(round(OPACITY_RANGE[0] * 100), round(OPACITY_RANGE[1] * 100))  # the lowest point is still visible
        self.opacity_slider.setValue(round(model.opacity * 100))
        self.opacity_slider.valueChanged.connect(lambda v: model.set_opacity(v / 100))
        self._animate = animate
        self.slide_plan: list[int] = []
        self.slide_timer = QTimer()
        self.slide_timer.setInterval(16)
        self.slide_timer.timeout.connect(self._slide_step)
        self.top_timer = QTimer()  # full-screen games: stay on top, re-asserted often, never activating
        self.top_timer.setInterval(300)
        self.top_timer.timeout.connect(self._reassert)
        self._height = BAR_HEIGHT

        self.title_label = QLabel("", self.window)
        self.title_label.setObjectName("title")
        self.title_label.setAlignment(Qt.AlignmentFlag.AlignCenter)

        self.chat_scroll = QScrollArea(self.window)  # a fixed window onto the chat: the panel keeps PANEL_HEIGHT whatever is said
        self.chat_scroll.setWidgetResizable(True)
        self.chat_scroll.setFrameShape(QFrame.Shape.NoFrame)
        self.chat_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarPolicy.ScrollBarAlwaysOff)
        self.chat_scroll.setFixedHeight(CHAT_HEIGHT)
        self.chat_box = QWidget()
        self.chat_scroll.setWidget(self.chat_box)
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
        self.chip_box.setSizePolicy(QSizePolicy.Policy.Ignored, QSizePolicy.Policy.Preferred)  # clipped, never widens the window
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

        layout.addWidget(self.bar)
        layout.addWidget(self.title_label)
        layout.addWidget(self.chat_scroll)
        layout.addWidget(self.partial_label)
        layout.addWidget(self.talk_button)
        layout.addWidget(self.chip_box)
        layout.addWidget(self.entry)
        layout.addLayout(actions)
        layout.addWidget(self.opacity_slider)
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
        self.keys_label.setText(model.shortcut_hint)
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
        for line in model.shown_lines():  # the last few, cut short: the panel keeps its height whatever is said
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

        for widget in (self.title_label, self.chat_scroll, self.partial_label, self.talk_button,
                       self.chip_box, self.entry, self.hand_button, self.stop_button, self.opacity_slider):
            widget.setVisible(model.visible)
        self.caption_label.setVisible(model.visible and bool(self.caption_label.text()))
        self.panel_layout.setContentsMargins(*((18, 12, 18, 12) if model.visible else (14, 8, 14, 8)))  # folded: just the bar
        self.panel_layout.invalidate()  # the minimum size follows what is shown, so Windows never refuses the folded or open size
        self.window.layout().invalidate()
        self.toggle_button.setText("▴" if model.visible else "▾")
        target = PANEL_HEIGHT if model.visible else BAR_HEIGHT
        if target != self._height and not self.slide_plan:
            self.slide_plan = slide_heights(self._height, target)
            if self._animate:
                self.slide_timer.start()
        self._place(self._height)
        if self.hwnd:
            self.applied = winstyle.apply_overlay_style(
                self.hwnd, click_through=model.click_through,
                show_in_recordings=self._show_in_recordings, allow_focus=self.allow_focus,
            )

    # ---- the widget's motion: docked at the top centre, sliding open and closed --------------------------------
    def _place(self, height: int) -> None:
        self.window.resize(BAR_WIDTH, height)
        screen = self.window.screen()
        target = self._follow() if self._follow is not None else None
        if target is not None:  # glued to the game: the top centre of its window, wherever the window is or however big
            scale = screen.devicePixelRatio() if screen is not None else 1.0
            left, top, right, _ = (v / scale for v in target)
            x, y, _, _ = dock_rect(int(left), int(top), int(right - left), BAR_WIDTH, height)
            if (x, y) != (self.window.x(), self.window.y()):
                self.window.move(x, y)
        elif screen is not None:
            geo = screen.availableGeometry()
            x, y, _, _ = dock_rect(geo.left(), geo.top(), geo.width(), BAR_WIDTH, height)
            self.window.move(x, y)

    def _toggle(self) -> None:
        self.model.toggle_collapsed()

    def _slide_step(self) -> None:
        if not self.slide_plan:
            self.slide_timer.stop()
            return
        self._height = self.slide_plan.pop(0)
        self._place(self._height)
        if not self.slide_plan:
            self.slide_timer.stop()

    def finish_slide(self) -> None:
        """Play the rest of the slide at once (tests, and a closing window)."""
        while self.slide_plan:
            self._slide_step()

    def _reassert(self) -> None:
        if self.hwnd:
            winstyle.keep_on_top(self.hwnd)
        if self._follow is not None:  # the game window moved or resized: follow it
            self._place(self._height)

    def start(self) -> None:
        """Show the pill and apply the Windows overlay style. Never activates."""
        self._redraw()
        self.window.show()
        self.hwnd = int(self.window.winId())
        self._redraw()  # now with a window handle, so the style is applied
        self.top_timer.start()

    def mainloop(self) -> None:
        self.app.exec()

    def close(self) -> None:
        self.window.close()
