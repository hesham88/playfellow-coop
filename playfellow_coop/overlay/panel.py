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
OPACITY_RANGE = (0.3, 1.0)  # the lowest point of the slider is still visible: the widget is never invisible
DEFAULT_OPACITY = 0.55  # see-through by default, over the game
DOCK_TOP = 6  # pixels from the top edge of the screen
BAR_WIDTH, BAR_HEIGHT, PANEL_HEIGHT = 560, 52, 440  # the slim bar, and the panel it slides open into (its rows need 430)
OPACITY_STEPS = (0.3, 0.55, 0.8, 1.0)  # the see-through key walks these and wraps; the first is the floor, never invisible
CHAT_LINES, CHAT_CHARS = 4, 140  # what the open panel shows, so a long spoken request can never make it outgrow PANEL_HEIGHT
KEY_WORDS = {"talk": ("talk", "تحدّث"), "panel": ("open", "افتح"), "see_through": ("see-through", "الشفافية"),
             "hand": ("hand over", "سلّم التحكم"), "stop": ("stop", "إيقاف")}


def key_label(key: str) -> str:
    """"ctrl+alt+p" -> "Ctrl+Alt+P", "f8" -> "F8": how a key is written on the bar."""
    return "+".join(piece.upper() if len(piece) <= 3 and (len(piece) == 1 or piece[0] == "f") else piece.capitalize()
                    for piece in key.split("+") if piece)


def dock_rect(screen_left: int, screen_top: int, screen_width: int, width: int, height: int) -> tuple[int, int, int, int]:
    """Where the widget sits: centred at the top of the screen the game is on."""
    return screen_left + (screen_width - width) // 2, screen_top + DOCK_TOP, width, height


def slide_heights(start: int, end: int, ms: int = 220, fps: int = 60) -> list[int]:
    """The heights of a slide from start to end, eased out (fast first, gentle at the end), ending exactly on `end`."""
    if start == end:
        return [end]
    frames = max(2, round(ms * fps / 1000))
    out = []
    for i in range(1, frames + 1):
        t = i / frames
        eased = 1 - (1 - t) ** 3
        out.append(round(start + (end - start) * eased))
    out[-1] = end
    return out


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
        self.opacity = DEFAULT_OPACITY
        self.heard_partial = ""
        self.keys: dict[str, str] = {"hand": "f9", "stop": "f12"}  # the session's own keys; set_keys adds the talk and widget keys

    # ---- what a view needs -------------------------------------------------------------------------------------
    @property
    def arabic(self) -> bool:
        return self._language() == "arabic"

    @property
    def right_to_left(self) -> bool:
        return self.arabic  # the Arabic panel mirrors

    @property
    def collapsed(self) -> bool:
        """The slim bar at the top centre; open, it slides down into the full panel."""
        return not self.visible

    @property
    def click_through(self) -> bool:
        """The bar carries the mic and the open arrow, so it takes clicks on its own small area, open or closed (it never takes focus)."""
        return False

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

    def toggle_collapsed(self) -> bool:
        """Open or close the widget (the bar's own arrow, or the summon key). Returns the new collapsed state."""
        self.toggle()
        return self.collapsed

    def step_opacity(self) -> float:
        """The see-through key: the next level up, wrapping from fully solid back to the floor (never invisible)."""
        higher = [level for level in OPACITY_STEPS if level > self.opacity + 1e-6]
        return self.set_opacity(higher[0] if higher else OPACITY_STEPS[0])

    def set_keys(self, talk: str | None = None, panel: str | None = None, see_through: str | None = None) -> None:
        """The keys this run really listens to, so the bar promises only those (in full screen the mouse is often gone)."""
        for name, key in (("talk", talk), ("panel", panel), ("see_through", see_through)):
            if key:
                self.keys[name] = key
        self._changed()

    @property
    def shortcut_hint(self) -> str:
        """One line for the bar, every key written out: "F8 talk · Ctrl+Alt+P open · Ctrl+Alt+O see-through · F9 hand over · F12 stop"."""
        index = 1 if self.arabic else 0
        order = ("talk", "panel", "see_through", "hand", "stop")
        return " · ".join(f"{key_label(self.keys[name])} {KEY_WORDS[name][index]}" for name in order if name in self.keys)

    def shown_lines(self) -> list[Line]:
        """The last few lines, each cut short: the open panel draws these, so it keeps its height whatever is said."""
        return [Line(line.who, line.text if len(line.text) <= CHAT_CHARS else line.text[:CHAT_CHARS - 1] + "…")
                for line in list(self.lines)[-CHAT_LINES:]]

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
