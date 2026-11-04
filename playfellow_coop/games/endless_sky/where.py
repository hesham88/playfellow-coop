"""Where the Endless Sky pack keeps its things on this PC: nothing machine-specific is written in the code.

  PLAYFELLOW_GAME_DIR  the pack's working folder: sessions, recordings, the widget's feed (default ~/.playfellow/endless-sky)
  ENDLESS_SKY_EXE      the game's program (default: looked for under Program Files on drives C to G)

Importing this module also tells the shared widget which game it serves, before the widget module loads.
"""
from __future__ import annotations

import os
from pathlib import Path

from playfellow_coop.games.stk.paths import HOME as _STK_HOME

os.environ.setdefault("PLAYFELLOW_GAME_TITLE", "Endless Sky")
os.environ.setdefault("PLAYFELLOW_GAME_DIR", str(_STK_HOME.parent / "endless-sky"))
GAME_DIR = Path(os.environ["PLAYFELLOW_GAME_DIR"])


def game_exe() -> Path:
    """The installed game's program, or a clearly named missing path."""
    named = os.environ.get("ENDLESS_SKY_EXE")
    if named:
        return Path(named)
    for drive in "CDEFG":
        for folder in ("Program Files", "Program Files (x86)"):
            candidate = Path(f"{drive}:/") / folder / "Endless Sky" / "Endless Sky.exe"
            if candidate.is_file():
                return candidate
    return Path("endless-sky-not-found")
