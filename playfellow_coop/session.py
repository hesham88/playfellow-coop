"""The plugin's own turn loop, written fresh around the engine's PUBLIC building blocks (no copy of the engine's play loop).

One turn: find the window, check it is in front, grab, shrink, ask the brain, check the reply against the controls card, press
the keys. Each step sits inside a stage of the StageTimer. While the player has the controls (HandOver) the turn is skipped:
no picture is taken for the AI and no AI is asked. Safety limits, F12 and the mouse corner work exactly as in the engine."""
from __future__ import annotations

import time
from typing import Any, Callable

from brain import BrainError
from brain.prompts import turn_text
from eyes import add_grid, shrink
from hands import CornerStop
from memory import Moment
from messages import tr
from reply import Reply, parse_reply

from playfellow_coop.handover import HandOver
from playfellow_coop.sam_marks import mark_image_full
from playfellow_coop.skills.book import NONE as NO_SKILL
from playfellow_coop.spatial import StuckTracker
from playfellow_coop.voice import CommandQueue, for_the_planner
from playfellow_coop import trace
from playfellow_coop.stage_timer import StageTimer

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
    labels, blocked, stuck = "", "", None
    logging = bool(getattr(parts, "session_log_on", False))  # set by main only when --log is given
    marker = getattr(parts, "marker", None)
    if marker is not None:  # SAM marks, if the session has them: numbered labels on the picture the brain sees
        with timer.stage("mark"):
            image, labels, marks = mark_image_full(image, marker)
        if logging:  # only with --log: otherwise this does not even build the list
            on_event("marks", [{"tag": m.tag, "kind": m.kind, "x": m.x, "y": m.y} for m in marks])
        stuck = getattr(parts, "stuck", None) or StuckTracker()
        parts.stuck = stuck
        blocked = stuck.note(marks)  # "your last move did nothing", from the marks alone
    text = turn_text(settings.goal, parts.memory.as_text(), for_the_planner(chat or []), None)  # the player's words come first
    # Prompt caching matches from the start of the prompt forward (docs: prompt caching): put what stays the same first and what changes every turn last.
    harness = getattr(parts, "harness", None)
    remembered = harness.memory_block() if harness is not None else ""
    if remembered:  # what worked before in this game: fenced data, never an instruction; it changes only between games
        text = remembered + "\n\n" + text
    if blocked:
        text = text + "\n\n" + blocked
    if labels:
        text = text + "\n\n" + labels
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
    parsing = time.perf_counter()
    with timer.stage("parse_and_check"):
        reply = parse_reply(raw, parts.card, settings.max_actions_per_step)
    skills = getattr(parts, "skills", None)
    chosen = _chosen_skill(raw) if skills is not None else None
    if chosen not in (None, NO_SKILL):  # the model chose a skill: it presses the keys for many steps, reading the picture itself, with no more model calls
        stop = lambda: _skill_must_stop(parts, settings)  # noqa: E731
        run = lambda: skills.run(chosen, parts, box, stop, max_steps=getattr(parts, "skill_max_steps", None))  # noqa: E731
        harness = getattr(parts, "harness", None)
        with timer.stage("skill"):
            if harness is None:
                ran = run()
            else:  # the harness runs it as a flow: act, then parallel checks, a retry, and the player's turn if it is still stuck
                outcome = harness.skill_flow(run, lambda: parts.screen.grab(box), stop).run()
                ran = outcome.context.get("result")
                harness.record_skill(ran, won=getattr(ran, "stopped", "") == "game_over" and bool(getattr(parts, "skill_won", lambda: None)()))
                if outcome.status == "help":
                    from playfellow_coop.harness.runtime import HELP_LINE, HELP_LINE_AR
                    on_event("say", tr(HELP_LINE, HELP_LINE_AR))
                    handover = getattr(parts, "handover", None)
                    if handover is not None:
                        handover.take_over()
        if ran is not None:
            on_event("thought", reply.thought)
            on_event("skill", {"name": chosen, "steps": ran.steps, "stopped": ran.stopped})
            reply.event = f"skill:{chosen}:{ran.stopped}"
            parts.memory.add(Moment(shrink(image, MEMORY_IMAGE_WIDTH), reply.thought, (f"skill {chosen}",), reply.say))
            return reply
    tracer = getattr(parts, "tracer", None)  # --trace: one line per request, hashes and numbers only
    if tracer is not None:
        said = {k: v for k, v in (getattr(parts.brain, "last_request", None) or {}).items() if k in trace.BRAIN_FIELDS}
        said.setdefault("request_ms", whole * 1000.0)
        tracer.request("plan", prefix=system, captured_px=getattr(picture, "size", None), sent_px=getattr(image, "size", None),
                       parse_ms=(time.perf_counter() - parsing) * 1000.0,
                       parse={"valid": not reply.confused, "dropped": len(reply.dropped), "actions": len(reply.steps)}, **said)
    on_event("thought", reply.thought)
    if logging:
        on_event("buddy_line", reply.say)  # "say" is the hand-over line, so the buddy's own line has its own kind
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
    if tracer is not None:
        tracer.turn(actions=reply.action_names())
    if stuck is not None:
        stuck.acted(reply.action_names())
    parts.memory.add(Moment(shrink(image, MEMORY_IMAGE_WIDTH), reply.thought, tuple(reply.action_names()), reply.say))
    return reply


def _chosen_skill(raw: str) -> str | None:
    from reply import extract_json
    data = extract_json(raw)
    name = data.get("skill") if isinstance(data, dict) else None
    return name if isinstance(name, str) else None


def _skill_must_stop(parts, settings) -> bool:
    """True when a running skill has to let go at once: a stop (F12, the corner, a limit), the player has the controls, the window is not in front, or the game is over."""
    if parts.safety.stopped or not parts.screen.in_front(settings.game_window):
        return True
    handover = getattr(parts, "handover", None)
    if handover is not None and handover.human_has_controls:
        return True
    return bool(getattr(parts, "skill_stop", lambda: False)())


def _apply_control(action: str, parts, handover: HandOver | None, on_event: Callable[[str, Any], None]) -> None:
    """A spoken or typed control phrase, applied at once and without the AI."""
    from playfellow_coop.control_words import BUDDY_TAKES, PLAYER_TAKES, STOP
    from playfellow_coop.handover import taken_line

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
                    if latency is not None:
                        latency.discard()  # this phrase never reaches the planner, so its voice stopwatch must not linger
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
                if getattr(parts, "tracer", None) is not None:
                    parts.tracer.request("plan", prefix=system, error=error.key, parse={"valid": False})
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
