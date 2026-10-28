"""The computer-use brain: the Responses API's native computer tool, behind the engine's one brain contract `ask(system, text, images) -> str`.

The model sees a screenshot and answers with a `computer_call` (click, double_click, drag, keypress, type, scroll, move, wait, screenshot). This brain keeps the conversation
(`previous_response_id`), turns each action into the engine's own reply JSON, and the engine's reply check still drops anything that is not on the game's controls card:
a click only becomes a card click action with grid coordinates, a keypress only becomes the card's own key action, and `type`, `scroll` and everything else without a card action is dropped
and said so. The model never touches the screen; the session's hands do.

Safety checks (`pending_safety_checks`) are NEVER acknowledged by this code: the action is held, the player is told in plain words, and only `acknowledge()` (called from the player's
own confirmation) lets it run; `decline()` ends the run. A step cap ends a trajectory that does not finish. Standard mode only, the pinned address, the key never shown: all inherited
from MuseBrain. Server-side state (`store`) is on because `previous_response_id` needs it; the screenshots of a run therefore live on the service until it expires them.
"""
from __future__ import annotations

import base64
import json
import time

from brain import BrainError, to_jpeg_bytes
from playfellow_coop import _http
from playfellow_coop.muse_brain import MuseBrain

MAX_STEPS = 50
MAX_OUTPUT_TOKENS = 1200
SYSTEM_PROMPT = (
    "You are operating a game window through screenshots. Coordinates are pixels in the screenshot you were last shown: (0, 0) is the top-left. "
    "Click the centre of the target. Batch actions only when they do not depend on new visual feedback. Use wait when something needs time. "
    "Finish by replying with a normal message when the goal is visibly complete, or a short explanation when it cannot be done. "
    "Do not guess hidden state and do not claim completion unless the screenshot supports it.")


def _grid(value: float, size: int) -> int:
    """A pixel on an image of `size` pixels as a point on the engine's 0-1000 grid."""
    return max(0, min(1000, round(float(value) * 1000.0 / max(size - 1, 1))))


def translate(actions: list[dict], card, size: tuple[int, int]) -> tuple[list, list[str]]:
    """The model's computer actions as the engine's reply actions for this controls card, and the plain-words reasons for anything dropped.
    `size` is the (width, height) of the screenshot the model saw."""
    width, height = size
    click = next((a for a in card.actions.values() if a.kind == "click"), None)
    drag = next((a for a in card.actions.values() if a.kind == "drag"), None)
    wait = next((a for a in card.actions.values() if a.kind == "wait"), None)
    by_key: dict[str, str] = {}
    for name, action in card.actions.items():
        keys = getattr(action, "keys", None)
        if getattr(action, "kind", "keys") == "keys" and keys and len(keys) == 1:
            by_key.setdefault(keys[0].lower(), name)
    out: list = []
    notes: list[str] = []
    for action in actions:
        kind = action.get("type") if isinstance(action, dict) else None
        try:
            if kind in ("click", "double_click"):
                if click is None or (kind == "click" and action.get("button", "left") != "left"):
                    notes.append(f"{kind} ({action.get('button', 'left')}) has no action on this controls card")
                    continue
                point = {"action": click.name, "x": _grid(action["x"], width), "y": _grid(action["y"], height)}
                out.extend([point, dict(point)] if kind == "double_click" else [point])
            elif kind == "drag":
                path = action.get("path") or []
                if drag is None or len(path) < 2:
                    notes.append("drag has no action on this controls card")
                    continue
                out.append({"action": drag.name, "x": _grid(path[0]["x"], width), "y": _grid(path[0]["y"], height),
                            "x2": _grid(path[-1]["x"], width), "y2": _grid(path[-1]["y"], height)})
            elif kind == "keypress":
                for key in action.get("keys") or []:
                    name = by_key.get(str(key).lower())
                    if name is None:
                        notes.append(f"key {key!r} is not on this controls card")
                    else:
                        out.append(name)
            elif kind == "wait":
                if wait is not None:
                    out.append(wait.name)
            elif kind in ("screenshot", "move"):
                continue  # nothing to press: the next screenshot is sent anyway
            else:
                notes.append(f"{kind or 'an action'} has no action on this controls card")
        except (KeyError, TypeError, ValueError):
            notes.append(f"{kind} was malformed and was dropped")
    return out, notes


