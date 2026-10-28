"""`python -m playfellow_coop`: play a game WITH the buddy. F9 takes the controls (the buddy lets go of every key and asks no AI),
F9 again hands them back with a short spoken-style summary; F12 or the mouse in the top-left corner stops everything.

The brain is the engine's built-in one (no key, no network) or the Muse brain (needs MODEL_API_KEY, from the environment or the
Windows credential manager, never from a file)."""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
import threading
from pathlib import Path
from typing import Callable

import play
from brain import BrainError
from eyes import make_dpi_aware
from messages import msg, tr
from safety import listen_for_f12, listen_for_key
from settings import load_settings

from playfellow_coop.budget import DailyBudget
from playfellow_coop.handover import HandOver, taken_line
from playfellow_coop.muse_brain import DEFAULT_MODEL, MuseBrain
from playfellow_coop.push_to_talk import VoiceLatency
from playfellow_coop.session_log import SessionLog, git_commit, make_header, resolve_log_path
from playfellow_coop.trace import Trace
from playfellow_coop.voice import CommandQueue, typed_listener
from playfellow_coop.session import play_session
from playfellow_coop.stage_timer import StageTimer

KEY_NAME = "MODEL_API_KEY"  # Meta's own name for the key
KEYRING_SERVICE = "playfellow-coop"


def load_muse_key() -> str | None:
    """The key from the environment or the Windows credential manager; never from a file in this repo."""
    key = os.environ.get(KEY_NAME, "").strip()
    if key:
        return key
    try:
        import keyring

        return (keyring.get_password(KEYRING_SERVICE, KEY_NAME) or "").strip() or None
    except Exception:  # no credential manager here: the same as no key
        return None


FAKE_MARKS_BANNER = ("FAKE MARKS ON: the numbered marks come from a fake server built from the Practice Arena's starting layout. "
                     "This is a pipeline demo, NOT SAM output. Do not use it for results, the README or the video.")


def attach_marks(parts, mode: str, key_loader: Callable, budget_file: Path, daily_usd: float, daily_calls: int, track: bool = True) -> None:
    """Give the session a marker. "sam" needs a key and calls the real service; "fake" starts a local fake server and says so loudly."""
    from playfellow_coop import sam_marks
    from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker
    from playfellow_coop.tracking import Tracker

    budget = DailyBudget(budget_file, daily_usd, daily_calls)
    if mode == "sam":
        key = key_loader()
        if not key:
            raise BrainError("no_key")
        parts.marker = SamMarker(key, budget=budget, tracker=Tracker() if track else None)
        return
    from practice_arena.game import ArenaGame

    from playfellow_coop.fakes import FakeSam

    parts.fake_sam = FakeSam(ArenaGame(), DEFAULT_PROMPTS).__enter__()  # a local server; it never talks to Meta
    sam_marks.ENDPOINTS["sam"] = parts.fake_sam.url
    parts.marker = SamMarker("fake-key-never-sent-to-meta", budget=budget, tracker=Tracker() if track else None)


