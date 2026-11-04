"""The models' part in the SuperTuxKart pack, with the app's own spending cap and key handling.

The key comes from the environment (MODEL_API_KEY), the credential manager, or a key file given by path; it is read into
memory only and never printed or written anywhere. Every call goes through DailyBudget, which stops a call before it is sent
once the cap is reached, and is appended to a call log beside the run.
"""
from __future__ import annotations

import json
import os
import time
from pathlib import Path

import numpy as np

from playfellow_coop.budget import DailyBudget


def load_key(key_file: Path | None = None) -> str | None:
    from playfellow_coop.__main__ import load_muse_key

    key = load_muse_key()
    if key:
        return key
    if key_file is not None and Path(key_file).exists():
        text = Path(key_file).read_text(encoding="utf-8").strip()
        return text or None
    return None


def muse_menu_eye(key: str, budget_file: Path, cap_usd: float, call_log: Path | None = None, effort: str = "minimal", width: int = 640):
    """`ask(screenshot_bgr, text) -> answer` for the menu Navigator: a small screenshot to Muse with the menu prompt."""
    import cv2
    from PIL import Image

    from playfellow_coop.games.stk.menus import SYSTEM as MENU_SYSTEM
    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

    brain = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(budget_file, cap_usd, 20000), effort=effort, cache_key=None)
    brain.max_tokens = 1000

    def ask(frame: np.ndarray, text: str) -> str:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (width, int(h * width / w)), interpolation=cv2.INTER_AREA)
        answer = brain.ask(MENU_SYSTEM, text, [Image.fromarray(np.ascontiguousarray(small[:, :, ::-1]))])
        if call_log is not None:
            with open(call_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "purpose": "menu_step", **(brain.last_request or {}),
                                     "answer": answer[:300]}) + "\n")
        return answer

    return ask


RESULTS_SYSTEM = ("You see the end of a SuperTuxKart race. Reply with JSON only: {\"screen\": short name, \"results_shown\": true if a "
                  "results or standings table is visible, \"player_position\": the finishing position of the human player's kart (the "
                  "row marked as the player, usually highlighted, or the player's name) as a number, or null, \"rows\": the table rows "
                  "as short strings, top to bottom}.")


def muse_results_reader(key: str, budget_file: Path, cap_usd: float, call_log: Path | None = None):
    """`read(frame_bgr) -> dict` for the results screen: who finished where, read off the game's own table."""
    import re

    import cv2
    from PIL import Image

    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

    brain = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(budget_file, cap_usd, 20000), effort="low", cache_key=None)
    brain.max_tokens = 1500

    def read(frame: np.ndarray, player_name: str = "") -> dict:
        h, w = frame.shape[:2]
        small = cv2.resize(frame, (800, int(h * 800 / w)), interpolation=cv2.INTER_AREA)
        hint = f"The player's name is {player_name!r}. " if player_name else ""
        answer = brain.ask(RESULTS_SYSTEM, hint + "Read the results.", [Image.fromarray(np.ascontiguousarray(small[:, :, ::-1]))])
        if call_log is not None:
            with open(call_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "purpose": "results", **(brain.last_request or {}),
                                     "answer": answer[:600]}) + "\n")
        m = re.search(r"\{.*\}", answer, re.S)
        try:
            return json.loads(m.group(0)) if m else {}
        except ValueError:
            return {}

    return read


def muse_label_reader(key: str, budget_file: Path, cap_usd: float, call_log: Path | None = None):
    """`read(crop_bgr) -> label text` (the main menu's bar tooltip) on Muse, '' when unreadable."""
    import re

    import cv2
    from PIL import Image

    from playfellow_coop.games.stk.menus import LABEL_SYSTEM
    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

    brain = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(budget_file, cap_usd, 20000), effort="minimal", cache_key=None)
    brain.max_tokens = 600

    def read(crop: np.ndarray) -> str:
        big = cv2.resize(crop, None, fx=1.5, fy=1.5, interpolation=cv2.INTER_CUBIC)
        answer = brain.ask(LABEL_SYSTEM, "Read the tooltip label.", [Image.fromarray(np.ascontiguousarray(big[:, :, ::-1]))])
        if call_log is not None:
            with open(call_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "purpose": "bar_label", **(brain.last_request or {}),
                                     "answer": answer[:200]}) + "\n")
        m = re.search(r'"label"\s*:\s*"([^"]*)"', answer)
        return m.group(1) if m else ""

    return read


def muse_reader(key: str, budget_file: Path, cap_usd: float, call_log: Path | None = None, effort: str = "minimal"):
    """`ask(strip_bgr) -> answer` for the instruction Reader, on Muse with a spending cap."""
    from PIL import Image

    from playfellow_coop.games.stk.instructions import SYSTEM
    from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain

    brain = MuseBrain(DEFAULT_MODEL, key, budget=DailyBudget(budget_file, cap_usd, 20000), effort=effort, cache_key=None)
    brain.max_tokens = 1000

    def ask(strip: np.ndarray) -> str:
        picture = Image.fromarray(np.ascontiguousarray(strip[:, :, ::-1]))
        answer = brain.ask(SYSTEM, "Read the message box and return the JSON.", [picture])
        if call_log is not None:
            with open(call_log, "a", encoding="utf-8") as fh:
                fh.write(json.dumps({"at": time.strftime("%Y-%m-%dT%H:%M:%S%z"), "purpose": "read_instruction", **(brain.last_request or {}),
                                     "answer": answer[:300]}) + "\n")
        return answer

    return ask
