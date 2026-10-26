"""The floating command center's Windows-level parts: how a panel sits over a game without taking focus, hiding from the buddy's own
screen capture, letting clicks through, and being summoned by a hotkey that no game key uses. No graphics toolkit is needed here:
these functions work on any top-level window handle, so the same code serves the Qt panel and the tkinter fallback."""