def build(argv: list[str] | None = None, build_parts: Callable = play.build_parts, key_loader: Callable = load_muse_key):
    parser = argparse.ArgumentParser(description="Play a game with the buddy: F9 takes over, F9 hands back, F12 stops.")
    parser.add_argument("--settings", type=Path, default=Path(play.SOFTWARE) / "settings.yaml")
    parser.add_argument("--brain", choices=("builtin", "muse", "local-open"), default="builtin",
                        help="builtin = no AI, no key; muse = a Muse model on the Meta Model API; "
                             "local-open = an open model served on THIS PC by LM Studio (give its id with --model)")
    parser.add_argument("--model", default=None, help="the model: muse-spark-1.3 by default for --brain muse; required for local-open")
    parser.add_argument("--window", help="the game window's title (default: the Practice Arena)")
    parser.add_argument("--card", help="the controls card name (default: from the settings)")
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--typed", action="store_true", help="type commands in this window, one per line (no microphone needed)")
    parser.add_argument("--talk-key", default="", help="hold this key (for example f8) to talk to the buddy; needs a Muse key and a microphone")
    parser.add_argument("--marks", choices=("off", "sam", "fake"), default=None,
                        help="numbered marks on the picture: sam = SAM 3.1 (needs a key), fake = a fake server for a pipeline demo; "
                             "fake marks are NEVER SAM output and never belong in results or the video. "
                             "Default: sam with --brain muse, off otherwise")
    parser.add_argument("--overlay", action="store_true",
                        help="the floating command center over the game (a small chat panel: summon and hide with one key)")
    parser.add_argument("--track", choices=("on", "off"), default="on",
                        help="on: between SAM calls a local tracker follows what SAM found and asks SAM again only when something is lost (fewer requests, lower latency)")
    parser.add_argument("--dry-run", action="store_true",
                        help="do everything except press keys: the buddy looks, thinks and says what it would press (cookbook: voice chess; nothing is ever pressed in a dry run)")
    parser.add_argument("--skills", choices=("on", "off"), default="on",
                        help="on: the model may start a skill (a local controller that plays many steps for it) when the game has one; off: the model presses every key")
    parser.add_argument("--cua", action="store_true",
                        help="with --brain muse: use the native computer tool (the model answers with clicks and key presses on the screenshot; safety checks wait for your approve/decline)")
    parser.add_argument("--input", choices=("pydirectinput", "scancode"), default="pydirectinput",
                        help="scancode (Windows): press hardware scan codes with the extended flag and absolute or relative mouse, the way games read input; the same safety rules apply")
    parser.add_argument("--screen-watch", choices=("on", "off"), default="on",
                        help="on: a frozen loading screen is waited out without asking the model, and menu, game-over and victory screens are named in the prompt")
    parser.add_argument("--stop-on-end", action="store_true", help="stop the session when the end-of-game signals say the match is over (needs the screen watch)")
    parser.add_argument("--max-steps", type=int, default=None, help="a watchdog in the loop: end the session after this many turns")
    parser.add_argument("--summon-key", default="ctrl+alt+p", help="the key that opens and closes the command center (refused if the game's card uses it)")
    parser.add_argument("--daily-usd", type=float, default=2.0, help="the Muse brain's daily spending cap in dollars")
    parser.add_argument("--daily-calls", type=int, default=400)
    parser.add_argument("--budget-file", type=Path, default=Path.home() / ".playfellow-coop" / "budget.json")
    parser.add_argument("--log", type=Path, default=None,
                        help="write a raw session log (what the buddy said, the marks it saw, the keys it pressed) for the replay recorder; "
                             "off unless you give a new file name (a bare name goes under ./session-logs/, which git ignores); it never holds keys, pictures, paths, names or your own words")
    parser.add_argument("--trace", type=Path, default=None,
                        help="write a pf-trace/1 file: one line per request (model, tokens in/cached/out, prefix hash, latency, finish reason, cost, "
                             "whether the answer parsed) and per turn; numbers and hashes only, never a picture, a word, a key or a path; "
                             "off unless you give a new file name (a bare name goes under ./session-logs/)")
    parser.add_argument("--trial", default="trial", help="with --trace: a short name for this trial (letters, digits, dot, dash, underscore)")
    parser.add_argument("--log-level", default=None, help="with --log: the web page's level id this run corresponds to (for example garden)")
    args = parser.parse_args(argv)
    cfg = load_settings(args.settings)
    overrides = {"game_window": args.window, "controls_card": args.card, "max_minutes": args.minutes, "brain": "builtin"}
    cfg = dataclasses.replace(cfg, **{k: v for k, v in overrides.items() if v is not None})
    parts = build_parts(cfg)
    parts.typed = args.typed
    if args.dry_run:
        from playfellow_coop.dry_run import DryRunHands
        parts.hands = DryRunHands(parts.hands)
    if args.screen_watch == "on":
        from playfellow_coop.universal.state_fit import load_state_classifier
        from playfellow_coop.universal.watch import ScreenWatch
        parts.screen_watch = ScreenWatch(load_state_classifier(str(cfg.controls_card).removeprefix("arena_")), eog_fps=1.0 / max(0.05, float(cfg.look_every_seconds)))  # a classifier fitted to this game when one is shipped
    if args.input == "scancode" and not args.dry_run:
        from playfellow_coop.universal.scan_backend import DirectInputCompat, available
        if not available():
            raise BrainError("brain_trouble", detail="--input scancode needs Windows")
        parts.hands.backend = DirectInputCompat()  # the engine's own hands and safety rules, now pressing scan codes
    parts.stop_on_end = args.stop_on_end
    if args.max_steps is not None:
        from playfellow_coop.harness.hooks import from_spec
        parts.hooks = from_spec({"watchdog": {"max_steps": args.max_steps}})
    parts.talk_key = args.talk_key.lower().strip()
    parts.voice_budget = DailyBudget(args.budget_file.with_name("voice-budget.json"), args.daily_usd, args.daily_calls)
    marks = args.marks or ("sam" if args.brain == "muse" else "off")  # the Muse brain is shown with its marks unless told otherwise
    parts.overlay, parts.summon_key = args.overlay, args.summon_key
    parts.marks_source = marks
    if args.trace:
        parts.trace_plan = {"path": resolve_log_path(args.trace), "trial": args.trial}
    if args.log:
        model = args.model or (DEFAULT_MODEL if args.brain == "muse" else "builtin" if args.brain == "builtin" else None)
        parts.session_log_plan = {"path": resolve_log_path(args.log), "brain": args.brain, "model": model, "level": args.log_level}
    if marks != "off":
        attach_marks(parts, marks, key_loader, args.budget_file.with_name("sam-budget.json"), args.daily_usd, args.daily_calls, track=args.track == "on")
    if args.brain == "local-open":
        # The engine's own LM Studio brain: loopback only, no proxy, and the memory check that refuses a model that will not fit
        # BEFORE it is loaded (the reason a laptop is not frozen). Never routed through MuseBrain, which would skip that check.
        from brain.lmstudio import LMStudioBrain

        if not args.model:
            raise BrainError("brain_trouble", detail="--brain local-open needs the model's id as shown in LM Studio: add --model <id>")
        parts.brain = LMStudioBrain(args.model)
    if args.brain == "muse":
        key = key_loader()
        if not key:
            raise BrainError("no_key")
        brain_class = MuseBrain
        if args.cua:
            from playfellow_coop.cua_brain import CuaBrain
            brain_class = CuaBrain
        parts.brain = brain_class(args.model or DEFAULT_MODEL, key, budget=DailyBudget(args.budget_file, args.daily_usd, args.daily_calls))
        if args.cua:
            parts.brain.set_card(parts.card)
            return parts, cfg  # the native tool has its own protocol: no skills schema, no marks
        if not parts.card.uses_clicks:  # key cards: the reply is held to a schema whose actions are exactly the card's keys (a click card keeps free text)
            parts.brain.set_actions(parts.card.actions)
        attach_skills(parts, cfg, args.skills)
    return parts, cfg


