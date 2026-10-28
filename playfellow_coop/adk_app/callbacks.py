"""The guardrails as plain functions (research R1 section 2.4 and 4.2): they run before a tool or an action, mutate it to something safe, and say what they changed. ADK wraps them as callbacks,
and the rest of the harness calls them directly; none needs ADK to run.
"""
from __future__ import annotations

from playfellow_coop.universal.hold import SocdCleaner, minimum_hold_ms

MAX_HOLD_MS = 3000
KEYS_PER_STEP = 6


def guard_action(args: dict, state: dict) -> tuple[dict, list[str]]:
    """Make an action safe before any key is pressed. `args`: {"keys": [...], "hold_ms": int, "click": [x, y] on the 0-1000 grid}. `state` carries what the guard needs: `allowed_keys`
    (the controls card), `socd_mode`, `fps` of the game, `focus_ok`. Returns (safe args, notes). A missing focus blocks everything: nothing is ever sent to a window that is not in front."""
    notes: list[str] = []
    safe = dict(args)
    if state.get("focus_ok") is False:
        return {"keys": [], "hold_ms": 0}, ["the game window is not in front: nothing is pressed"]
    allowed = {k.lower() for k in state.get("allowed_keys", [])}
    keys = [str(k).lower() for k in args.get("keys", [])]
    if allowed:
        kept = [k for k in keys if k in allowed]
        if len(kept) != len(keys):
            notes.append("keys not on the controls card were dropped: " + ", ".join(sorted(set(keys) - set(kept))))
        keys = kept
    cleaner = state.get("_socd") or SocdCleaner(state.get("socd_mode", "neutral"))
    state["_socd"] = cleaner
    cleaned = cleaner.clean(set(keys))
    if cleaned != set(keys):
        notes.append("opposite directions together were cleaned: " + ", ".join(sorted(set(keys) - cleaned)) + " removed")
    ordered = [k for k in keys if k in cleaned]
    if len(ordered) > KEYS_PER_STEP:
        notes.append(f"more than {KEYS_PER_STEP} keys at once: the rest were dropped")
        ordered = ordered[:KEYS_PER_STEP]
    safe["keys"] = ordered
    hold = int(args.get("hold_ms", 0) or 0)
    if ordered and 0 < hold < minimum_hold_ms(float(state.get("fps", 60.0))):
        notes.append(f"a hold of {hold} ms is shorter than two frames at {state.get('fps', 60)} fps and would often be dropped: raised")
        hold = int(round(minimum_hold_ms(float(state.get("fps", 60.0)))))
    if hold > MAX_HOLD_MS:
        notes.append(f"a hold of {hold} ms was cut to {MAX_HOLD_MS} ms")
        hold = MAX_HOLD_MS
    safe["hold_ms"] = hold
    click = args.get("click")
    if click is not None:
        x, y = click
        cx, cy = min(max(float(x), 0.0), 1000.0), min(max(float(y), 0.0), 1000.0)
        if (cx, cy) != (x, y):
            notes.append("a click outside the 0-1000 grid was clamped")
        safe["click"] = [cx, cy]
    return safe, notes


def episode_should_stop(state: dict) -> bool:
    """The loop's exit rule: the detector says the match is over, the player took over, a stop was requested, or the step budget is used up."""
    return bool(state.get("episode_terminated") or state.get("player_has_controls") or state.get("stop_requested")
                or state.get("step", 0) >= state.get("max_steps", 10 ** 9))
