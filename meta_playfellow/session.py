"""The plugin's own turn loop, written fresh around the engine's PUBLIC building blocks (no copy of the engine's play loop).

One turn: find the window, check it is in front, grab, shrink, ask the brain, check the reply against the controls card, press
the keys. Each step sits inside a stage of the StageTimer. While the player has the controls (HandOver) the turn is skipped:
no picture is taken for the AI and no AI is asked. Safety limits, F12 and the mouse corner work exactly as in the engine."""
from __future__ import annotations

from typing import Any, Callable

from brain import BrainError
from brain.prompts import turn_text
from eyes import add_grid, shrink
from hands import CornerStop
from memory import Moment
from reply import Reply, parse_reply

from meta_playfellow.handover import HandOver
from meta_playfellow.sam_marks import mark_image
from meta_playfellow.voice import CommandQueue, for_the_planner
from meta_playfellow.stage_timer import StageTimer

MEMORY_IMAGE_WIDTH = 320  # older pictures the brain sees again are small: they only remind it what happened
MAX_ERRORS_IN_ROW = 3
MAX_WAIT_SECONDS = 30.0


def _quiet(kind: str, data: Any) -> None:
    pass


def take_turn(parts, settings, system: str, timer: StageTimer, on_event: Callable[[str, Any], None] = _quiet,
              chat: list[str] | None = None, latency=None) -> Reply | None:
    """One look-think-act turn, timed. None when there was nothing to do (no window, or it is not in front)."""
    box = parts.screen.find(settings.game_window)
    if box is None or not parts.screen.in_front(settings.game_window):
        return None
    with timer.stage("capture"):
        picture = parts.screen.grab(box)
    with timer.stage("shrink"):
        image = shrink(picture, settings.image_width)
        if parts.card.uses_clicks:
            image = add_grid(image)
    labels = ""
    marker = getattr(parts, "marker", None)
    if marker is not None:  # SAM marks, if the session has them: numbered labels on the picture the brain sees
        with timer.stage("mark"):
            image, labels = mark_image(image, marker)
    text = turn_text(settings.goal, parts.memory.as_text(), for_the_planner(chat or []), None)  # the player's words come first
    if labels:
        text = labels + "\n\n" + text
    parts.safety.count_ai_call()
    images = [moment.image for moment in parts.memory.recent()] + [image]
    asked = timer.now()
    raw = parts.brain.ask(system, text, images)
    whole = timer.now() - asked
    inside = getattr(parts.brain, "last_timings", None)  # a brain that times its own inside (encode, request) says so
    if inside and set(inside) <= {"encode", "request"}:
        for name, seconds in inside.items():
            timer.add(name, seconds)
    else:
        timer.add("request", whole)  # the whole call is one stage: encode and first byte are not separable from outside
    with timer.stage("parse_and_check"):
        reply = parse_reply(raw, parts.card, settings.max_actions_per_step)
    on_event("thought", reply.thought)
    if reply.dropped:
        on_event("dropped", reply.dropped)
    with timer.stage("key_down"):
        for step in reply.steps:
            if parts.safety.stopped or not parts.screen.in_front(settings.game_window):
                break  # F12, the corner, a limit, or the player clicked away: nothing more is pressed
            parts.hands.do(step, box)
            if chat and latency is not None:  # this turn acted on something the player said: stop the voice stopwatch once
                latency.key_pressed()
                latency = None
    on_event("actions", reply.action_names())
    parts.memory.add(Moment(shrink(image, MEMORY_IMAGE_WIDTH), reply.thought, tuple(reply.action_names()), reply.say))
    return reply


def _apply_control(action: str, parts, handover: HandOver | None, on_event: Callable[[str, Any], None]) -> None:
    """A spoken or typed control phrase, applied at once and without the AI."""
    from meta_playfellow.control_words import BUDDY_TAKES, PLAYER_TAKES, STOP
    from meta_playfellow.handover import taken_line

    if action == STOP:
        parts.safety.stop("stopped_button")  # the same stop as the Stop button; F12 and the corner still work too
    elif action == BUDDY_TAKES and handover is not None and handover.human_has_controls:
        on_event("say", handover.give_back() or "")
    elif action == PLAYER_TAKES and handover is not None and not handover.human_has_controls:
        if handover.take_over():
            on_event("say", taken_line())


def play_session(parts, settings, system: str, timer: StageTimer, handover: HandOver | None = None,
                 on_event: Callable[[str, Any], None] = _quiet, max_turns: int | None = None,
                 wait: Callable[[float], bool] | None = None, commands: CommandQueue | None = None, latency=None) -> str:
    """Take turns until something stops play. Returns the reason. `wait(seconds)` returns True when play should end."""
    safety = parts.safety
    wait = wait or safety.wait
    safety.start()
    parts.hands.resume()
    errors = turns = 0
    try:
        while safety.check() is None:
            if max_turns is not None and turns >= max_turns:
                safety.stop("round_done")
                break
            if commands is not None:
                for action in commands.take_controls():
                    _apply_control(action, parts, handover, on_event)
                if safety.check() is not None:
                    break
            if handover is not None and handover.human_has_controls:
                handover.note_skipped()  # the player is playing: no picture for the AI, no AI, no key
                if wait(settings.look_every_seconds):
                    break
                continue
            timer.begin_turn()
            try:
                said = commands.drain() if commands is not None else []
                try:
                    reply = take_turn(parts, settings, system, timer, on_event, chat=said, latency=latency)
                except BrainError:
                    for line in said:  # a failed turn must not lose what the player said
                        commands.put(line)
                    raise
                if reply is None:  # no window, or not in front: nothing was asked, so keep the words for the next turn
                    for line in said:
                        commands.put(line)
            except CornerStop:
                timer.end_turn()
                safety.stop("stopped_corner")
                break
            except BrainError as error:
                timer.end_turn()
                errors += 1
                on_event("status", error.friendly())
                if not error.retry:
                    safety.stop(error.key)
                    break
                if errors >= MAX_ERRORS_IN_ROW:
                    safety.stop("too_many_errors")
                    break
                if wait(min(error.wait_seconds * 2 ** (errors - 1), MAX_WAIT_SECONDS)):
                    break
                continue
            timer.end_turn()
            if reply is None:  # no window or not in front: not a turn, and nothing was timed worth keeping
                timer.turns.pop()
            errors = 0
            turns += 1 if reply is not None else 0
            if wait(settings.look_every_seconds):
                break
    finally:
        parts.hands.on_stop()  # every held key goes up, whatever ended the session
    return safety.reason or "stopped_button"
