"""The overlay's live check, for the owner at the keyboard (about 5 minutes): `python demo/overlay_live_check.py`

What it does, in order:
  1. waits until the game window you named is the foreground window;
  2. shows the pinned pill, then opens and closes the panel 50 times, counting every time the foreground window stopped being the game;
  3. with the panel open, takes a screen capture and counts how many pixels changed inside the panel's rectangle compared with a
     capture taken with the panel closed (0 means the panel is invisible to our own capture);
  4. writes both numbers, and what it could not measure, to a small results file. It never says PASS: the numbers speak.

It presses no game key and sends nothing over the network. Do not touch the keyboard or mouse while it runs (about 20 seconds).
The game must be windowed or borderless; true exclusive full screen cannot show any overlay, and the script says so if Windows reports it."""
from __future__ import annotations

import argparse
import ctypes
import json
import sys
import time
from datetime import datetime
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from playfellow_coop.overlay import winstyle  # noqa: E402
from playfellow_coop.overlay.panel import PanelModel  # noqa: E402
from playfellow_coop.overlay.spike import capture_check, measure_focus_loss  # noqa: E402
from playfellow_coop.overlay.tk_view import TkOverlay  # noqa: E402
from playfellow_coop.voice import CommandQueue  # noqa: E402

user32 = ctypes.windll.user32


def foreground() -> int:
    return int(user32.GetForegroundWindow() or 0)


def find_game(title: str) -> int:
    return int(user32.FindWindowW(None, title) or 0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    parser.add_argument("--game-title", default="PlayFellow Practice Arena")
    parser.add_argument("--opens", type=int, default=50)
    parser.add_argument("--dry-run", action="store_true",
                        help="rehearse over a plain window this script opens itself: no game needed, only the panel's own rectangle is looked at")
    parser.add_argument("--out", type=Path, default=Path(__file__).resolve().parents[1] / "results")
    args = parser.parse_args(argv)

    host = None
    if args.dry_run:
        import tkinter as tk

        host = tk.Tk()  # a plain window of our own stands in for the game
        host.title("overlay dry run (stand-in for the game)")
        host.geometry("640x420+120+120")
        host.update()
        host.focus_force()
        host.update()
        time.sleep(0.3)
        host.update()
        game = int(user32.GetParent(host.winfo_id()) or host.winfo_id())
        if foreground() != game:
            print("Windows would not let the stand-in window take the foreground (another program holds it); the focus numbers below "
                  "are measured against whatever was in front.")
            game = foreground()
        args.game_title = "dry run: " + args.game_title
    else:
        game = find_game(args.game_title)
        if not game:
            print(f"I can't find a window called {args.game_title!r}. Open the game first (borderless or windowed), then run this again.")
            return 2
        print("Click the game window now. Waiting until it is in front... (Ctrl+C stops)")
        while foreground() != game:
            time.sleep(0.2)
        print("The game is in front. Starting in 3 seconds: please do not touch the keyboard or the mouse.")
        time.sleep(3)

    state = winstyle.full_screen_state()
    model = PanelModel(CommandQueue())
    overlay = TkOverlay(model, root=__import__("tkinter").Toplevel(host) if host is not None else None)
    overlay.start()
    root = overlay.root

    def settle():
        root.update()
        time.sleep(0.05)
        root.update()

    settle()
    focus = measure_focus_loss(args.opens, model.toggle, foreground, settle)
    model.hide()
    settle()
    # the panel's rectangle on the screen, taken while it is open
    model.show()
    settle()
    rect = (root.winfo_rootx(), root.winfo_rooty(), root.winfo_rootx() + root.winfo_width(), root.winfo_rooty() + root.winfo_height())
    model.hide()
    settle()

    from PIL import ImageGrab

    width, height = rect[2] - rect[0], rect[3] - rect[1]
    # only the panel's own rectangle is captured, kept in memory and compared; nothing from the screen is ever saved
    pixels = capture_check(lambda: ImageGrab.grab(bbox=rect, all_screens=True), model.show, model.hide, (0, 0, width, height), settle)
    hwnd_style = overlay.applied
    result = {
        "tool": "overlay_live_check", "dry_run": bool(args.dry_run), "started": datetime.now().astimezone().isoformat(timespec="seconds"),
        "game_title": args.game_title, "windows_full_screen_state": state,
        "focus": {"opens": focus.opens, "focus_losses": focus.focus_losses, "game_window_was_foreground_at_start": focus.foreground_before == game},
        "capture": {"panel_pixels_found_in_capture": pixels, "rectangle": list(rect),
                    "note": "0 means the panel is absent from this capture; the game keeps moving, so a small count can be the game itself"},
        "style": {"excluded_from_capture": getattr(hwnd_style, "excluded_from_capture", "not measured"),
                  "click_through_when_pinned": model.click_through},
        "not_measured": ["F12 with the panel open (press F12 yourself while the engine runs)", "dropped keys in a fast game (watch the game)"],
    }
    args.out.mkdir(parents=True, exist_ok=True)
    path = args.out / f"overlay_live_check-{datetime.now():%Y%m%d-%H%M%S}.json"
    path.write_text(json.dumps(result, indent=2), encoding="utf-8")
    overlay.close()
    if host is not None:
        host.destroy()
    print(json.dumps(result["focus"]), json.dumps(result["capture"]), sep="\n")
    print(f"Saved: {path}")
    if state == "exclusive":
        print("Windows says this game is in true exclusive full screen: no overlay can be drawn over it. Switch the game to borderless.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
