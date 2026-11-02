"""The pace rule for games that run on their own clock.

A real-time game does not wait while the model looks and thinks (about 2.5 s a turn on 2 Nov 2026). With one move per turn, the
player stands still between moves; the owner's live run showed exactly that, 31 of 31 turns choosing one action though the engine
allows more. So for real-time genres the planner is asked for a short sequence that carries the player until the next look, and, when
the game has a run skill, to hand open stretches to it (the skill plays at local speed). Turn-based and unknown genres get nothing."""
from __future__ import annotations

REALTIME_GENRES = frozenset({"platformer", "metroidvania", "endless_runner", "arcade", "action_rpg", "fighting", "first_person", "fps",
                             "racing", "top_down", "maze"})


def pace_rule(card, max_actions: int, skills: tuple[str, ...] = ()) -> str:
    if str(getattr(card, "genre", "")).lower() not in REALTIME_GENRES or int(max_actions) < 2:
        return ""
    low = min(3, int(max_actions))
    text = (f"\n\nThis game runs in real time: it does not wait while you look and think. Every turn, choose {low} to {int(max_actions)} "
            "actions in the order they should happen, so the player keeps moving until your next look (for example run, jump, run), "
            "never just one, unless you must wait or a menu is open.")
    if skills:
        text += (f" To cross an open stretch of level, choose the skill \"{skills[0]}\": it runs, jumps and attacks on its own at local "
                 "speed, and gives control back after a few seconds so you can look again.")
    return text
