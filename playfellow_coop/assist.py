"""The assist: the player plays, asks for one part ("grab the coins on the left", "get me past this jump"), the buddy does that part,
and the controls come back to the player by themselves. Split controls: the player keeps some keys ("you block, I heal") and the
buddy can never press or release them.

How the parts fit:
- the player starts with the controls (the hand-over, F9); while they play, no picture is taken, no AI is asked and no key is pressed;
- an ordinary spoken or typed request, said while the player has the controls, gives the buddy that one part. The request reaches the
  planner as the player's own words, the same way any command does;
- after each buddy turn, `done(request, parts)` is asked: when it says yes, or the turn limit for one part is reached, the controls go
  back to the player with one line made only of counted facts (turns, seconds, AI calls, actions). A part that was not finished is
  said plainly, never reported as done;
- F12, the mouse corner and every limit still stop everything; a stop is recorded as a stop, and the hand-back never resumes the hands;
- split controls work at two places: `buddy_card` removes every action that uses a kept key from the card the planner sees (so the
  engine's own check drops such an action), and `OwnedKeys` wraps the key backend so no route (planner, timed holds, skills) can press
  or release a kept key. A release matters too: lifting a key the player is holding would break their own move.

Every record in `Assist.log` is a counted fact, for the benchmark and for the player's summary."""
from __future__ import annotations

import dataclasses
import time
from typing import Any, Callable

from messages import tr

KEY_CALLS = ("keyDown", "keyUp", "key_down", "key_up", "press")
# Added to the planner's instructions when the assist is on: how a live session learns that the asked-for part is finished.
DONE_RULE = ('The player may ask you for one part of the game. Only when that part is finished and you can see it finished on the screen, '
             'add "done": true to your JSON answer. Never say done because you tried, ran out of ideas or guessed; '
             'leave "done" out until the picture shows it.')


class AssistError(ValueError):
    """A split that cannot work, explained in both languages."""


def _norm(key: str) -> str:
    return str(key).strip().lower()


def _action_keys(action) -> set[str]:
    keys = {_norm(k) for k in getattr(action, "keys", ()) or ()}
    if getattr(action, "hold_key", ""):
        keys.add(_norm(action.hold_key))
    return keys


def buddy_card(card, owned) -> Any:
    """The card the buddy plans with when the player keeps `owned` keys: every action that uses a kept key is gone."""
    from controls import KNOWN_KEYS

    owned = {_norm(k) for k in owned}
    unknown = sorted(k for k in owned if k not in KNOWN_KEYS)
    if unknown:
        raise AssistError(tr(f"These are not keys I know: {', '.join(unknown)}", f"هذه ليست أزرارًا أعرفها: {', '.join(unknown)}"))
    kept = {name: action for name, action in card.actions.items() if not _action_keys(action) & owned}
    if not any(_action_keys(a) or a.kind in ("click", "drag", "move", "scroll") for a in kept.values()):
        raise AssistError(tr("You kept every key: I would have nothing left to press. Keep fewer keys.",
                             "احتفظت بكل الأزرار: لن يبقى لي ما أضغطه. احتفظ بأزرار أقل."))
    return dataclasses.replace(card, actions=kept)


class OwnedKeys:
    """Wraps a key backend: a kept key is never pressed and never released by the buddy. Everything else passes through."""

    def __init__(self, inner, owned):
        self._inner = inner
        self.owned = frozenset(_norm(k) for k in owned)
        self.refused = 0

    def __getattr__(self, name):
        attr = getattr(self._inner, name)
        if name not in KEY_CALLS:
            return attr

        def guarded(key, *args, **kwargs):
            if _norm(key) in self.owned:
                self.refused += 1
                return None
            return attr(key, *args, **kwargs)
        return guarded


def apply_split(parts, owned) -> None:
    """Split the controls of a built session: the planner's card loses the kept keys and the hands can no longer press them."""
    if not owned:
        return
    parts.card = buddy_card(parts.card, owned)
    hands = parts.hands
    if getattr(hands, "card", None) is not None:
        hands.card = parts.card
    inner = getattr(hands, "inner", None)  # a dry run wraps the real hands
    for target in (hands, inner):
        if target is not None and getattr(target, "backend", None) is not None and not isinstance(target.backend, OwnedKeys):
            target.backend = OwnedKeys(target.backend, owned)


class DoneSpotter:
    """Wraps the brain and notes whether its last answer said the asked-for part is finished (the JSON value true, nothing else).
    Everything else (cost, timings, safety checks) passes through to the real brain."""

    def __init__(self, inner):
        self._inner = inner
        self.said_done = False

    def ask(self, system, text, images):
        raw = self._inner.ask(system, text, images)
        from reply import extract_json
        data = extract_json(raw) if isinstance(raw, str) else None
        self.said_done = isinstance(data, dict) and data.get("done") is True
        return raw

    def forget_done(self) -> None:
        self.said_done = False

    def __getattr__(self, name):
        return getattr(self._inner, name)


