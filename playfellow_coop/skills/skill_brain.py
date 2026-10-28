"""A brain wrapper that lets ANY brain use skills, without touching the engine's loop.

The engine's play loop asks a brain for a plan and presses the keys of the reply. `SkillBrain` sits around the real brain: it adds the skills paragraph to the instructions, and when the
real brain answers with `"skill": "<name>"` it runs that skill itself, with the screen and hands the session already has (a real window, or the virtual screen of the in-app games), then
hands the loop an empty plan with the brain's own words. Every other answer passes through untouched. The skill reads pictures only, presses only keys of the controls card, and
stops at once when `stop()` says so (F12, the player taking over, the window leaving the front).
"""
from __future__ import annotations

import json
from types import SimpleNamespace
from typing import Callable

from playfellow_coop.skills.book import NONE, SkillBook


def chosen_skill(raw: str) -> str | None:
    """The skill name in a brain's JSON answer, or None."""
    from reply import extract_json
    data = extract_json(raw)
    name = data.get("skill") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


class SkillBrain:
    def __init__(self, inner, book: SkillBook, screen, hands, card, window: str = "", stop: Callable[[], bool] = lambda: False, on_event: Callable | None = None,
                 max_steps: int | None = None):
        self.inner, self.book, self.screen, self.hands, self.card = inner, book, screen, hands, card
        self.window, self.stop, self.on_event, self.max_steps = window, stop, on_event or (lambda kind, data: None), max_steps
        self.last_skill = None  # the SkillResult of the last run, for the window and the tests
        if hasattr(inner, "set_skills"):
            inner.set_skills(book.names)  # a strict-schema brain may then answer with the skill enum

    def __getattr__(self, name):  # model, last_request, last_timings, set_actions, close ...: all the inner brain's
        return getattr(self.inner, name)

    def ask(self, system: str, text: str, images: list) -> str:
        raw = self.inner.ask(system + self.book.system_text(), text, images)
        name = chosen_skill(raw)
        if name in (None, NONE) or name != self.book.skill.name:
            return raw
        box = self.screen.find(self.window)
        parts = SimpleNamespace(card=self.card, screen=self.screen, hands=self.hands, safety=SimpleNamespace(stopped=False), wait_for_ticks=True)
        result = self.book.run(name, parts, box, self.stop, max_steps=self.max_steps)
        self.last_skill = result
        if result is not None:
            self.on_event("skill", {"name": name, "steps": result.steps, "stopped": result.stopped})
        try:
            words = json.loads(raw)
            thought, say = str(words.get("thought", ""))[:200], str(words.get("say", ""))[:140]
        except (ValueError, AttributeError):
            thought, say = "", ""
        return json.dumps({"thought": thought or f"I used my {name} skill.", "say": say, "actions": []})
