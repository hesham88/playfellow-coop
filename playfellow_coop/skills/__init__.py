"""Skills: small local controllers the buddy can run for many game steps from one model decision.

The model looks at the (marked) picture and chooses a skill. The skill then reads each new picture itself, with no model call, and presses keys until it
is done, the game ends, or its step limit is reached. Like a driver who says "take the next exit" once, and the hands do the rest.

Rules for every skill (a test pins them): it reads only the picture (pixels), never the game's inner state; it presses only keys the controls card
allows; it has a hard step limit; it can say why it stopped. The model stays the one that decides WHAT to do; a skill only decides HOW.
"""
from __future__ import annotations

from playfellow_coop.skills.base import Skill, SkillResult, run_skill  # noqa: F401
from playfellow_coop.skills.registry import SKILLS, skill_for_game  # noqa: F401
