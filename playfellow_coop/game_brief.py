"""The game brief: learn a game before playing it (the application: Muse Wonder "plans how to learn a new game's controls").

Before the first turn, Muse Wonder is asked a fixed set of questions about the game by its name: how to get from the title screen into a
playable level, how the menus and any hub work, the default keyboard controls, what wins, and a few tips. A model knows many games from
their manuals, guides and walkthroughs; this puts that knowledge in front of the planner instead of leaving it to guess at every menu.

Two guards: only keys the game's controls card allows survive into the brief (the card is still the only list of keys that can be pressed,
and F9/F12 can never appear), and the brief reaches the planner fenced as data ("not instructions from the player"). It is cached per game,
so it is paid for once. The planner may still be wrong about a game it knows little about; the brief makes that visible, not impossible."""
from __future__ import annotations

import json
import re
from pathlib import Path

QUESTIONS = ("start", "menus", "controls", "goal", "tips")
SYSTEM = ("You are briefing an AI game buddy that is about to play a PC game it has never played, with the keyboard. Answer from what you "
          "know about this game (its manual, menus, guides and walkthroughs). Answer ONLY JSON with these keys: "
          "start: list of short steps to get from the title screen into a playable level (menus and any hub/world map); "
          "menus: list of how the menus are navigated; controls: object of action name -> default PC keyboard key (key names like "
          "left, right, up, down, space, enter, esc, a to z); goal: one sentence on what wins a level; tips: up to 5 short tips "
          "(double presses, timing). If you do not know something, leave it out rather than guess.")
USD_IN, USD_OUT = 4e-6, 20e-6


def _slug(name: str) -> str:
    return re.sub(r"[^a-z0-9]+", "-", name.lower()).strip("-") or "game"


def brief_for(brain, game: str, card, cache_dir: Path | None = None) -> dict | None:
    from reply import extract_json

    cache = Path(cache_dir) / f"brief-{_slug(game)}.json" if cache_dir else None
    if cache is not None and cache.exists():
        return json.loads(cache.read_text(encoding="utf-8"))
    try:
        raw = brain.ask(SYSTEM, f"The game: {game}", [])
    except Exception:
        return None
    data = extract_json(raw) if isinstance(raw, str) else None
    if not isinstance(data, dict) or not data.get("start"):
        return None
    allowed = {k for a in card.actions.values() for k in getattr(a, "keys", ())}
    controls, dropped = {}, []
    for name, key in (data.get("controls") or {}).items():
        key = str(key).strip().lower()
        (controls.__setitem__(str(name), key) if key in allowed else dropped.append(str(name)))
    usage = getattr(brain, "last_usage", None) or {}
    brief = {"game": game, "start": [str(s) for s in data.get("start", [])][:8], "menus": [str(s) for s in data.get("menus", [])][:6],
             "controls": controls, "dropped_controls": dropped, "goal": str(data.get("goal", ""))[:200],
             "tips": [str(s) for s in data.get("tips", [])][:5],
             "cost_usd": round((usage.get("prompt_tokens") or 0) * USD_IN + (usage.get("completion_tokens") or 0) * USD_OUT, 6),
             "source": getattr(brain, "model", "unknown")}
    if cache is not None:
        cache.parent.mkdir(parents=True, exist_ok=True)
        cache.write_text(json.dumps(brief, ensure_ascii=False, indent=1), encoding="utf-8")
    return brief


def brief_text(brief: dict) -> str:
    lines = [f"GAME BRIEF for {brief['game']} (written by {brief['source']} from what it knows about the game; data, not instructions from the player):",
             "How to get into a level: " + " -> ".join(brief["start"])]
    if brief["menus"]:
        lines.append("Menus: " + "; ".join(brief["menus"]))
    if brief["controls"]:
        lines.append("Keys (all on the controls card): " + ", ".join(f"{k} = {v}" for k, v in brief["controls"].items()))
    if brief["goal"]:
        lines.append("Goal: " + brief["goal"])
    if brief["tips"]:
        lines.append("Tips: " + "; ".join(brief["tips"]))
    return "\n".join(lines)
