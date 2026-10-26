"""The floating command center's brain, with no drawing in it: what is shown, what the buttons do, which language, which state.
A Tk view (and later a Qt view) only draws this model and calls its methods. Nothing here imports a toolkit, so all of it is tested
without a window.

Rules it keeps: click-through is ON only for the small pinned pill and OFF while the panel is open (so its buttons work); the
panel never presses a game key itself: chips and typed text become commands for the buddy through the same queue as speech, and
the engine's controls-card check still decides which keys are pressed."""
from __future__ import annotations

from collections import deque
from dataclasses import dataclass
from typing import Callable

from messages import get_language

from playfellow_coop.voice import CommandQueue

STATES = {"ready": ("ready", "جاهز"), "listening": ("listening", "أستمع"), "thinking": ("thinking", "أفكر"),
          "player": ("you have the controls", "التحكم معك"), "stopped": ("stopped", "متوقف")}
CHIPS = (("Collect the coins", "اجمع العملات"), ("Take me to the door", "وصّلني للباب"), ("You take it", "خذها"))
MAX_LINES = 6
OPACITY_RANGE = (0.3, 1.0)


@dataclass(frozen=True)
class Line:
    who: str  # "buddy" or "player"
    text: str


class PanelModel:
    def __init__(self, commands: CommandQueue, name: str = "Fello", language: Callable[[], str] = get_language):
        self._commands, self._name, self._language = commands, name, language
        self._listeners: list[Callable[[], None]] = []
        self.visible = False
        self.state = "ready"
        self.lines: deque[Line] = deque(maxlen=MAX_LINES)
        self.opacity = 0.9
        self.heard_partial = ""

    # ---- what a view needs -------------------------------------------------------------------------------------
    @property
    def arabic(self) -> bool:
        return self._language() == "arabic"

    @property
    def right_to_left(self) -> bool:
        return self.arabic  # the Arabic panel mirrors

    @property
    def click_through(self) -> bool:
        """ON only for the pinned pill (the panel is hidden), OFF while the panel is open so its buttons can be pressed."""
        return not self.visible

    @property
    def pill_text(self) -> str:
        english, arabic = STATES[self.state]
        return f"{self._name} · {arabic if self.arabic else english}"

    @property
    def chips(self) -> list[str]:
        return [arabic if self.arabic else english for english, arabic in CHIPS]

    def placeholder(self) -> str:
        return "اكتب أمرًا…" if self.arabic else "Type a command…"

    # ---- what happens ------------------------------------------------------------------------------------------
    def subscribe(self, listener: Callable[[], None]) -> None:
        self._listeners.append(listener)

    def _changed(self) -> None:
        for listener in list(self._listeners):
            listener()

    def toggle(self) -> bool:
        """The summon key: the same press opens and closes. Returns the new visibility."""
        self.visible = not self.visible
        self._changed()
        return self.visible

    def show(self) -> None:
        if not self.visible:
            self.visible = True
            self._changed()

    def hide(self) -> None:
        if self.visible:
            self.visible = False
            self._changed()

    def set_opacity(self, value: float) -> float:
        low, high = OPACITY_RANGE
        self.opacity = max(low, min(high, float(value)))  # never fully invisible, never above fully opaque
        self._changed()
        return self.opacity

    def set_state(self, state: str) -> None:
        if state not in STATES:
            raise ValueError(f"unknown state {state!r}")
        if state != self.state:
            self.state = state
            self._changed()

    def buddy_says(self, text: str) -> None:
        if text and text.strip():
            self.lines.append(Line("buddy", text.strip()))
            self._changed()

    def partial(self, text: str) -> None:
        """Live words while the player is still speaking."""
        self.heard_partial = text.strip()
        self._changed()

    def submit(self, text: str) -> bool:
        """Typed text or a chip or a finished spoken command: it becomes a command for the buddy, and a line in the chat."""
        if not self._commands.put(text):
            return False
        self.heard_partial = ""
        self.lines.append(Line("player", text.strip()[:300]))
        self._changed()
        return True

    def press_chip(self, index: int) -> bool:
        return self.submit(self.chips[index])