def attach_skills(parts, cfg, switch: str) -> None:
    """Give the session a skill book when the game has one (the arena game named by the card, for example arena_snake) and the model may use it."""
    from playfellow_coop.skills.book import SkillBook
    from playfellow_coop.skills.registry import SKILLS
    game = str(cfg.controls_card).removeprefix("arena_")
    if switch == "off" or game not in SKILLS or not hasattr(parts.brain, "set_skills"):
        return
    parts.skills = SkillBook(game)
    parts.wait_for_ticks = True  # live play: a real-time game ticks on its own clock, so a skill waits for the picture to move between keys
    parts.brain.set_skills(parts.skills.names)
    from playfellow_coop.harness.runtime import Harness
    parts.harness = Harness(game=game, goal=cfg.goal)  # session, long-term facts, identity, goal and the flow around a skill run (files under ~/.playfellow-coop/harness)


def main(argv: list[str] | None = None, build_fn: Callable = build, listen_key: Callable = listen_for_key,
         listen_stop: Callable = listen_for_f12, run: Callable = play_session, say: Callable = print,
         overlay_builder: Callable | None = None) -> int:
    try:
        parts, cfg = build_fn(argv)
    except BrainError as error:
        say(error.friendly())
        return 2
    log = None
    plan = getattr(parts, "session_log_plan", None)
    if plan:  # --log: opened before anything starts, and never over an existing file
        try:
            log = SessionLog(plan["path"], make_header(parts, plan))
        except FileExistsError:
            say(tr("That --log file already exists: nothing was overwritten. Pick a new file name.",
                   "ملف --log موجود بالفعل: لم يُكتب فوقه شيء. اختر اسم ملف جديدًا."))
            return 2
        except OSError as error:
            say(tr(f"The --log file cannot be created ({type(error).__name__}).", f"لا يمكن إنشاء ملف --log ({type(error).__name__})."))
            return 2
        parts.session_log_on = True  # the session now reports the marks and the buddy's lines (and does not otherwise)
    tracer = None
    trace_plan = getattr(parts, "trace_plan", None)
    if trace_plan:  # --trace: opened before anything starts, and never over an existing file
        try:
            tracer = Trace(trace_plan["path"], trace_plan["trial"], commit=git_commit())
        except FileExistsError:
            say(tr("That --trace file already exists: nothing was overwritten. Pick a new file name.",
                   "ملف --trace موجود بالفعل: لم يُكتب فوقه شيء. اختر اسم ملف جديدًا."))
            return 2
        except ValueError:
            say(tr("The --trial name must be 1 to 40 letters, digits, dots, dashes or underscores.",
                   "اسم --trial يجب أن يكون من ١ إلى ٤٠ حرفًا أو رقمًا أو نقطة أو شرطة."))
            return 2
        except OSError as error:
            say(tr(f"The --trace file cannot be created ({type(error).__name__}).", f"لا يمكن إنشاء ملف --trace ({type(error).__name__})."))
            return 2
        parts.tracer = tracer
        if getattr(parts, "marker", None) is not None:
            parts.marker.tracer = tracer
    make_dpi_aware()
    if getattr(parts, "marks_source", "off") == "fake":
        say(FAKE_MARKS_BANNER)
    handover = HandOver(parts.hands, parts.safety)
    parts.handover = handover  # a running skill lets go the moment the player takes the controls
    commands = CommandQueue()
    if getattr(parts, "typed", False):
        typed_listener(commands, input)
    latency = VoiceLatency()
    talk_key = getattr(parts, "talk_key", "")
    talker = None
    if talk_key:
        key = load_muse_key()
        if not key:
            say(tr("Talking needs a Muse key (MODEL_API_KEY). You can still type commands with --typed.",
                   "الكلام يحتاج مفتاح Muse (MODEL_API_KEY). يمكنك الكتابة بدلًا منه باستخدام --typed."))
        else:
            from playfellow_coop.microphone import Microphone
            from playfellow_coop.push_to_talk import PushToTalk, listen_hold
            from playfellow_coop.realtime_voice import RealtimeTranscriber

            talker = PushToTalk(Microphone(), RealtimeTranscriber(key, budget=parts.voice_budget, tracer=tracer),
                                commands, say, card=parts.card, language=cfg.language, latency=latency)
            listen_hold(talk_key, talker.key_down, talker.key_up)
    overlay = None
    if getattr(parts, "overlay", False):
        from playfellow_coop.overlay.hotkey import HotkeyError
        from playfellow_coop.overlay.runner import OverlayUnavailableError

        if overlay_builder is None:
            from playfellow_coop.overlay.runner import build_overlay as overlay_builder
        try:
            overlay = overlay_builder(parts, commands, handover, getattr(parts, "summon_key", "ctrl+alt+p"),
                                      talker.key_down if talker else (lambda: None), talker.key_up if talker else (lambda: None))
        except (HotkeyError, OverlayUnavailableError) as error:  # a missing Qt says so in words; no old window opens instead
            say(str(error))
            return 2
    timer = StageTimer()
    listen_stop(lambda: parts.safety.stop("stopped_f12"))
    listen_key("f9", lambda: say(handover.toggle() or taken_line()))
    say(tr(f"Playing '{cfg.game_window}'. F9 takes the controls, F9 again gives them back. F12 or the mouse in the top-left "
           "corner stops at once.",
           f"ألعب '{cfg.game_window}'. F9 يأخذ التحكم، وF9 مرة أخرى يعيده. F12 أو الفأرة في الزاوية العلوية اليسرى يوقف فورًا."))
    def on_event(kind, data):
        if kind == "say" and data:
            say(data)
        if overlay is not None:
            overlay.event(kind, data)
        if log is not None:
            log(kind, data)

    def run_session():
        return run(parts, cfg, play_system, timer, handover, on_event=on_event, commands=commands, latency=latency)

    play_system = play.system_for(parts, cfg) + (parts.skills.system_text() if getattr(parts, "skills", None) else "")
    if overlay is None:
        reason = run_session()
    else:  # the window loop owns this thread; the game session runs on another
        outcome: dict = {}

        def session_thread():
            try:
                outcome["reason"] = run_session()
            finally:
                overlay.finish()

        worker = threading.Thread(target=session_thread, name="session", daemon=True)
        worker.start()
        overlay.run()
        worker.join()
        reason = outcome.get("reason", "stopped")
    if log is not None:
        log.close()
    if tracer is not None:
        tracer.close()
    say(msg(reason, minutes=cfg.max_minutes, calls=cfg.max_ai_calls))
    if getattr(parts, "marks_source", "off") == "fake":
        say(FAKE_MARKS_BANNER)  # said again at the end, so a log or a recording can never miss it
    fake = getattr(parts, "fake_sam", None)
    if fake is not None:
        fake.__exit__(None, None, None)
    if latency.samples:
        say(tr(f"Key release to the first game key, measured: {latency.summary()}", f"من ترك المفتاح إلى أول ضغطة في اللعبة (مقيس): {latency.summary()}"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
