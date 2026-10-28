"""The harness assembled: one object the turn loop holds. It owns the session, the long-term memory bank, the identity, and the flow around a skill run."""
from __future__ import annotations

import uuid
from pathlib import Path

from playfellow_coop import sam_marks
from playfellow_coop.harness.flow import DONE, DOOM_LOOP, Flow, LoopGuard
from playfellow_coop.harness.memory_bank import MemoryBank, fact_from_skill
from playfellow_coop.harness.security import Confirmation, Identity, Policy, PrivacyPolicy
from playfellow_coop.harness.state import Session, SessionStore
from playfellow_coop.harness.tools import ToolRegistry

DEFAULT_DIR = Path.home() / ".playfellow-coop" / "harness"
HELP_LINE = "I am stuck, so it is your turn. Press F9 and I will stop pressing keys."
HELP_LINE_AR = "علقتُ، فالدور عليك. اضغط F9 وسأتوقف عن ضغط الأزرار."


class Harness:
    def __init__(self, folder: Path | None = None, game: str = "", player: str = "local", confirm=None, clock_session: str | None = None, goal: str = "",
                 max_iterations: int = 200, max_usd: float | None = None):
        self.folder = Path(folder or DEFAULT_DIR)
        self.game = game
        store = SessionStore(self.folder / "sessions")
        self.session = Session(clock_session or uuid.uuid4().hex[:12], store)
        self.bank = MemoryBank(self.folder / "memory.json")
        self.confirmation = Confirmation(confirm)
        self.policy = Policy(protected={"harness.settings", "harness.memory.clear", "harness.files"})  # the harness's own settings and files are one approval per action, never "always"
        self.tools = ToolRegistry(self.session, self.confirmation, policy=self.policy)
        self.guard = LoopGuard(max_iterations=max_iterations, max_usd=max_usd)  # five ways to end, and the doom-loop stop
        self.turns = 0
        self.progress = 0
        self.privacy = PrivacyPolicy()
        self.identity = Identity("buddy", self.session.id, player)
        self.session.append("note", {"event": "game started", "game": game}, who=self.identity.tag(), delta={"game": game} if game else {})
        if goal:
            self.session.set_goal(goal, "the game is won")

    # ---- context: what the model is shown besides the picture (all fenced data)
    def memory_block(self) -> str:
        return self.bank.context_for(self.game) if self.game else ""

    # ---- tools and flow
    def skill_flow(self, run, grab, stop, retry_limit: int = 1) -> Flow:
        """Act = run the skill. Two checks run at the same time afterwards: the picture changed (the skill really did something), and nobody asked to stop.
        A skill that ended because the game is over counts as done, whatever the picture did."""
        def act(ctx):
            ctx["before"] = sam_marks._signature(_image(grab()))
            result = run()
            ctx["result"] = result
            ctx["after"] = sam_marks._signature(_image(grab()))
            return result

        def picture_changed(ctx):
            return True if sam_marks._changed(ctx["before"], ctx["after"]) else "the picture did not change after the skill ran"

        def not_stopped(ctx):
            return "a stop was requested" if stop() else True

        def game_over(ctx):
            return getattr(ctx.get("result"), "stopped", "") == "game_over"

        return Flow(act, {"picture_changed": picture_changed, "not_stopped": not_stopped}, retry_limit=retry_limit, finished=game_over)

    def unknown_effects_note(self) -> str:
        """After a restart on the same session: actions that were announced but never confirmed. They are reported as unknown, never repeated blindly."""
        pending = self.session.unfinished_intents()
        if not pending:
            return ""
        names = ", ".join(sorted({e.data.get("tool", "?") for e in pending}))[:120]
        return f"Earlier actions were announced but never confirmed ({names}). Check what really happened on the screen before you repeat them."

    # ---- the goal and the loop's brakes
    def reminder(self) -> str:
        """The goal reminder, empty unless the last several turns made no progress."""
        return self.session.probe()

    def turn_done(self, changed: bool, signature=None) -> str | None:
        """Call once per model turn that ran a skill. `changed` says the picture changed (progress); `signature` is whatever should repeat for a doom loop to be called.
        Returns the reason the loop must stop (iteration cap, budget, doom loop), or None."""
        self.turns += 1
        if changed:
            self.progress += 1
        self.session.note_progress(float(self.progress) if changed else None)
        reason = self.guard.check(self.turns, signature=signature)
        if reason:
            self.session.append("note", {"loop_end": reason}, who=self.identity.tag())
        return reason

    # ---- remembering
    def record_skill(self, result, won: bool | None = None) -> None:
        who = Identity(f"skill:{getattr(result, 'skill', 'unknown')}", self.session.id, self.identity.player).tag()
        steps, stopped = getattr(result, "steps", 0), getattr(result, "stopped", "")
        self.session.append("skill", {"name": getattr(result, "skill", ""), "steps": steps, "stopped": stopped}, who=who)
        if self.game:
            topic, text = fact_from_skill(self.game, getattr(result, "skill", "skill"), steps, stopped, won)
            self.bank.add(self.game, topic, text)

    def end_turn(self) -> None:
        self.session.end_turn()


def _image(picture):
    from PIL import Image
    return picture if hasattr(picture, "convert") else Image.fromarray(picture)


__all__ = ["Harness", "HELP_LINE", "HELP_LINE_AR", "DONE"]
