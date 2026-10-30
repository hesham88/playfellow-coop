"""The agent ADK's evaluator runs (it looks for `root_agent` in a module whose name ends in `.agent`).

Each user message names an arena game and a seed ("Play snake, seed 3."). The agent calls one tool, `start_skill` with the skill it chose (the event ADK's
tool-trajectory score reads), plays that skill to the end on the gym from pixels, returns the tool's result (won, steps), and answers in one sentence ("I won
snake." or "I lost snake."). The chooser is the game's own skill (the scripted chooser of our benchmark rows); PF_ADK_CHOOSER=random picks among all five
skills instead, a control that must score lower. Imported only by ADK's evaluator in the ADK environment (AD1), never by the app; no model, no network.
"""
from __future__ import annotations

import os
import random
import re

from google.adk.agents import BaseAgent
from google.adk.events import Event
from google.genai import types

from playfellow_coop.skills.registry import SKILLS

GAME = re.compile(r"play\s+([a-z_0-9]+)\s*,?\s*seed\s+(\d+)", re.I)
MAX_STEPS = 3000  # a skill that has not finished by then has lost (brick_breaker needs far more and is left out of the default evalset)


def choose(game: str, seed: int) -> str:
    """The skill to start: the game's own, or (control) any of the five."""
    if os.environ.get("PF_ADK_CHOOSER") == "random":
        return random.Random(seed * 7919 + len(game)).choice(sorted(cls.name for cls in SKILLS.values()))
    return SKILLS[game].name


def play(game: str, seed: int, skill_name: str) -> dict:
    """Play `skill_name` on `game` from pixels until the game ends; a skill made for another game simply fails to win."""
    from bench import arena_run as ar
    from playfellow_coop.gym.env import PlayfellowGym
    from playfellow_coop.gym.oracle import run_oracle
    by_name = {cls.name: cls for cls in SKILLS.values()}
    env = PlayfellowGym(game, lambda s: ar.load_game(game, s), seed=seed)
    try:
        card = run_oracle(env, by_name[skill_name](), MAX_STEPS)
        return {"won": bool(card.won), "steps": int(card.steps)}
    except Exception as error:  # noqa: BLE001 (a wrong skill may break on a game it does not know: that is a loss, not a crash)
        return {"won": False, "steps": 0, "error": type(error).__name__}


class ArenaPlayer(BaseAgent):
    async def _run_async_impl(self, ctx):
        parts = getattr(ctx.user_content, "parts", None) or []
        text = " ".join(p.text for p in parts if getattr(p, "text", None))
        match = GAME.search(text)
        if not match or match.group(1) not in SKILLS:
            yield Event(author=self.name, invocation_id=ctx.invocation_id, content=types.Content(role="model", parts=[types.Part(text="I do not know that game.")]))
            return
        game, seed = match.group(1), int(match.group(2))
        skill = choose(game, seed)
        call = types.FunctionCall(id=f"call-{game}-{seed}", name="start_skill", args={"skill": skill})
        yield Event(author=self.name, invocation_id=ctx.invocation_id, content=types.Content(role="model", parts=[types.Part(function_call=call)]))
        result = play(game, seed, skill)
        answer = types.FunctionResponse(id=call.id, name="start_skill", response=result)
        yield Event(author=self.name, invocation_id=ctx.invocation_id, content=types.Content(role="user", parts=[types.Part(function_response=answer)]))
        verdict = "won" if result["won"] else "lost"
        yield Event(author=self.name, invocation_id=ctx.invocation_id, content=types.Content(role="model", parts=[types.Part(text=f"I {verdict} {game}.")]))


root_agent = ArenaPlayer(name="arena_player", description="Plays one arena game per message with a local skill and says whether it won.")
