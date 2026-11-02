"""Play Turn Quest from pixels: read menus, selected row, foe presence and HP/MP bars directly from the picture.

No copied game maps or state: reads everything from pixels on both the unskinned arena and glass skin looks.
"""
from __future__ import annotations

import numpy as np

from playfellow_coop.skills.base import Done

Frame = np.ndarray


def detect_look(frame: Frame) -> str | None:
    """Return 'arena' for the plain look, 'skinned' for the glass skin, or None if not Turn Quest."""
    if not isinstance(frame, np.ndarray) or frame.ndim != 3 or frame.shape[:2] != (424, 560):
        return None
    if frame.std() < 5.0:
        return None
    if int(frame[0, 0, 0]) == 16 and int(frame[0, 0, 1]) == 16 and int(frame[0, 0, 2]) == 32:
        return "arena"
    if int(frame[0, 0, 0]) <= 10 and int(frame[0, 0, 2]) <= 30:
        return "skinned"
    return None


def read_turn_quest(frame: Frame) -> tuple[str, str, str | None, int, int, float, float] | None:
    """Read (mode, screen, enemy_kind, cursor, num_options, hp_ratio, mp_ratio) from the picture."""
    mode = detect_look(frame)
    if mode is None:
        return None

    # HP bar: row 228, x from 20 to 220 (length 200)
    hp_mask = (frame[228, 20:220, 1] > 200) & (frame[228, 20:220, 0] < 120) & (frame[228, 20:220, 2] < 150)
    hp_ratio = float(hp_mask.sum()) / 200.0

    # MP bar: row 244, x from 20 to 220 (length 200)
    mp_mask = (frame[244, 20:220, 2] > 240) & (frame[244, 20:220, 1] > 200) & (frame[244, 20:220, 0] < 60)
    mp_ratio = float(mp_mask.sum()) / 200.0

    # Battle check: enemy health bar at y=113, x=30 is red (230, 70, 70)
    is_battle = bool((int(frame[113, 30, 0]) > 180) and (int(frame[113, 30, 1]) < 100))
    if is_battle:
        screen = "battle"
        enemy_kind = "slime" if int(frame[154, 280, 1]) >= 120 else "dragon"
        num_options = 4
    else:
        enemy_kind = None
        # In shop: 3 options, row 3 (y=366..386, x=26..150) is empty background
        bg_col = frame[376, 18]
        diff = float(np.max(np.abs(frame[366:386, 26:150].astype(int) - bg_col.astype(int))))
        if diff < 50.0:
            screen = "shop"
            num_options = 3
        else:
            screen = "town"
            num_options = 4

    cursor = 0
    for i in range(num_options):
        y = 64 + 200 + i * 34
        col = frame[y + 10, 18]
        if int(col[2]) > 100 and int(col[0]) > 60:
            cursor = i
            break

    return mode, screen, enemy_kind, cursor, num_options, hp_ratio, mp_ratio


class BattleHero:
    name = "battle_hero"
    about = "Navigate menus, grind slimes, buy gear, rest at the inn, and defeat the dragon in Turn Quest from pixels."
    max_steps = 200

    def __init__(self, look: str | None = None):
        self.look = look
        self.detected_look: str | None = None
        self.reset()

    def reset(self) -> None:
        self.detected_look = None
        self.slimes = 0
        self.gold = 0
        self.potions = 1
        self.sword = False
        self.in_battle = False
        self.battle_kind: str | None = None

    def detect_look(self, frame: Frame) -> str | None:
        return detect_look(frame)

    def next_key(self, frame: Frame) -> str | None:
        parsed = read_turn_quest(frame)
        if parsed is None:
            raise Done("unreadable turn_quest picture")

        mode, screen, enemy_kind, cursor, num_options, hp_ratio, mp_ratio = parsed
        self.detected_look = mode

        prev_battle = self.in_battle
        self.in_battle = (screen == "battle")
        if prev_battle and not self.in_battle and self.battle_kind == "slime":
            self.slimes += 1
            self.gold += 8
        if self.in_battle:
            self.battle_kind = enemy_kind

        if screen == "town":
            if hp_ratio < 0.6 and self.gold >= 10:
                tgt = 2
            elif not self.sword and self.gold >= 40:
                tgt = 1
            elif self.sword and self.potions < 3 and self.gold >= 20:
                tgt = 1
            elif self.slimes >= 10 and self.sword and self.potions >= 2 and hp_ratio >= 0.98:
                tgt = 3
            else:
                tgt = 0
        elif screen == "shop":
            if not self.sword and self.gold >= 40:
                tgt = 1
            elif self.sword and self.potions < 3 and self.gold >= 10:
                tgt = 0
            else:
                tgt = 2
        elif screen == "battle":
            if hp_ratio < 0.4 and self.potions > 0:
                tgt = 2
            elif enemy_kind == "dragon" and mp_ratio >= 0.27:
                tgt = 1
            else:
                tgt = 0
        else:
            tgt = 0

        if cursor == tgt:
            act = "enter"
            if screen == "town" and tgt == 2:
                self.gold -= 10
            elif screen == "shop":
                if tgt == 1:
                    self.sword = True
                    self.gold -= 40
                elif tgt == 0:
                    self.potions += 1
                    self.gold -= 10
            elif screen == "battle" and tgt == 2:
                self.potions -= 1
        elif (tgt - cursor) % num_options <= num_options // 2:
            act = "down"
        else:
            act = "up"

        return act
