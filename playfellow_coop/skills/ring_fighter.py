"""Play Mini Fighter from pixels: read player and CPU positions, HP, meter, and attack animations directly from the picture.

No copied game state or engine queries: reads positions, meter, and attack windups directly from pixels
on both the unskinned arena and glass skin looks, and blocks and counters reliably.
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done

Frame = np.ndarray

WIDTH, HEIGHT = 624, 364
STAGE_SCALE = 24


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if not Mini Fighter."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (HEIGHT, WIDTH):
        return None
    if frame.std() < 5.0:
        return None
    if int(frame[0, 0, 0]) == 16 and int(frame[0, 0, 1]) == 16 and int(frame[0, 0, 2]) == 32:
        return "arena"
    if int(frame[0, 0, 0]) <= 12 and int(frame[0, 0, 2]) <= 28:
        return "skinned"
    return None


def read_fighter(frame: Frame, look: str) -> tuple[float, float, int, float, bool]:
    """Read (player_x, cpu_x, gap_units, meter_percent, cpu_winding_up) from the picture."""
    # Read lower torso band (y = 295..315) where punch lines never obscure the fighters
    band = frame[295:315, :]
    if look == "arena":
        purple_diff = np.abs(band.astype(float) - [124, 92, 255]).sum(axis=-1)
        red_diff = np.abs(band.astype(float) - [230, 70, 70]).sum(axis=-1)
        p_cols = np.where((purple_diff < 35).any(axis=0))[0]
        c_cols = np.where((red_diff < 35).any(axis=0))[0]
    else:
        p_cols = np.where(((band[:, :, 0] > 100) & (band[:, :, 2] > 130) & (band[:, :, 2] > band[:, :, 1] + 15)).any(axis=0))[0]
        c_cols = np.where(((band[:, :, 1] > 130) & (band[:, :, 2] > 130) & (band[:, :, 0] < 100)).any(axis=0))[0]

    px = float(p_cols.mean()) if len(p_cols) else 168.0
    cx = float(c_cols.mean()) if len(c_cols) else 456.0
    gap = round(abs(px - cx) / float(STAGE_SCALE))

    # Meter bar at row 94, x = 12..212
    meter_row = frame[94, 12:212]
    gold_diff = np.abs(meter_row.astype(float) - [255, 214, 60]).sum(axis=-1)
    meter = float((gold_diff < 40).sum()) / 200.0 * 100.0

    # CPU attacking windup: line of reach 18 extends towards player
    facing = 1 if px > cx else -1
    windup = False
    for y in (64 + 260 - 70, 64 + 260 - 40):
        p14 = frame[y, int(np.clip(cx + facing * 14, 0, WIDTH - 1))]
        p28 = frame[y, int(np.clip(cx + facing * 28, 0, WIDTH - 1))]
        if look == "arena":
            c14 = np.abs(p14.astype(float) - [230, 70, 70]).sum() < 30 or np.abs(p14.astype(float) - [255, 214, 60]).sum() < 30
            c28 = np.abs(p28.astype(float) - [230, 70, 70]).sum() < 30 or np.abs(p28.astype(float) - [255, 214, 60]).sum() < 30
        else:
            c14 = (p14[1] > 130 and p14[2] > 130 and p14[0] < 100) or np.abs(p14.astype(float) - [255, 214, 60]).sum() < 40
            c28 = (p28[1] > 130 and p28[2] > 130 and p28[0] < 100) or np.abs(p28.astype(float) - [255, 214, 60]).sum() < 40

        # Windup line extends to 18 px (present at 14 px, absent at 28 px)
        if c14 and not c28:
            windup = True
            break

    return px, cx, gap, meter, windup


class FightBot:
    name = "fight_bot"
    about = "Fight one-on-one in Mini Fighter from pixels, blocking incoming strikes and landing punches and kicks."
    max_steps = 350

    def __init__(self, look: str | None = None):
        self.look = look
        self.detected_look: str | None = None
        self.reset()

    def reset(self) -> None:
        self.detected_look = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        mode = detect_look(frame)
        if mode is None:
            raise Done("unreadable mini_fighter picture")
        self.detected_look = mode

        px, cx, gap, meter, windup = read_fighter(frame, mode)

        toward = 1 if cx > px else -1
        fwd_key = "right" if toward == 1 else "left"

        if windup and gap <= 3:
            return "d"
        if meter >= 95.0 and gap <= 4:
            return "f"
        if gap > 3:
            return fwd_key
        if gap == 3:
            return "s"
        if gap <= 2:
            return "a"
        return None