class CuaBrain(MuseBrain):
    name = "muse-cua"

    def __init__(self, *args, max_steps: int = MAX_STEPS, truncation: str | None = None, **kwargs):
        super().__init__(*args, **kwargs)
        self.max_tokens = MAX_OUTPUT_TOKENS
        self.max_steps = max_steps
        self.truncation = truncation  # "auto" only where the account has it (otherwise HTTP 400)
        self._card = None
        self.reset()

    def reset(self) -> None:
        """Start a new trajectory (a new game, or after a stop)."""
        self.previous_id: str | None = None
        self.call_id: str | None = None  # the computer_call whose result the next request carries
        self.steps = 0
        self.held: dict | None = None  # a computer_call waiting for the player's yes (safety checks)
        self.approved = False
        self.acknowledged: list[dict] = []
        self.finished = False
        self.last_notes: list[str] = []
        self.last_size = (0, 0)

    # ---- the player's side of a safety check -------------------------------------------------------------------------------------
    @property
    def waiting_for_player(self) -> list[dict]:
        return list(self.held["pending_safety_checks"]) if self.held else []

    def acknowledge(self) -> None:
        """Called only from the player's own confirmation: the held action may run."""
        if self.held:
            self.approved = True

    def decline(self) -> None:
        self.reset()
        self.finished = True

    # ------------------------------------------------------------------------------------------------------------------------------
    def _request(self, system: str, text: str, image) -> dict:
        data = base64.standard_b64encode(to_jpeg_bytes(image)).decode("ascii")
        screenshot = f"data:image/jpeg;base64,{data}"
        body: dict = {"model": self.model, "instructions": f"{SYSTEM_PROMPT}\n\n{system}".strip(), "tools": [{"type": "computer"}],
                      "reasoning": {"effort": self.effort}, "max_output_tokens": self.max_tokens, "store": True}
        if self.call_id is None:
            body["input"] = [{"role": "user", "content": [{"type": "input_text", "text": text}, {"type": "input_image", "image_url": screenshot}]}]
        else:
            body["previous_response_id"] = self.previous_id
            body["input"] = [{"type": "computer_call_output", "call_id": self.call_id, "acknowledged_safety_checks": self.acknowledged,
                              "output": {"type": "computer_screenshot", "image_url": screenshot}}]
        if self.truncation:
            body["truncation"] = self.truncation
        if self.safety_id:
            body["safety_identifier"] = str(self.safety_id)[:64]
        return body

    def ask(self, system: str, text: str, images: list) -> str:
        if self.held is not None:
            if not self.approved:  # waiting for the player: nothing is sent, nothing is pressed
                return self._hold_reply()
            call, self.held, self.approved = self.held, None, False
            self.acknowledged = [dict(c) for c in call["pending_safety_checks"]]
            self.call_id = call["call_id"]
            return self._reply(call, "")
        if self.finished or self.steps >= self.max_steps:
            why = "finished" if self.finished else "step budget reached"
            self.finished = True
            return json.dumps({"thought": why, "say": "", "actions": []})
        if not images:
            raise BrainError("brain_trouble", detail="the computer-use brain needs the current picture")
        if self.budget is not None and self.budget.exhausted():
            raise BrainError("token_cap_day")
        image = images[-1]
        self.last_size = tuple(image.size)
        started = time.perf_counter()
        response = self._send(self.base + "/responses", self._request(system, text, image))
        self.last_timings = {"encode": 0.0, "request": time.perf_counter() - started}
        _http.check_status(response.status_code)
        try:
            body = response.json()
            output = body["output"]
        except (ValueError, KeyError, TypeError):
            raise BrainError("brain_trouble", detail="the answer was not in the expected shape") from None
        self._note_usage(body)
        self.previous_id = body.get("id") or self.previous_id
        self.steps += 1
        self.acknowledged = []
        call = next((item for item in output if isinstance(item, dict) and item.get("type") == "computer_call"), None)
        message = "".join(part.get("text", "") for item in output if isinstance(item, dict) and item.get("type") == "message"
                          for part in (item.get("content") or []) if isinstance(part, dict))
        if call is None:  # the model replied with a normal message: it is done (or says it cannot)
            self.finished = True
            self.call_id = None
            return json.dumps({"thought": message[:400], "say": "", "actions": []})
        if call.get("pending_safety_checks"):
            self.held = call  # never acknowledged here
            return self._hold_reply()
        self.call_id = call["call_id"]
        return self._reply(call, message)

    def _reply(self, call: dict, message: str) -> str:
        if self._card is None:
            raise BrainError("brain_trouble", detail="the computer-use brain needs the controls card (set_card) before it can play")
        actions, notes = translate(call.get("actions") or [], self._card, self.last_size)
        self.last_notes = notes
        thought = message[:300] or (("some actions were not allowed: " + "; ".join(notes))[:300] if notes else "")
        return json.dumps({"thought": thought, "say": "", "actions": actions})

    def _hold_reply(self) -> str:
        checks = self.waiting_for_player
        words = "; ".join(str(c.get("message", "")) for c in checks)[:200]
        return json.dumps({"thought": "waiting for the player to approve an action", "say": f"I need your OK before I do this: {words}", "actions": []})

    def _note_usage(self, body: dict) -> None:
        usage = body.get("usage") if isinstance(body, dict) else None
        prompt = usage.get("input_tokens") if isinstance(usage, dict) else None
        completion = usage.get("output_tokens") if isinstance(usage, dict) else None
        cached = (usage.get("input_tokens_details") or {}).get("cached_tokens") if isinstance(usage, dict) else None
        reasoning = (usage.get("output_tokens_details") or {}).get("reasoning_tokens") if isinstance(usage, dict) else None
        cost = self.budget.record(prompt, completion) if self.budget is not None else None
        self.last_usage = {"prompt_tokens": prompt, "completion_tokens": completion}
        self.last_request = {"model": self.model, "images": 1, "tokens_in": prompt, "tokens_cached": cached, "tokens_out": completion, "reasoning_tokens": reasoning,
                             "cost_usd": cost, "request_ms": self.last_timings["request"] * 1000.0}

    def set_card(self, card) -> None:
        """The controls card the actions are translated onto (the session sets it once)."""
        self._card = card
