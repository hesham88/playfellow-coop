"""Where the SuperTuxKart pack keeps its things on this PC: nothing machine-specific is written in the code.

  PLAYFELLOW_STK_HOME        the pack's working folder: recordings, learned notes, the widget's feed (default ~/.playfellow/stk)
  PLAYFELLOW_ASSETS          the crew's art, for the character beside the widget (optional; without it the bar runs alone)
  PLAYFELLOW_MODEL_KEY_FILE  a file holding the model key, read in memory only (optional: the key may also come from the
                             environment or the credential manager, see brains.load_key)
  SUPERTUXKART_DATA          the game's data folder (default: looked for under Program Files)
"""
from __future__ import annotations

import os
import re
from pathlib import Path

HOME = Path(os.environ.get("PLAYFELLOW_STK_HOME") or Path.home() / ".playfellow" / "stk")
ASSETS = Path(os.environ.get("PLAYFELLOW_ASSETS") or HOME / "assets")
KEY_FILE = Path(os.environ["PLAYFELLOW_MODEL_KEY_FILE"]) if os.environ.get("PLAYFELLOW_MODEL_KEY_FILE") else None
BUDGET = HOME / "model-budget.json"
VOICE_BUDGET = HOME / "voice-budget.json"
CALLS = HOME / "model-calls.jsonl"
SESSIONS = HOME / "sessions"
PRESKILLS = HOME / "preskills"


def game_data() -> Path:
    """The installed game's data folder."""
    named = os.environ.get("SUPERTUXKART_DATA")
    if named:
        return Path(named)
    for drive in "CDEFG":
        for folder in ("Program Files", "Program Files (x86)"):
            base = Path(f"{drive}:/") / folder
            try:
                found = sorted(base.glob("SuperTuxKart*/data"))
            except OSError:
                continue
            if found:
                return found[-1]
    return Path("supertuxkart-data-not-found")


def kart_info(kart: str, data: Path | None = None) -> dict:
    """A kart's class and minimap icon file, read from its kart.xml (heavy karts: 5% more top speed, wider turns)."""
    folder = (data or game_data()) / "karts" / kart
    try:
        text = (folder / "kart.xml").read_text(encoding="utf-8", errors="replace")
    except OSError:
        return {}
    def attr(name: str) -> str:
        m = re.search(rf'\b{name}\s*=\s*"([^"]*)"', text)
        return m.group(1) if m else ""
    icon = attr("minimap-icon-file") or attr("icon-file")
    return {"name": attr("name"), "class": attr("type") or "medium", "icon": folder / icon if icon else None}


def player_name() -> str:
    """The game's own player profile (its row is marked by name on the results table), or empty."""
    try:
        text = (Path.home() / "AppData" / "Roaming" / "supertuxkart" / "config-0.10" / "players.xml").read_text(encoding="utf-8")
    except OSError:
        return ""
    match = re.search(r'<player name="([^"]+)" guest="false"', text)
    return match.group(1) if match else ""
