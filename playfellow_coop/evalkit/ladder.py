"""The evaluation ladder: which help each rung allows and which clock it runs on (research R1 section 3.5 "4-rung ladder", R2 section 6.1 "five tiers").

A result is only meaningful with its rung. The rungs here merge both documents' ladders into the one we report: the local floor, raw model on a live clock, raw model on a paused clock,
the system with model-written skills, and the system with human-written skills.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class Rung:
    key: str
    number: int
    title: str
    perception: str  # what local perception is allowed
    control: str  # what local control is allowed
    clock: str  # "live" or "paused"
    measures: str
    model_calls: bool
    human_skill: bool
    model_skill: bool


RUNGS = (
    Rung("local_floor", 0, "Local floor (no model)", "local perception", "the local controller plays alone with fixed or random tactics", "live",
         "the win rate the scaffold reaches by itself: the floor every model claim must beat", False, True, False),
    Rung("raw_live", 1, "Raw model, live clock", "raw pixels only", "direct primitive inputs, no local skill", "live",
         "end-to-end embodied reactivity: can the model see and act in time?", True, False, False),
    Rung("raw_paused", 2, "Raw model, paused clock", "raw pixels only", "direct primitive inputs, no local skill", "paused",
         "the model's visual and strategic ceiling, separated from its latency", True, False, False),
    Rung("model_skills", 3, "System with model-written skills", "pixels plus model-configured perception", "local controllers written by the model from a blank folder", "live",
         "autonomous compound competence on a game nobody wrote a skill for", True, False, True),
    Rung("human_skills", 4, "System with human-written skills", "pixels plus pre-built perception", "the model picks, a human-authored skill plays", "live",
         "the deployed composite system; never reported as the model alone", True, True, False),
)
BY_KEY = {r.key: r for r in RUNGS}


def rung_for(model_calls: bool, human_skill: bool, model_skill: bool, clock: str) -> Rung:
    """The rung a run belongs to, from what it actually used. Mixed help (human and model skills together) is reported as the human-skill rung: the stricter label."""
    if human_skill:
        return BY_KEY["human_skills"] if model_calls else BY_KEY["local_floor"]
    if model_skill:
        return BY_KEY["model_skills"]
    if not model_calls:
        return BY_KEY["local_floor"]
    return BY_KEY["raw_paused"] if clock == "paused" else BY_KEY["raw_live"]


def table() -> str:
    lines = ["| rung | name | perception | control | clock | what it measures |", "|---|---|---|---|---|---|"]
    for r in RUNGS:
        lines.append(f"| {r.number} | {r.title} | {r.perception} | {r.control} | {r.clock} | {r.measures} |")
    return "\n".join(lines)
