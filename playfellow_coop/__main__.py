"""`python -m playfellow_coop`: play a game WITH the buddy. F9 takes the controls (the buddy lets go of every key and asks no AI),
F9 again hands them back with a short spoken-style summary; F12 or the mouse in the top-left corner stops everything.

The brain is the engine's built-in one (no key, no network) or the Muse brain (needs MODEL_API_KEY, from the environment or the
Windows credential manager, never from a file)."""
from __future__ import annotations

import argparse
import dataclasses
import os
import sys
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
from playfellow_coop.muse_brain import MuseBrain
from playfellow_coop.push_to_talk import VoiceLatency
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


def attach_marks(parts, mode: str, key_loader: Callable, budget_file: Path, daily_usd: float, daily_calls: int) -> None:
    """Give the session a marker. "sam" needs a key and calls the real service; "fake" starts a local fake server and says so loudly."""
    from playfellow_coop import sam_marks
    from playfellow_coop.sam_marks import DEFAULT_PROMPTS, SamMarker

    budget = DailyBudget(budget_file, daily_usd, daily_calls)
    if mode == "sam":
        key = key_loader()
        if not key:
            raise BrainError("no_key")
        parts.marker = SamMarker(key, budget=budget)
        return
    from practice_arena.game import ArenaGame

    from playfellow_coop.fakes import FakeSam

    parts.fake_sam = FakeSam(ArenaGame(), DEFAULT_PROMPTS).__enter__()  # a local server; it never talks to Meta
    sam_marks.ENDPOINTS["sam"] = parts.fake_sam.url
    parts.marker = SamMarker("fake-key-never-sent-to-meta", budget=budget)


def build(argv: list[str] | None = None, build_parts: Callable = play.build_parts, key_loader: Callable = load_muse_key):
    parser = argparse.ArgumentParser(description="Play a game with the buddy: F9 takes over, F9 hands back, F12 stops.")
    parser.add_argument("--settings", type=Path, default=Path(play.SOFTWARE) / "settings.yaml")
    parser.add_argument("--brain", choices=("builtin", "muse"), default="builtin")
    parser.add_argument("--model", default="muse-spark")
    parser.add_argument("--window", help="the game window's title (default: the Practice Arena)")
    parser.add_argument("--card", help="the controls card name (default: from the settings)")
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--typed", action="store_true", help="type commands in this window, one per line (no microphone needed)")
    parser.add_argument("--talk-key", default="", help="hold this key (for example f8) to talk to the buddy; needs a Muse key and a microphone")
    parser.add_argument("--marks", choices=("off", "sam", "fake"), default=None,
                        help="numbered marks on the picture: sam = SAM 3.1 (needs a key), fake = a fake server for a pipeline demo; "
                             "fake marks are NEVER SAM output and never belong in results or the video. "
                             "Default: sam with --brain muse, off otherwise")
    parser.add_argument("--daily-usd", type=float, default=2.0, help="the Muse brain's daily spending cap in dollars")
    parser.add_argument("--daily-calls", type=int, default=400)
    parser.add_argument("--budget-file", type=Path, default=Path.home() / ".playfellow-coop" / "budget.json")
    args = parser.parse_args(argv)
    cfg = load_settings(args.settings)
    overrides = {"game_window": args.window, "controls_card": args.card, "max_minutes": args.minutes, "brain": "builtin"}
    cfg = dataclasses.replace(cfg, **{k: v for k, v in overrides.items() if v is not None})
    parts = build_parts(cfg)
    parts.typed = args.typed
    parts.talk_key = args.talk_key.lower().strip()
    parts.voice_budget = DailyBudget(args.budget_file.with_name("voice-budget.json"), args.daily_usd, args.daily_calls)
    marks = args.marks or ("sam" if args.brain == "muse" else "off")  # the Muse brain is shown with its marks unless told otherwise
    parts.marks_source = marks
    if marks != "off":
        attach_marks(parts, marks, key_loader, args.budget_file.with_name("sam-budget.json"), args.daily_usd, args.daily_calls)
    if args.brain == "muse":
        key = key_loader()
        if not key:
            raise BrainError("no_key")
        parts.brain = MuseBrain(args.model, key, budget=DailyBudget(args.budget_file, args.daily_usd, args.daily_calls))
    return parts, cfg


def main(argv: list[str] | None = None, build_fn: Callable = build, listen_key: Callable = listen_for_key,
         listen_stop: Callable = listen_for_f12, run: Callable = play_session, say: Callable = print) -> int:
    try:
        parts, cfg = build_fn(argv)
    except BrainError as error:
        say(error.friendly())
        return 2
    make_dpi_aware()
    if getattr(parts, "marks_source", "off") == "fake":
        say(FAKE_MARKS_BANNER)
    handover = HandOver(parts.hands, parts.safety)
    commands = CommandQueue()
    if getattr(parts, "typed", False):
        typed_listener(commands, input)
    latency = VoiceLatency()
    talk_key = getattr(parts, "talk_key", "")
    if talk_key:
        key = load_muse_key()
        if not key:
            say(tr("Talking needs a Muse key (MODEL_API_KEY). You can still type commands with --typed.",
                   "الكلام يحتاج مفتاح Muse (MODEL_API_KEY). يمكنك الكتابة بدلًا منه باستخدام --typed."))
        else:
            from playfellow_coop.microphone import Microphone
            from playfellow_coop.push_to_talk import PushToTalk, listen_hold
            from playfellow_coop.realtime_voice import RealtimeTranscriber

            talker = PushToTalk(Microphone(), RealtimeTranscriber(key, budget=parts.voice_budget),
                                commands, say, card=parts.card, language=cfg.language, latency=latency)
            listen_hold(talk_key, talker.key_down, talker.key_up)
    timer = StageTimer()
    listen_stop(lambda: parts.safety.stop("stopped_f12"))
    listen_key("f9", lambda: say(handover.toggle() or taken_line()))
    say(tr(f"Playing '{cfg.game_window}'. F9 takes the controls, F9 again gives them back. F12 or the mouse in the top-left "
           "corner stops at once.",
           f"ألعب '{cfg.game_window}'. F9 يأخذ التحكم، وF9 مرة أخرى يعيده. F12 أو الفأرة في الزاوية العلوية اليسرى يوقف فورًا."))
    reason = run(parts, cfg, play.system_for(parts, cfg), timer, handover, on_event=lambda kind, data: say(data) if kind == "say" and data else None,
                 commands=commands, latency=latency)
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
