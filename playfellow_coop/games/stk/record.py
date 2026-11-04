"""Screen recording of the game window, the widget included (it sits over the window's top centre and is set to show in
recordings), as its own low-priority process so it never slows the driving loop.

    python -m playfellow_coop.games.stk.record --out recordings/tutorial.mp4 --stop-file <path> [--fps 12]

It also saves a full-size screenshot every --shot-every seconds next to the video. It stops when the stop file appears, the
game window closes, or after --max-seconds. Only the game window's own rectangle is captured, never the rest of the desktop.
"""
from __future__ import annotations

import argparse
import ctypes
import os
import time
from pathlib import Path

import cv2
import numpy as np

from playfellow_coop.games.stk.io import WINDOW_TITLE, GameWindow


def below_normal_priority() -> None:  # pragma: no cover
    try:
        handle = ctypes.windll.kernel32.GetCurrentProcess()
        ctypes.windll.kernel32.SetPriorityClass(handle, 0x00004000)  # BELOW_NORMAL_PRIORITY_CLASS
    except OSError:
        pass


def record(out: Path, stop_file: Path, fps: float = 12.0, max_seconds: float = 1800.0, shot_every: float = 10.0, title: str = WINDOW_TITLE, private: bool = True) -> dict:  # pragma: no cover
    import mss

    below_normal_priority()
    out.parent.mkdir(parents=True, exist_ok=True)
    shots = out.parent / (out.stem + "-shots")
    shots.mkdir(exist_ok=True)
    window = GameWindow(title)
    grabber = mss.MSS() if hasattr(mss, "MSS") else mss.mss()
    x0, y0, x1, y1 = window.client_box()
    size = ((x1 - x0) // 2 * 2, (y1 - y0) // 2 * 2)
    writer = cv2.VideoWriter(str(out), cv2.VideoWriter_fourcc(*"mp4v"), fps, size)
    started, frames, last_shot = time.monotonic(), 0, -shot_every
    try:
        while not stop_file.exists() and time.monotonic() - started < max_seconds:
            t = time.monotonic() - started
            try:
                x0, y0, x1, y1 = window.client_box()
            except Exception:
                break
            if x1 - x0 < 50 or y1 - y0 < 50 or (private and not window.in_front()):  # minimised, or another window may cover the game: never record that
                time.sleep(0.2)
                continue
            img = np.asarray(grabber.grab({"left": x0, "top": y0, "width": x1 - x0, "height": y1 - y0}))[:, :, :3]
            if (img.shape[1], img.shape[0]) != size:
                img = cv2.resize(img, size)
            writer.write(np.ascontiguousarray(img))
            frames += 1
            if t - last_shot >= shot_every:
                last_shot = t
                cv2.imwrite(str(shots / f"{out.stem}-{int(t):04d}s.png"), img)
            time.sleep(max(0.0, (frames / fps) - (time.monotonic() - started)))
    finally:
        writer.release()
    return {"video": str(out), "frames": frames, "seconds": round(time.monotonic() - started, 1)}


def main(argv=None):  # pragma: no cover
    p = argparse.ArgumentParser()
    p.add_argument("--out", required=True)
    p.add_argument("--stop-file", required=True)
    p.add_argument("--fps", type=float, default=12.0)
    p.add_argument("--max-seconds", type=float, default=1800.0)
    p.add_argument("--shot-every", type=float, default=10.0)
    p.add_argument("--title", default=WINDOW_TITLE)
    a = p.parse_args(argv)
    print(record(Path(a.out), Path(a.stop_file), a.fps, a.max_seconds, a.shot_every, a.title))


if __name__ == "__main__":
    main()
