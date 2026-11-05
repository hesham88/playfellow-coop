"""Game actions the widget's brain can carry out when the player asks: back to the menu, restart, start a race.

    python -m playfellow_coop.games.stk.act menu | restart | race <difficulty>

Each one goes through the same guarded keyboard as everything else (only the game window, only menu keys) and says its
steps on the widget's bar. A race starts a full session (play.py): difficulty set by sight, rocket start, recording.
"""
from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

from playfellow_coop.games.stk.paths import BUDGET, CALLS, KEY_FILE


def navigator():  # pragma: no cover - needs the game
    import mss
    import numpy as np

    from playfellow_coop.games.stk.brains import load_key, muse_menu_eye
    from playfellow_coop.games.stk.io import GameWindow, MENU_KEYS
    from playfellow_coop.games.stk.menus import Navigator
    from playfellow_coop.games.stk.widget import say_line

    window = GameWindow()
    grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()

    def look():
        window.focus()
        x0, y0, x1, y1 = window.client_box()
        image = np.asarray(grabber.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3].copy()
        image[0:64, max((image.shape[1] - 580) // 2, 0):(image.shape[1] + 580) // 2] = 0  # the widget's own words
        return image

    def press(key: str) -> bool:
        if not window.in_front():
            window.focus()
        return window.hands(MENU_KEYS).tap(key)

    ask = muse_menu_eye(load_key(KEY_FILE), BUDGET, 30.0, CALLS)
    return Navigator(look=look, ask=ask, press=press, say=say_line), say_line


def main(argv=None) -> None:  # pragma: no cover
    argv = list(sys.argv[1:] if argv is None else argv)
    what = argv[0] if argv else "menu"
    if what == "race":
        difficulty = argv[1] if len(argv) > 1 else "intermediate"
        subprocess.Popen([sys.executable, "-m", "playfellow_coop.games.stk.mission", "--mission", "race", "--difficulty", difficulty],
                         creationflags=0x08000000 | 0x00000200)
        return
    if what == "press":  # the player asked for keys: press them now, say each one
        from playfellow_coop.games.stk.io import GameWindow, MENU_KEYS
        from playfellow_coop.games.stk.widget import say_line

        window = GameWindow()
        window.focus()
        hands = window.hands(MENU_KEYS)
        for key in argv[1:] or ["enter"]:
            if not window.in_front():
                window.focus()
            ok = hands.tap(key)
            say_line(f"Pressed {key}." if ok else f"Could not press {key}: the game is not in front.")
            time.sleep(0.4)
        return
    nav, say = navigator()
    from playfellow_coop.games.stk.widget import set_status

    if what == "goal":
        goal = " ".join(argv[1:]) or "the main menu"
        set_status(f"in the menus: {goal} (each step is shown here).")
        ok = nav.reach(f"{goal}. Done (press none) when that is on screen.", max_steps=10)
        say(f"Done: {goal}." if ok else f"I couldn't get to: {goal}. Nothing else was pressed.")
    elif what == "menu":
        set_status("going back to the main menu (each step is shown here).")
        ok = nav.reach("Go back to the main menu: on a results screen choose 'Back to the menu', on a Paused menu choose "
                       "'Back to menu' / 'Exit Race', on other screens press esc. Done (press none) when the main menu with the "
                       "Story Mode / Singleplayer / Splitscreen tiles is on screen.", max_steps=10)
        say("I'm at the main menu." if ok else "I couldn't get back to the main menu; nothing else was pressed.")
    elif what == "restart":
        set_status("restarting the race (each step is shown here).")
        ok = nav.reach("Restart this race: on a results screen choose 'Restart'; during a race press esc and choose "
                       "'Restart Race'. Done (press none) when the race is loading or the countdown is on.", max_steps=8)
        say("Race restarted." if ok else "I couldn't restart the race; nothing else was pressed.")
    set_status("not driving: waiting for your next command; nothing is pressed.")
    time.sleep(0.5)


if __name__ == "__main__":
    main()
