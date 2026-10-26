"""A Tk view of the PanelModel: a translucent chat card that floats over a windowed or borderless game and never takes focus.

Tk is the engine's own toolkit, so this needs no new dependency. It is the v0 and the fallback; a Qt skin can draw the same model
later. The window is a borderless top-level; winstyle makes it non-activating, a tool window (no taskbar button), topmost, excluded
from our screen capture, and click-through while only the pill is showing. Whole-window alpha gives the translucent card.

Run it only from a real desktop session. Tests build the model and the style functions without a window."""
from __future__ import annotations

import ctypes
import tkinter as tk
from typing import Callable

from playfellow_coop.overlay import winstyle
from playfellow_coop.overlay.panel import PanelModel

BACKGROUND, TEXT, ACCENT, PLAYER_TEXT = "#14141f", "#f2f2f7", "#22e4ff", "#b6ff3b"
PANEL_SIZE, PILL_SIZE = (360, 420), (190, 34)
MARGIN = 24


class TkOverlay:
    def __init__(self, model: PanelModel, on_talk_down: Callable[[], None] = lambda: None, on_talk_up: Callable[[], None] = lambda: None,
                 on_stop: Callable[[], None] = lambda: None, on_hand_over: Callable[[], None] = lambda: None,
                 show_in_recordings: bool = False, root: tk.Tk | None = None):
        self.model = model
        self._talk_down, self._talk_up, self._stop, self._hand_over = on_talk_down, on_talk_up, on_stop, on_hand_over
        self._show_in_recordings = show_in_recordings
        self.root = root or tk.Tk()
        self.root.withdraw()
        self.root.overrideredirect(True)  # no title bar
        self.root.attributes("-topmost", True)
        self.root.configure(bg=BACKGROUND)
        self._build()
        model.subscribe(self._redraw)
        self.hwnd = 0
        self.applied: winstyle.Applied | None = None

    # ---- construction ----------------------------------------------------------------------------------------------
    def _build(self) -> None:
        self.pill = tk.Label(self.root, text="", bg=BACKGROUND, fg=ACCENT, font=("Segoe UI", 11, "bold"), padx=10, pady=6)
        self.card = tk.Frame(self.root, bg=BACKGROUND)
        self.chat = tk.Text(self.card, height=11, width=40, bg=BACKGROUND, fg=TEXT, bd=0, wrap="word", state="disabled",
                            font=("Segoe UI", 10), highlightthickness=0)
        self.chat.tag_configure("player", foreground=PLAYER_TEXT)
        self.chat.tag_configure("rtl", justify="right")
        self.partial = tk.Label(self.card, text="", bg=BACKGROUND, fg=ACCENT, font=("Segoe UI", 9, "italic"), anchor="w")
        self.chip_row = tk.Frame(self.card, bg=BACKGROUND)
        self.entry = tk.Entry(self.card, bg="#22223a", fg=TEXT, insertbackground=TEXT, bd=0, font=("Segoe UI", 10))
        self.entry.bind("<Return>", self._on_enter)
        buttons = tk.Frame(self.card, bg=BACKGROUND)
        self.talk = tk.Button(buttons, text="Hold to talk", bg="#2a2a4a", fg=TEXT, bd=0, activebackground=ACCENT)
        self.talk.bind("<ButtonPress-1>", lambda event: self._talk_down())
        self.talk.bind("<ButtonRelease-1>", lambda event: self._talk_up())
        self.hand = tk.Button(buttons, text="Hand over", bg="#2a2a4a", fg=TEXT, bd=0, command=self._hand_over)
        self.stop = tk.Button(buttons, text="Stop (F12)", bg="#5a1a2a", fg=TEXT, bd=0, command=self._stop)
        for widget in (self.talk, self.hand, self.stop):
            widget.pack(side="left", padx=3, pady=2, fill="x", expand=True)
        self.chat.pack(fill="both", expand=True, padx=10, pady=(10, 2))
        self.partial.pack(fill="x", padx=10)
        self.chip_row.pack(fill="x", padx=10, pady=4)
        self.entry.pack(fill="x", padx=10, pady=4)
        buttons.pack(fill="x", padx=10, pady=(2, 10))

    def _on_enter(self, event) -> None:
        if self.model.submit(self.entry.get()):
            self.entry.delete(0, "end")

    # ---- drawing ---------------------------------------------------------------------------------------------------
    def _redraw(self) -> None:
        model, rtl = self.model, self.model.right_to_left
        self.root.attributes("-alpha", model.opacity)
        self.pill.configure(text=model.pill_text)
        for child in self.chip_row.winfo_children():
            child.destroy()
        for index, text in enumerate(model.chips):
            tk.Button(self.chip_row, text=text, bg="#2a2a4a", fg=TEXT, bd=0, command=lambda i=index: model.press_chip(i)).pack(
                side="right" if rtl else "left", padx=2)
        self.talk.configure(text="اضغط للتحدث" if model.arabic else "Hold to talk")
        self.hand.configure(text="سلّم التحكم" if model.arabic else "Hand over")
        self.stop.configure(text="إيقاف (F12)" if model.arabic else "Stop (F12)")
        self.partial.configure(text=("… " + model.heard_partial) if model.heard_partial else "", anchor="e" if rtl else "w")
        self.chat.configure(state="normal")
        self.chat.delete("1.0", "end")
        for line in model.lines:
            tags = ("player",) if line.who == "player" else ()
            self.chat.insert("end", line.text + "\n", tags + (("rtl",) if rtl else ()))
        self.chat.configure(state="disabled")
        self._place()
        if self.hwnd:
            self.applied = winstyle.apply_overlay_style(self.hwnd, click_through=model.click_through,
                                                        show_in_recordings=self._show_in_recordings)

    def _place(self) -> None:
        width, height = PANEL_SIZE if self.model.visible else PILL_SIZE
        screen_w = self.root.winfo_screenwidth()
        left = MARGIN if self.model.right_to_left else screen_w - width - MARGIN
        self.root.geometry(f"{width}x{height}+{left}+{MARGIN}")
        if self.model.visible:
            self.pill.pack_forget()
            self.card.pack(fill="both", expand=True)
        else:
            self.card.pack_forget()
            self.pill.pack(fill="both", expand=True)

    def start(self) -> None:
        """Map the window, style it (no focus, no capture, topmost) and show the pill. Never activates the window."""
        self._redraw()
        self.root.update_idletasks()
        self.root.deiconify()
        self.root.update()
        self.hwnd = ctypes.windll.user32.GetParent(self.root.winfo_id()) or self.root.winfo_id()
        self._redraw()  # now with a window handle, so the style is applied

    def mainloop(self) -> None:
        self.root.mainloop()

    def close(self) -> None:
        self.root.destroy()
