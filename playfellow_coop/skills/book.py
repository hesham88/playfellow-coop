"""A skill book: the skills one game offers, how the model is told about them, and how a chosen skill is run through the session's own hands."""
from __future__ import annotations

import time
from typing import Callable

from playfellow_coop.skills.base import SkillResult, make_settle, run_skill
from playfellow_coop.skills.registry import SKILLS

NONE = "none"  # the model's answer when it wants to press keys itself this turn


class SkillBook:
    def __init__(self, game_key: str, looks=None):
        if game_key not in SKILLS:
            raise KeyError(f"no skills for game {game_key!r}")
        self.game_key = game_key
        self.looks = list(looks or [])  # other ways this game may be drawn (re-skins), tried in order after the plain look
        self.look_name = "arena"
        self.skill = SKILLS[game_key]()
        self.last: SkillResult | None = None
        self.native_size: tuple[int, int] | None = None  # (width, height) of the picture the skill was proven to read; a resized window is scaled back to this
        self.blind_runs = 0  # runs that ended before a single key: the skill cannot see this game any more

    def readable(self, picture) -> bool:
        """Can a skill read this game's picture? Tries the plain look, then each known re-skin; the first look the skill can read with is kept (`look_name`).
        A skill that cannot see must not be offered to the model: False when no look works."""
        from playfellow_coop.skills.base import Done, as_frame
        frame = as_frame(picture)
        if self.native_size is not None and (frame.shape[1], frame.shape[0]) != self.native_size:
            from playfellow_coop.universal.frames import resize
            frame = resize(frame, *self.native_size)  # a resized window: judge it at the size the skill was proven on
        for look in [None] + self.looks:
            candidate = SKILLS[self.game_key](look) if look is not None else SKILLS[self.game_key]()
            candidate.reset()
            try:
                candidate.next_key(frame)
            except Done:
                continue
            except Exception:
                continue
            self.skill, self.look_name = candidate, (look.name if look is not None else "arena")
            self.native_size = (frame.shape[1], frame.shape[0])
            return True
        return False

    @property
    def names(self) -> tuple[str, ...]:
        return (self.skill.name, NONE)

    def system_text(self) -> str:
        """The paragraph added to the buddy's instructions. It says what a skill is, so the model chooses instead of guessing keys."""
        return (f"\n\nSKILLS. You may start a skill instead of pressing keys. A skill reads the picture itself and presses many keys on its own, so use one "
                f"whenever it fits. Skill \"{self.skill.name}\": {self.skill.about} To use it, answer with \"skill\": \"{self.skill.name}\" and an empty "
                f"\"actions\" list. Answer \"skill\": \"{NONE}\" to press keys yourself this turn. After the skill stops, you see the picture again and choose again.")

    def run(self, name: str, parts, box, stop: Callable[[], bool], max_steps: int | None = None) -> SkillResult | None:
        """Run the named skill with the session's own screen and hands. None when the name is not one of this book's skills."""
        if name != self.skill.name:
            return None
        card = parts.card
        by_key: dict[str, str] = {}
        wait_action = None
        for action_name, action in card.actions.items():
            keys = getattr(action, "keys", None)
            if getattr(action, "kind", "keys") == "keys" and keys and len(keys) == 1:
                by_key.setdefault(keys[0], action_name)
            elif getattr(action, "kind", "") == "wait" and wait_action is None:
                wait_action = action_name
        from reply import Step

        live_realtime = getattr(self.skill, "realtime", False) and getattr(parts, "wait_for_ticks", False)

        def press(key):
            if parts.safety.stopped:
                return
            if key is None:
                if live_realtime:
                    return  # the game moves on its own clock and the next step waits for its tick anyway: nothing to press, nothing to wait for here
                if wait_action is not None:
                    parts.hands.do(Step(wait_action), box)
                else:
                    getattr(parts, "skill_idle", lambda: time.sleep(0.05))()
                return
            parts.hands.do(Step(by_key[key]), box)

        grab = self._grab(parts, box)
        # a real-time game moves on its own clock: in a live session (the window or the in-app game) each step waits for the picture to move; the offline benchmark steps the game itself
        settle = make_settle(grab) if getattr(self.skill, "realtime", False) and getattr(parts, "wait_for_ticks", False) else None
        self.skill.live = live_realtime  # a skill may skip a key that changes nothing, but only when the game's own clock moves it
        if settle is not None:
            waited = settle

            def settle(before, _waited=waited):  # noqa: F811 - the same wait, plus one lesson from it
                moved = _waited(before)
                if moved is False:
                    self.skill.live = False  # nothing moved without a key: this game advances on key presses, so every step presses again
                return moved
        result = run_skill(self.skill, grab, press, stop, set(by_key), max_steps=max_steps, settle=settle)
        self.last = result
        self.blind_runs = self.blind_runs + 1 if result.steps == 0 and result.stopped.startswith("done") else 0
        return result

    def _grab(self, parts, box):
        """The session's screen grab, scaled back to the picture size the skill was proven on, so a resized window or another display scale does not blind it."""
        def grab():
            picture = parts.screen.grab(box)
            if self.native_size is None:
                return picture
            from playfellow_coop.universal.frames import resize, to_rgb
            frame = to_rgb(picture)
            width, height = self.native_size
            return frame if (frame.shape[1], frame.shape[0]) == (width, height) else resize(frame, width, height)
        return grab
