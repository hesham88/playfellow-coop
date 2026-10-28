"""Pillar 1 (doing) and the guardrails of pillar 4: the model's action tokens become native inputs, and impossible ones never reach the game.

A token is `[NAME]` or `[NAME(arg, arg)]`: `[MOVE_FORWARD]`, `[HOLD(w, 300)]`, `[CLICK(500, 400)]`, `[DRAG_MOUSE(100, 100, 600, 400)]`. Tokens separated by spaces run one after the other;
tokens joined with `&` run together (`[MOVE_FORWARD]&[MOVE_LEFT]`). Mouse positions are on the 0-1000 grid and are mapped to the window's pixels at the last moment.
`ActionBinder` turns tokens into `NativeInput` records through a binding table (and, when given the controls card's keys, refuses any key that is not on the card).
`GuardRails` removes what no player could do: Left and Right held together, a hold longer than the limit, a flood of inputs in one turn. Each removal is reported in plain words.
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, replace

GRID = 1000
TOKEN = re.compile(r"\[([A-Z][A-Z0-9_]*)(?:\(([^\]]*)\))?\]")

# name -> (key, default hold in ms); holding a movement key for a moment is how a person walks
MOVES = {"MOVE_FORWARD": ("w", 200), "MOVE_BACK": ("s", 200), "MOVE_LEFT": ("a", 200), "MOVE_RIGHT": ("d", 200),
         "UP": ("up", 120), "DOWN": ("down", 120), "LEFT": ("left", 120), "RIGHT": ("right", 120)}
TAPS = {"JUMP": "space", "USE": "e", "INTERACT": "e", "ATTACK": "mouse_left", "CROUCH": "ctrl", "SPRINT": "shift", "RELOAD": "r", "MAP": "m", "INVENTORY": "i", "PAUSE": "escape"}
OPPOSITES = [{"w", "s"}, {"a", "d"}, {"up", "down"}, {"left", "right"}, {"stick_up", "stick_down"}, {"stick_left", "stick_right"}, {"dpad_up", "dpad_down"}, {"dpad_left", "dpad_right"}]

MAX_HOLD_MS = 3000
MAX_INPUTS_PER_TURN = 12
MAX_TURN_MS = 6000


@dataclass(frozen=True)
class NativeInput:
    kind: str  # "key", "mouse_click", "mouse_drag", "mouse_move", "stick", "button", "wait"
    key: str = ""  # key or button name
    x: int = 0  # mouse positions on the 0-1000 grid (or a stick axis, -1000..1000)
    y: int = 0
    x2: int = 0
    y2: int = 0
    hold_ms: int = 0  # how long a key/button stays down (0 = a tap); for "wait" the wait
    clicks: int = 1
    button: str = "left"

    def to_pixels(self, box: tuple[int, int, int, int]) -> "NativeInput":
        """Map the 0-1000 grid to the window box (left, top, width, height); other kinds pass through."""
        if self.kind not in ("mouse_click", "mouse_drag", "mouse_move"):
            return self
        left, top, width, height = box
        mapped = lambda value, size, base: base + round(min(max(value, 0), GRID) * (size - 1) / GRID)  # noqa: E731
        return replace(self, x=mapped(self.x, width, left), y=mapped(self.y, height, top), x2=mapped(self.x2, width, left), y2=mapped(self.y2, height, top))


@dataclass
class Plan:
    steps: list[list[NativeInput]] = field(default_factory=list)  # each step: inputs that happen together
    notes: list[str] = field(default_factory=list)  # plain-words reasons for anything dropped or changed


def _numbers(arguments: str | None, count: int) -> list[int] | None:
    parts = [p.strip() for p in (arguments or "").split(",") if p.strip()]
    if len(parts) != count:
        return None
    try:
        return [int(float(p)) for p in parts]
    except ValueError:
        return None


class ActionBinder:
    def __init__(self, card_keys: set[str] | None = None, extra: dict[str, str] | None = None):
        """`card_keys`: the keys the active controls card allows (None = no card check here). `extra`: more TAP tokens, name -> key, for one game."""
        self.card_keys = {k.lower() for k in card_keys} if card_keys is not None else None
        self.taps = {**TAPS, **{k.upper(): v for k, v in (extra or {}).items()}}

    def _allowed(self, key: str) -> bool:
        return self.card_keys is None or key.lower() in self.card_keys or key in ("mouse_left", "mouse_right")

    def one(self, name: str, arguments: str | None) -> tuple[list[NativeInput], str]:
        """One token as inputs, or ([], why-not)."""
        if name in MOVES:
            key, default = MOVES[name]
            hold = _numbers(arguments, 1)
            return [NativeInput("key", key, hold_ms=hold[0] if hold else default)], ""
        if name in self.taps:
            return [NativeInput("key", self.taps[name])], ""
        if name in ("PRESS", "HOLD", "RELEASE"):
            parts = [p.strip().lower() for p in (arguments or "").split(",") if p.strip()]
            if not parts:
                return [], f"{name} needs a key"
            hold = 0
            if name == "HOLD":
                try:
                    hold = int(float(parts[1])) if len(parts) > 1 else 300
                except ValueError:
                    return [], "HOLD needs a number of milliseconds"
            return [NativeInput("key", parts[0], hold_ms=hold)], ""
        if name in ("CLICK", "RIGHT_CLICK", "DOUBLE_CLICK"):
            at = _numbers(arguments, 2)
            if at is None:
                return [], f"{name} needs x and y on the 0-1000 grid"
            return [NativeInput("mouse_click", x=at[0], y=at[1], clicks=2 if name == "DOUBLE_CLICK" else 1, button="right" if name == "RIGHT_CLICK" else "left")], ""
        if name == "DRAG_MOUSE":
            at = _numbers(arguments, 4)
            if at is None:
                return [], "DRAG_MOUSE needs x1, y1, x2, y2 on the 0-1000 grid"
            return [NativeInput("mouse_drag", x=at[0], y=at[1], x2=at[2], y2=at[3])], ""
        if name == "LOOK":
            at = _numbers(arguments, 2)
            if at is None:
                return [], "LOOK needs a sideways and an up-down amount"
            return [NativeInput("mouse_move", x=at[0], y=at[1])], ""
        if name == "WAIT":
            wait = _numbers(arguments, 1)
            return [NativeInput("wait", hold_ms=wait[0] if wait else 200)], ""
        if name == "STICK":
            parts = [p.strip().lower() for p in (arguments or "").split(",")]
            try:
                x, y = int(float(parts[1])), int(float(parts[2]))
            except (IndexError, ValueError):
                return [], "STICK needs a name, x and y"
            return [NativeInput("stick", parts[0], x=x, y=y, hold_ms=200)], ""
        if name == "BUTTON":
            parts = [p.strip().lower() for p in (arguments or "").split(",")]
            if not parts or not parts[0]:
                return [], "BUTTON needs a name"
            return [NativeInput("button", parts[0], hold_ms=int(float(parts[1])) if len(parts) > 1 else 0)], ""
        return [], f"unknown action {name}"

    def bind(self, text: str) -> Plan:
        """Parse a string of tokens (see the module note) into a plan. Anything unknown or not on the card is dropped with a note; the rest still runs."""
        plan = Plan()
        text = re.sub(r"\[[^\]]*\]", lambda m: re.sub(r"\s+", "", m.group(0)), text)  # spaces inside a token ("[HOLD(w, 300)]") do not split it
        text = re.sub(r"\s*&\s*", "&", text)
        for chunk in text.split():
            step: list[NativeInput] = []
            for part in chunk.split("&"):
                match = TOKEN.fullmatch(part.strip())
                if not match:
                    if part.strip():
                        plan.notes.append(f"{part.strip()!r} is not an action token")
                    continue
                inputs, why = self.one(match.group(1), match.group(2))
                if why:
                    plan.notes.append(why)
                    continue
                for item in inputs:
                    if item.kind in ("key", "button") and item.key and not self._allowed(item.key):
                        plan.notes.append(f"key {item.key!r} is not on the controls card")
                        continue
                    step.append(item)
            if step:
                plan.steps.append(step)
        return plan


class GuardRails:
    """The last check before the hands: no input a person could not make. Returns a new plan; the old one is not changed."""

    def __init__(self, max_hold_ms: int = MAX_HOLD_MS, max_inputs: int = MAX_INPUTS_PER_TURN, max_turn_ms: int = MAX_TURN_MS):
        self.max_hold_ms, self.max_inputs, self.max_turn_ms = max_hold_ms, max_inputs, max_turn_ms

    def check(self, plan: Plan) -> Plan:
        out = Plan(notes=list(plan.notes))
        count, total = 0, 0
        for step in plan.steps:
            kept: list[NativeInput] = []
            held: dict[str, NativeInput] = {}
            for item in step:
                if count >= self.max_inputs:
                    out.notes.append(f"too many inputs in one turn (limit {self.max_inputs}); the rest were dropped")
                    break
                if item.hold_ms > self.max_hold_ms:
                    out.notes.append(f"hold of {item.hold_ms} ms cut to {self.max_hold_ms} ms")
                    item = replace(item, hold_ms=self.max_hold_ms)
                if item.kind in ("mouse_click", "mouse_drag", "mouse_move") and not all(0 <= v <= GRID for v in (item.x, item.y, item.x2, item.y2)):
                    out.notes.append("a mouse position was outside the 0-1000 grid and was dropped")
                    continue
                if item.kind == "stick" and not (-GRID <= item.x <= GRID and -GRID <= item.y <= GRID):
                    out.notes.append("a stick position was outside -1000..1000 and was dropped")
                    continue
                if item.kind in ("key", "button"):
                    clash = next((other for name, other in held.items() if any({item.key, name} == pair for pair in OPPOSITES)), None)
                    if clash is not None:
                        out.notes.append(f"{item.key} and {clash.key} together would cancel out; {item.key} was dropped")
                        continue
                    held[item.key] = item
                kept.append(item)
                count += 1
            if not kept:
                continue
            step_ms = max((i.hold_ms for i in kept), default=0)
            if total + step_ms > self.max_turn_ms:
                out.notes.append(f"the turn would last more than {self.max_turn_ms} ms; the rest were dropped")
                break
            total += step_ms
            out.steps.append(kept)
        return out
