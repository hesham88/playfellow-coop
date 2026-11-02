"""First sight: learning a new game's controls (the application: "Muse Wonder ... plans how to learn a new game's controls").

1. Draft: Muse Wonder sees a few frames of a game it has never seen, and the window's title, and answers with a plan as JSON: the genre,
   the goal as it reads it, and the actions it expects, each with its keys.
2. Check: the draft is written as a controls card and loaded by the ENGINE'S OWN card loader, so the same rules hold as for a card a
   person writes: known keys only, never F12 (the stop) or F9 (the take-over). A draft that breaks a rule is refused, not repaired.
3. Probe: each drafted action is pressed once (through the caller's press function, which is the session's hands: only in the chosen
   window) and the picture before and after is compared; an action that changes nothing is dropped. The learned card is what is left.
4. Score (benchmark only): the share of the real card's keys the learned card found.

Nothing here is given the game's real card or its code: only pictures, the title and what pressing keys does."""
from __future__ import annotations

import json
import tempfile
from pathlib import Path
from typing import Callable

import numpy as np

import controls
from messages import tr

MODEL = "muse-wonder-1.0"
USD_IN, USD_OUT = 4e-6, 20e-6
CHANGE = 2.0  # mean absolute pixel change (0-255) above which a key "did something"
SYSTEM = ("You see the first frames of a computer game you have never seen, and its window title. Plan how a player would control it. "
          "Answer ONLY with JSON: {\"genre\": one of platformer, racing, puzzle, shooter, sports, rpg, strategy, maze, fighting, other, "
          "\"goal\": one sentence, \"actions\": [{\"name\": UPPER_CASE_NAME, \"keys\": key or list of keys, \"says\": a few words}]}. "
          "Use keyboard key names such as up, down, left, right, space, enter, esc, a to z, 0 to 9. Never use f9 or f12. "
          "List only actions a player of this kind of game needs.")


class FirstSightError(ValueError):
    """A draft that cannot become a card, said in both languages."""


def _yaml_value(text: str) -> str:
    return json.dumps(str(text), ensure_ascii=False)


def draft_card(brain, frames: list, title: str):
    """Ask the model for a plan and turn it into a card the engine accepts. Returns (card, info)."""
    from reply import extract_json

    raw = brain.ask(SYSTEM, f"Window title: {title}", list(frames))
    usage = getattr(brain, "last_usage", None) or {}
    cost = round((usage.get("prompt_tokens") or 0) * USD_IN + (usage.get("completion_tokens") or 0) * USD_OUT, 6)
    data = extract_json(raw) if isinstance(raw, str) else None
    if not isinstance(data, dict) or not isinstance(data.get("actions"), list) or not data["actions"]:
        raise FirstSightError(tr("The model's answer was not a plan of actions.", "إجابة النموذج لم تكن خطة أفعال."))
    lines = [f"name: {_yaml_value('First sight: ' + title)}", f"genre: {_yaml_value(data.get('genre') or 'other')}",
             f"game_hint: {_yaml_value(data.get('goal') or '')}", "actions:"]
    for a in data["actions"]:
        if not isinstance(a, dict) or not a.get("name") or not a.get("keys"):
            raise FirstSightError(tr("An action in the plan has no name or no keys.", "فعل في الخطة بلا اسم أو بلا أزرار."))
        keys = a["keys"] if isinstance(a["keys"], list) else [a["keys"]]
        lines.append(f"  {controls.normalize_name(str(a['name']))}: {{keys: {json.dumps([str(k).strip().lower() for k in keys])}, "
                     f"says: {_yaml_value(a.get('says') or '')}}}")
    with tempfile.TemporaryDirectory() as folder:
        path = Path(folder) / "first_sight.yaml"
        path.write_text("\n".join(lines) + "\n", encoding="utf-8")
        try:
            card = controls.load_card(path)  # the engine's own rules: known keys, never F9 or F12
        except controls.CardError as error:
            raise FirstSightError(str(error)) from None
    return card, {"genre": card.genre, "goal": card.game_hint, "cost_usd": cost, "raw": raw}


def _changed(before: np.ndarray, after: np.ndarray) -> float:
    """The share of pixels that changed clearly (any colour channel by more than 24 of 255)."""
    if before.shape != after.shape:
        return 1.0
    return float((np.abs(after.astype(np.int16) - before.astype(np.int16)).max(axis=-1) > 24).mean())


def probe(card, press: Callable[[str], None], grab: Callable[[], np.ndarray], idle: Callable[[], None], trials: int = 3, margin: float = 0.001):
    """Press each drafted action a few times, each time next to a moment of doing nothing (`idle`), and keep the actions whose presses change
    clearly more of the picture than doing nothing does (in many games things move by themselves). Returns (learned card, report)."""
    import dataclasses

    report, kept = {}, {}
    for name, action in card.actions.items():
        if action.kind != "keys":
            continue
        with_key, without = [], []
        for _ in range(trials):  # nothing, key, key, nothing: both sides see the same game clock (things that move every other tick)
            shots = [grab()]
            for step in ("idle", "key", "key", "idle"):
                if step == "idle":
                    idle()
                else:
                    for key in action.keys:
                        press(key)
                shots.append(grab())
            without += [_changed(shots[0], shots[1]), _changed(shots[3], shots[4])]
            with_key += [_changed(shots[1], shots[2]), _changed(shots[2], shots[3])]
        gain = sum(with_key) / len(with_key) - sum(without) / len(without)
        report[name] = {"keys": list(action.keys), "changed_with_key": round(sum(with_key) / len(with_key), 5),
                        "changed_doing_nothing": round(sum(without) / len(without), 5), "changed": gain > margin}
        if gain > margin:
            kept[name] = action
    if not kept:
        raise FirstSightError(tr("No drafted key changed the picture: I will not guess.", "لم يغيّر أي زر مقترح الصورة: لن أخمّن."))
    return dataclasses.replace(card, actions=kept), report


def key_recall(card, real) -> float:
    """The share of the real card's keys that the card found."""
    def keys(c):
        return {k for a in c.actions.values() for k in a.keys}
    want = keys(real)
    return round(len(keys(card) & want) / len(want), 4) if want else 0.0
