"""The buddy's character beside the widget: a small Fello (or Dalil, Rami, Hakim, Vela) standing at the left end of the bar,
playing the library's animation frames and reacting to what the buddy is doing.

The frames are the asset library's atlases (assets/derived/atlas/<name>/<name>-<action>.webp + .json, pf-atlas/1: a grid
of transparent frames rendered from each character's 3D model). The mini version is the same frames drawn small.

Mood from the buddy's own lines (`mood_for`): racing -> walk, a dodge or a turn -> point, a win -> celebrate, a model
thinking or reading -> thinking, a command heard or a hand-over -> wave, otherwise idle. A mood is held for a few seconds
before the next change, so the character does not flicker between moves.
"""
from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path

ATLAS = Path(os.environ.get("PLAYFELLOW_ASSETS") or Path.home() / ".playfellow" / "stk" / "assets") / "derived" / "atlas"
CHARACTERS = ("fello", "dalil", "rami", "hakim", "vela")
MOODS = ("idle", "walk", "point", "celebrate", "thinking", "wave")
HOLD_SECONDS = 2.5  # a mood stays at least this long (2-3 of the buddy's actions)

RULES = (
    ("celebrate", r"finished 1st|\bwon\b|1st place|results table says i finished 1"),
    ("point", r"banana|steering around|going for the|steering (left|right)|dodg"),
    ("wave", r"heard '|f9|you have the controls|i have the controls|hi, i'm"),
    ("thinking", r"thinking|menu:|reading|catalogue|learned|race notes|looking"),
    ("walk", r"set!|driving|racing|lap \d|nitro|full throttle|drift"),
)


def mood_for(line: str) -> str | None:
    low = line.lower()
    for mood, pattern in RULES:
        if re.search(pattern, low):
            return mood
    return None


def load_frames(character: str, mood: str):
    """The animation's frames as (atlas path, [(x, y, w, h), ...]) from the library's frame map."""
    meta = json.loads((ATLAS / character / f"{character}-{mood}.json").read_text(encoding="utf-8"))
    frames = [(f["x"], f["y"], f["w"], f["h"]) for f in meta["frames"] if not f.get("empty")]
    return ATLAS / character / meta["image"], frames


class Avatar:  # pragma: no cover - needs a desktop
    """A small frameless, see-through, always-on-top window that stands at the left end of the bar and follows it."""

    def __init__(self, bar_window, height: int = 96, character: str = "fello", show_in_recordings: bool = True):
        from PySide6.QtCore import Qt, QTimer
        from PySide6.QtGui import QPixmap
        from PySide6.QtWidgets import QComboBox, QLabel, QVBoxLayout, QWidget

        self._qt, self._QPixmap = Qt, QPixmap
        self.bar = bar_window
        self.height = height
        self.width = int(height * 256 / 341)
        self.character, self.mood, self.mood_since = character, "idle", 0.0
        self.window = QWidget()
        self.window.setWindowFlags(Qt.WindowType.FramelessWindowHint | Qt.WindowType.WindowStaysOnTopHint | Qt.WindowType.Tool)
        self.window.setAttribute(Qt.WidgetAttribute.WA_TranslucentBackground)
        self.window.setAttribute(Qt.WidgetAttribute.WA_ShowWithoutActivating)
        layout = QVBoxLayout(self.window)
        layout.setContentsMargins(0, 0, 0, 0)
        layout.setSpacing(1)
        self.picture = QLabel(self.window)
        self.picture.setFixedSize(self.width, self.height)
        layout.addWidget(self.picture)
        self.window.resize(self.width, self.height)
        self._load()
        self.frame_i = 0
        self.timer = QTimer()
        self.timer.setInterval(90)
        self.timer.timeout.connect(self._tick)
        self.timer.start()
        self.window.show()
        self._show_in_recordings = show_in_recordings

    def make_choice(self, parent):
        """The character drop-down, for the expanded panel (not the folded bar)."""
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

    def _load(self) -> None:
        image, self.frames = load_frames(self.character, self.mood)
        self.sheet = self._QPixmap(str(image))
        self.frame_i = 0

    def set_character(self, character: str) -> None:
        self.character = character
        self._load()

    def react(self, line: str) -> None:
        """Called with each new line of the buddy's: change the animation when the mood changes (held a little)."""
        mood = mood_for(line)
        now = time.monotonic()
        if mood and mood != self.mood and now - self.mood_since >= HOLD_SECONDS:
            self.mood, self.mood_since = mood, now
            self._load()

    def settle(self) -> None:
        """Back to idle when nothing has happened for a while."""
        if self.mood != "idle" and time.monotonic() - self.mood_since > 8.0:
            self.mood, self.mood_since = "idle", time.monotonic()
            self._load()

    def _tick(self) -> None:
        x, y, w, h = self.frames[self.frame_i % len(self.frames)]
        self.frame_i += 1
        piece = self.sheet.copy(x, y, w, h).scaled(self.width, self.height, self._qt.AspectRatioMode.KeepAspectRatio,
                                                   self._qt.TransformationMode.SmoothTransformation)
        self.picture.setPixmap(piece)
        bar = self.bar
        bar_h = min(bar.height(), 52)  # the folded bar's height: the character stands centred on it, a little taller
        self.window.move(bar.x() - self.window.width() - 6, max(bar.y() + (bar_h - self.height) // 2, 0))
        if self.frame_i % 30 == 0:
            self.settle()
            try:
                from playfellow_coop.overlay import winstyle

                winstyle.apply_overlay_style(int(self.window.winId()), click_through=False,
                                             show_in_recordings=self._show_in_recordings, allow_focus=True)
            except OSError:
                pass
