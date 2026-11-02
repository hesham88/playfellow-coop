"""The after-session debrief, written by Muse Wonder from counted facts only.

The session counts what happened (`Assist.log`: the parts you asked for, which were done and who decided, turns, keys pressed for you,
AI calls, seconds; the split-controls refusals; whether F12 ended it). Muse Wonder turns those facts into two or three friendly sentences.
It is sent the facts as JSON and nothing else: no picture, and not the player's own words again.

A model can make numbers up. So every number in its text (Western or Arabic-Indic digits) must be one of the counted numbers; a text with
any other number is refused and the plain counted line is shown instead, as it is when the model is not reachable. The source of what the
player sees is always recorded ("muse-wonder" or "counted")."""
from __future__ import annotations

import json
import re

from messages import tr

MODEL = "muse-wonder-1.0"
USD_IN, USD_OUT = 4e-6, 20e-6  # muse-wonder-1.0 Standard prices per token ($4 / $20 per million)
SYSTEM = ("You write a short, warm debrief for an adult gamer after a play session with an AI buddy that did some parts of the game for them. "
          "Write two or three plain sentences in the requested language. Use ONLY the numbers in FACTS, exactly as given; never compute, "
          "round or invent a number, a percentage or a time. Do not give advice, scores or judgement of the player. If parts were not "
          "done, say so plainly.")
_DIGITS = str.maketrans("٠١٢٣٤٥٦٧٨٩", "0123456789")


def facts_from(log: list[dict], refused: int, f12: bool) -> dict:
    done = [r for r in log if r.get("done")]
    return {"parts_asked": len(log), "parts_done": len(done), "parts_not_done": len(log) - len(done),
            "done_by_model": sum(1 for r in done if r.get("done_by") == "model_said"),
            "turns": sum(int(r.get("turns", 0)) for r in log), "presses_for_you": sum(int(r.get("actions", 0)) for r in log),
            "ai_calls": sum(int(r.get("ai_calls", 0)) for r in log), "seconds": round(sum(float(r.get("seconds", 0.0)) for r in log)),
            "refused_kept_keys": int(refused), "stopped_with_f12": bool(f12)}


def numbers_ok(text: str, facts: dict) -> bool:
    allowed = {str(v) for v in facts.values() if isinstance(v, int) and not isinstance(v, bool)}
    found = re.findall(r"\d+(?:[.,]\d+)?", (text or "").translate(_DIGITS))
    return all(n in allowed for n in found)


def plain_line(facts: dict, language: str) -> str:
    f = facts
    english = (f"You asked for {f['parts_asked']} parts; {f['parts_done']} were done and {f['parts_not_done']} were not. "
               f"I pressed {f['presses_for_you']} keys for you in {f['turns']} turns and asked the AI {f['ai_calls']} times.")
    arabic = (f"طلبت {f['parts_asked']} أجزاء؛ أُنجز منها {f['parts_done']} ولم يُنجز {f['parts_not_done']}. "
              f"ضغطت {f['presses_for_you']} زرًا بدلًا منك في {f['turns']} دورة وسألت الذكاء الاصطناعي {f['ai_calls']} مرة.")
    if f["refused_kept_keys"]:
        english += f" I left your keys alone {f['refused_kept_keys']} times."
        arabic += f" تركت أزرارك لك {f['refused_kept_keys']} مرة."
    if f["stopped_with_f12"]:
        english += " The session ended with F12."
        arabic += " انتهت الجلسة بزر F12."
    return arabic if language == "arabic" else english


class Debrief:
    def __init__(self, brain):
        if getattr(brain, "model", MODEL) != MODEL:
            raise ValueError(f"the debrief is written by {MODEL}")
        self.brain = brain

    def write(self, facts: dict, language: str) -> dict:
        ask = f"Language: {'Arabic' if language == 'arabic' else 'English'}.\nFACTS: {json.dumps(facts)}"
        try:
            text = self.brain.ask(SYSTEM, ask, [])
        except Exception as error:  # the debrief never fails the session: the counted line is always there
            return {"source": "counted", "text": plain_line(facts, language), "error": type(error).__name__, "cost_usd": 0.0}
        usage = getattr(self.brain, "last_usage", None) or {}
        cost = round((usage.get("prompt_tokens") or 0) * USD_IN + (usage.get("completion_tokens") or 0) * USD_OUT, 6)
        text = (text or "").strip()
        if not text or not numbers_ok(text, facts):
            return {"source": "counted", "text": plain_line(facts, language), "rejected": text, "cost_usd": cost}
        return {"source": "muse-wonder", "text": text, "cost_usd": cost}


def wonder_brain(api_key: str):
    """The real Muse Wonder client: the same pinned address and rules as the Muse brain, no planner schema, no prompt cache key."""
    from playfellow_coop.muse_brain import MuseBrain
    brain = MuseBrain(MODEL, api_key, effort="low", cache_key=None)
    brain.max_tokens = 400
    return brain


__all__ = ["MODEL", "Debrief", "facts_from", "numbers_ok", "plain_line", "wonder_brain", "tr"]
