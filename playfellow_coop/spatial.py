"""A "that way is blocked" note for the planner, from marks alone (the one idea of JEV-Star's failed-option masking that fits here).

The engine's marks legend already says where each thing is from ME ("up-right, far"). What a planner cannot know is that its LAST move
did nothing: the buddy pressed "right", but ME is still where it was, so something is in the way. This keeps the previous position of ME and
the movement keys pressed since, and says so in one plain sentence when ME did not move. Like a driver who notices the car did not move
after pressing the pedal. Numbers come from the marks, never from the model.
"""
from __future__ import annotations

import math

from messages import tr

MOVES = frozenset({"left", "right", "up", "down"})  # direction keys by name; other actions (jump, use, wait) are never judged
MOVED = 8  # grid units (0-1000): ME moving less than this counts as "did not move"


class StuckTracker:
    def __init__(self) -> None:
        self._previous: tuple[int, int] | None = None
        self._tried: list[str] = []

    def note(self, marks) -> str:
        """Call once per turn with this turn's marks (before the planner is asked). Returns the sentence, or "" when there is nothing to say."""
        me = next((m for m in marks if m.kind == "me"), None)
        line = ""
        if me is not None and self._previous is not None and self._tried \
                and math.hypot(me.x - self._previous[0], me.y - self._previous[1]) < MOVED:
            tried = ", ".join(self._tried)
            line = tr(f"Note: your last move ({tried}) did not move you, so something blocks that way. Try a different direction.",
                      f"ملاحظة: حركتك الأخيرة ({tried}) لم تحرّكك، فهناك ما يعيق ذلك الاتجاه. جرّب اتجاهًا آخر.")
        self._previous = (me.x, me.y) if me is not None else None
        self._tried = []
        return line

    def acted(self, action_names) -> None:
        """Call after the turn's keys: remembers which direction keys were pressed."""
        self._tried = [name for name in action_names if name.lower() in MOVES]  # card names may be upper-case (RIGHT)