def model_said_done(request: str, parts) -> str | bool:
    """The live check: the planner said the part is finished. Recorded as the model's word ("model_said"), never as a measured fact."""
    return "model_said" if getattr(getattr(parts, "brain", None), "said_done", False) is True else False


VERIFY_SYSTEM = ("A player asked their AI game buddy to do one part of the game for them. You see two pictures of the game: the first from "
                 "when they asked, the second from now. Decide only whether that part is finished now. Answer in the usual JSON with no "
                 "actions and \"done\": true only if the second picture clearly shows the part finished; otherwise \"done\": false.")


class VerifiedDone:
    """The live check with a second look: a "done" from the planner counts only when one more question, with the picture from when the
    player asked and the picture now, also says the part is finished. One extra call per claim, none without a claim. Recorded as
    "model_verified"; every claim that was not confirmed is counted in `refused` and the part goes on."""

    def __init__(self, grab: Callable[[], Any]):
        self.grab = grab
        self.start = None
        self.refused = 0
        self.confirmed = 0

    def on_begin(self, parts) -> None:
        try:
            self.start = self.grab()
        except Exception:
            self.start = None

    def __call__(self, request: str, parts):
        brain = getattr(parts, "brain", None)
        if getattr(brain, "said_done", False) is not True:
            return False
        now = self.grab()
        pictures = [p for p in (self.start, now) if p is not None]
        try:
            raw = brain.ask(VERIFY_SYSTEM, f"The player asked: {request}. Is that part finished in the second picture?", pictures)
        except Exception:  # no answer is not a yes
            raw = ""
        from reply import extract_json
        data = extract_json(raw) if isinstance(raw, str) else None
        if isinstance(data, dict) and data.get("done") is True:
            self.confirmed += 1
            return "model_verified"
        self.refused += 1
        forget = getattr(brain, "forget_done", None)
        if callable(forget):
            forget()
        return False


class Assist:
    """One request at a time: begin, count each buddy turn, finish when done or out of turns."""

    def __init__(self, max_turns: int = 12, done: Callable[[str, Any], bool] | None = None, clock: Callable[[], float] = time.monotonic):
        if max_turns < 1:
            raise AssistError(tr("An assisted part needs at least one turn.", "الجزء المساعَد يحتاج دورة واحدة على الأقل."))
        self.max_turns, self._done, self._clock = max_turns, done, clock
        self.request: str | None = None
        self.log: list[dict] = []
        self._turns = self._actions = 0
        self._since = 0.0
        self._calls_then = 0

    @property
    def active(self) -> bool:
        return self.request is not None

    def begin(self, request: str, ai_calls_so_far: int, parts=None) -> str:
        forget = getattr(getattr(parts, "brain", None), "forget_done", None)
        if callable(forget):
            forget()  # an old "done" belongs to the last part, not this one
        on_begin = getattr(self._done, "on_begin", None)
        if callable(on_begin) and parts is not None:
            on_begin(parts)  # the second look keeps the picture from when the player asked
        self.request = " ".join(str(request).split())[:300]
        self._turns = self._actions = 0
        self._since = self._clock()
        self._calls_then = ai_calls_so_far
        return tr(f"On it: {self.request}. Say \"I've got it\" or press F9 to take it back.",
                  f"حاضر: {self.request}. قل «أنا هكمل» أو اضغط F9 لتستعيد التحكم.")

    def after_turn(self, parts, actions: int, ai_calls_so_far: int) -> str | None:
        """Count one buddy turn; the hand-back line when this part is over, else None."""
        if not self.active:
            return None
        self._turns += 1
        self._actions += actions
        done, done_by = False, ""
        if self._done is not None:
            try:
                said = self._done(self.request, parts)
            except Exception:  # a broken check never claims success
                said = False
            done = bool(said)
            done_by = said if isinstance(said, str) and said else ("check" if done else "")
        if not done and self._turns < self.max_turns:
            return None
        return self._finish("done" if done else "turn_limit", done, ai_calls_so_far, done_by)

    def end(self, reason: str, ai_calls_so_far: int) -> None:
        """The session ended (F12, the corner, a limit, the player took the controls) while a part was running."""
        if self.active:
            self._finish(reason, False, ai_calls_so_far)

    def _finish(self, ended: str, done: bool, ai_calls_so_far: int, done_by: str = "") -> str:
        seconds = self._clock() - self._since
        record = {"request": self.request, "done": done, "ended": ended, "turns": self._turns, "actions": self._actions,
                  "ai_calls": ai_calls_so_far - self._calls_then, "seconds": round(seconds, 3), "done_by": done_by}
        self.log.append(record)
        request, self.request = self.request, None
        if done:
            return tr(f"Done: {request}. Back to you. It took {record['turns']} turns, {round(seconds)} s and {record['ai_calls']} AI calls.",
                      f"تم: {request}. التحكم لك. استغرق ذلك {record['turns']} دورات و{round(seconds)} ثانية و{record['ai_calls']} طلبات للذكاء الاصطناعي.")
        return tr(f"I couldn't finish \"{request}\" in {record['turns']} turns. Back to you.",
                  f"لم أستطع إنهاء «{request}» في {record['turns']} دورات. التحكم لك.")
