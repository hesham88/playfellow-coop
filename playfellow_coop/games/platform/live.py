"""Runs the platformer skill on a real game window, through the same guarded door as the racing pack: keys only while the game is in
front, only the allowed keys, never the mouse, every key released at the end. F12 stops it, F9 hands over, the widget says what it does.

    python -m playfellow_coop.games.platform.live --title "<game window title>" --seconds 120 --sprint <key>
"""
from __future__ import annotations

import argparse
import json
import time
from pathlib import Path

import numpy as np

from playfellow_coop.games.platform.runner import Keys, Runner
from playfellow_coop.games.stk.io import GameWindow
from playfellow_coop.games.stk.paths import HOME
from playfellow_coop.games.stk.widget import HANDOVER, STOP, say_line, set_status

VK_F12 = 0x7B


def run(title: str, seconds: float, keys: Keys, out: Path, hz: float = 15.0) -> dict:  # pragma: no cover - needs a real desktop
    import mss

    out.mkdir(parents=True, exist_ok=True)
    window = GameWindow(title)
    if not window.focus():
        raise RuntimeError("the game window could not be brought to the front; nothing was pressed")
    allowed = frozenset(k for k in (keys.left, keys.right, keys.jump, keys.attack, keys.sprint) if k)
    hands, runner = window.hands(allowed), Runner(keys)
    grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
    set_status(f"playing {title}: running, jumping and reading the picture.")
    say_line(f"Playing {title}. F12 stops me, F9 hands over.")
    started, stopped_by = time.monotonic(), "time"
    try:
        while time.monotonic() - started < seconds:
            tick_start = time.monotonic()
            if window.key_is_down(VK_F12) or STOP.exists():
                stopped_by = "stop"
                break
            if not window.user32.IsWindow(window.hwnd):
                stopped_by = "game_closed"
                break
            if HANDOVER.exists() or not window.in_front():
                hands.release_all()
                time.sleep(0.1)
                continue
            x0, y0, x1, y1 = window.client_box()
            if x1 - x0 < 64 or y1 - y0 < 64:
                time.sleep(0.2)
                continue
            frame = np.asarray(grabber.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3].copy()
            hands.hold_only(runner.step(frame))
            time.sleep(max(0.0, 1.0 / hz - (time.monotonic() - tick_start)))
    finally:
        hands.release_all()
        set_status("not playing: nothing is pressed.")
    result = {"title": title, "stopped_by": stopped_by, "seconds": round(time.monotonic() - started, 1), "deaths": runner.deaths,
              "furthest_view_widths": round(runner.world.furthest, 2), "rooms": len(runner.world.seen), "blocked_ways": len(runner.world.blocked),
              "key_events": len(hands.audit), "refused_sends": hands.refused}
    (out / "run.json").write_text(json.dumps({"result": result, "log": runner.log[-2000:]}), encoding="utf-8")
    say_line(f"Run over ({stopped_by}): {result['furthest_view_widths']} view-widths, {result['deaths']} deaths, {result['rooms']} rooms.")
    return result


def main(argv=None) -> None:  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--title", required=True)
    p.add_argument("--seconds", type=float, default=120.0)
    p.add_argument("--jump", default="space")
    p.add_argument("--attack", default="s")
    p.add_argument("--sprint", default="shift", help="Rayman Legends' default sprint key is Left Shift (4 Nov research)")
    p.add_argument("--out", default=str(HOME.parent / "platform" / "runs" / time.strftime("%Y%m%d-%H%M%S")))
    a = p.parse_args(argv)
    print(json.dumps(run(a.title, a.seconds, Keys(jump=a.jump, attack=a.attack, sprint=a.sprint), Path(a.out))))


if __name__ == "__main__":
    main()
