# overlay

The floating command center's Windows-level parts: how a panel sits over a game without taking focus, hiding from the buddy's own screen capture, letting clicks through, and being summoned by a hotkey that no game key uses.

## Files

- `hotkey.py`: The summon key: registered with Windows' own RegisterHotKey (no global keyboard hook, so it cannot swallow other keys or lag the game), and refused if the game's controls card uses that key.
- `panel.py`: The floating command center's brain, with no drawing in it: what is shown, what the buttons do, which language, which state.
- `pump.py`: Receive the summon key without a keyboard hook: Windows posts WM_HOTKEY to the thread that registered the key, so that thread runs a tiny message loop and calls us back.
- `qt_view.py`: A Qt view of the PanelModel: the floating command center in Playfellow glass.
- `runner.py`: Runs the floating command center next to the game session, so `--overlay` is a real switch and not a loose module.
- `spike.py`: The H7 spike's measurements, as plain functions, so the numbers come from code and the logic is tested with fakes.
- `tk_view.py`: A Tk view of the PanelModel: a translucent chat card that floats over a windowed or borderless game and never takes focus.
- `winstyle.py`: Window styles for an overlay that must never disturb the game underneath (rules 1, 2, 4 of the design):
