"""The buddy's character as its real 3D model: the crew member's lite Meshy GLB (assets/derived/glb-lite), drawn live with
three.js in a see-through web view standing at the left end of the widget's bar, playing the model's own rigged clips
(Idle, Big_Wave_Hello, Victory_Cheer, Talk_with_Hands_Open, walking, running), cross-faded by the buddy's mood.
"""
from __future__ import annotations

import os
import time
from pathlib import Path

from playfellow_coop.overlay.avatar import CHARACTERS, HOLD_SECONDS, mood_for

LITE = Path(os.environ.get("PLAYFELLOW_ASSETS") or Path.home() / ".playfellow" / "stk" / "assets") / "derived" / "glb-lite"
MODELS = {"fello": "pf_s08_glblite-fello_v3.glb", "dalil": "pf_s08_glblite-dalil_v3.glb", "rami": "pf_s08_glblite-rami_v4.glb",
          "hakim": "pf_s08_glblite-hakim_v6.glb", "vela": "pf_s08_glblite-vela_v4.glb"}
PAGE = Path(__file__).with_name("avatar3d.html")
MOOD_TO_CLIP = {"walk": "run", "point": "point", "celebrate": "celebrate", "wave": "wave", "thinking": "thinking", "idle": "idle"}


class Avatar3D:  # pragma: no cover - needs a desktop and a GPU
    def __init__(self, bar_window, height: int = 84, character: str = "fello", show_in_recordings: bool = True):
        if not (LITE / MODELS[character]).exists():  # the art is not in this repo: the caller goes on without the character
            raise FileNotFoundError(f"no model file for {character}: set PLAYFELLOW_ASSETS")
        from PySide6.QtCore import QTimer, QUrl, Qt
        from PySide6.QtGui import QColor
        from PySide6.QtWebEngineCore import QWebEngineSettings
        from PySide6.QtWebEngineWidgets import QWebEngineView

        self.bar = bar_window
        self.height, self.width = height, int(height * 0.62)
        self.character, self.mood, self.mood_since = character, "idle", 0.0
        self.view = QWebEngineView()
        self.view.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.view.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.view.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        self.view.page().setBackgroundColor(QColor(0, 0, 0, 0))
        settings = self.view.settings()
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessFileUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.LocalContentCanAccessRemoteUrls, True)
        settings.setAttribute(QWebEngineSettings.WebAttribute.WebGLEnabled, True)
        self.view.resize(self.width, self.height)
        url = QUrl.fromLocalFile(str(PAGE))
        url.setQuery("model=" + QUrl.fromLocalFile(str(LITE / MODELS[character])).toString())
        self.view.load(url)
        self.view.show()
        self._show_in_recordings = show_in_recordings
        self.timer = QTimer()
        self.timer.setInterval(300)
        self.timer.timeout.connect(self._follow)
        self.timer.start()

    def _js(self, code: str) -> None:
        self.view.page().runJavaScript(code)

    def set_character(self, character: str) -> None:
        from PySide6.QtCore import QUrl

        self.character = character
        self._js(f"setCharacter({QUrl.fromLocalFile(str(LITE / MODELS[character])).toString()!r})")

    def react(self, line: str) -> None:
        mood = mood_for(line)
        now = time.monotonic()
        if mood and mood != self.mood and now - self.mood_since >= HOLD_SECONDS:
            self.mood, self.mood_since = mood, now
            self._js(f"setMood({MOOD_TO_CLIP.get(mood, 'idle')!r})")

    def _follow(self) -> None:
        bar = self.bar
        bar_h = min(bar.height(), 52)
        self.view.move(bar.x() - self.width - 6, max(bar.y() + (bar_h - self.height) // 2, 0))
        if self.mood != "idle" and time.monotonic() - self.mood_since > 8.0:
            self.mood, self.mood_since = "idle", time.monotonic()
            self._js("setMood('idle')")
        try:
            from playfellow_coop.overlay import winstyle

            winstyle.apply_overlay_style(int(self.view.winId()), click_through=True, show_in_recordings=self._show_in_recordings)
        except OSError:
            pass

    def make_choice(self, parent):
        from PySide6.QtWidgets import QComboBox, QHBoxLayout, QLabel, QWidget

        row = QWidget(parent)
        line = QHBoxLayout(row)
        line.setContentsMargins(0, 0, 0, 4)
        label = QLabel("Your buddy", row)
        label.setStyleSheet("color:#9fe8ff;font-size:12px")
        combo = QComboBox(row)
        combo.addItems([c.capitalize() for c in CHARACTERS])
        combo.setCurrentIndex(CHARACTERS.index(self.character))
        combo.setStyleSheet("QComboBox{background:rgba(20,24,60,220);color:#e8f6ff;border:1px solid #4a5bd8;"
                            "border-radius:8px;font-size:12px;padding:3px 8px;min-width:110px}")
        combo.currentIndexChanged.connect(lambda i: self.set_character(CHARACTERS[i]))
        line.addWidget(label)
        line.addWidget(combo)
        line.addStretch(1)
        return row
