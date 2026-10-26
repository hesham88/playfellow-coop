"""`python -m meta_playfellow`: play a game WITH the buddy. F9 takes the controls (the buddy lets go of every key and asks no AI),
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

from meta_playfellow.budget import DailyBudget
from meta_playfellow.handover import HandOver, taken_line
from meta_playfellow.muse_brain import MuseBrain
from meta_playfellow.voice import CommandQueue, typed_listener
from meta_playfellow.session import play_session
from meta_playfellow.stage_timer import StageTimer

KEY_NAME = "MODEL_API_KEY"  # Meta's own name for the key
KEYRING_SERVICE = "meta-playfellow"


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


def build(argv: list[str] | None = None, build_parts: Callable = play.build_parts, key_loader: Callable = load_muse_key):
    parser = argparse.ArgumentParser(description="Play a game with the buddy: F9 takes over, F9 hands back, F12 stops.")
    parser.add_argument("--settings", type=Path, default=Path(play.SOFTWARE) / "settings.yaml")
    parser.add_argument("--brain", choices=("builtin", "muse"), default="builtin")
    parser.add_argument("--model", default="muse-spark")
    parser.add_argument("--window", help="the game window's title (default: the Practice Arena)")
    parser.add_argument("--card", help="the controls card name (default: from the settings)")
    parser.add_argument("--minutes", type=int)
    parser.add_argument("--typed", action="store_true", help="type commands in this window, one per line (no microphone needed)")
    parser.add_argument("--daily-usd", type=float, default=2.0, help="the Muse brain's daily spending cap in dollars")
    parser.add_argument("--daily-calls", type=int, default=400)
    parser.add_argument("--budget-file", type=Path, default=Path.home() / ".meta-playfellow" / "budget.json")
    args = parser.parse_args(argv)
    cfg = load_settings(args.settings)
    overrides = {"game_window": args.window, "controls_card": args.card, "max_minutes": args.minutes, "brain": "builtin"}
    cfg = dataclasses.replace(cfg, **{k: v for k, v in overrides.items() if v is not None})
    parts = build_parts(cfg)
    parts.typed = args.typed
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
    handover = HandOver(parts.hands, parts.safety)
    commands = CommandQueue()
    if getattr(parts, "typed", False):
        typed_listener(commands, input)
    timer = StageTimer()
    listen_stop(lambda: parts.safety.stop("stopped_f12"))
    listen_key("f9", lambda: say(handover.toggle() or taken_line()))
    say(tr(f"Playing '{cfg.game_window}'. F9 takes the controls, F9 again gives them back. F12 or the mouse in the top-left "
           "corner stops at once.",
           f"ألعب '{cfg.game_window}'. F9 يأخذ التحكم، وF9 مرة أخرى يعيده. F12 أو الفأرة في الزاوية العلوية اليسرى يوقف فورًا."))
    reason = run(parts, cfg, play.system_for(parts, cfg), timer, handover, on_event=lambda kind, data: None, commands=commands)
    say(msg(reason, minutes=cfg.max_minutes, calls=cfg.max_ai_calls))
    return 0


if __name__ == "__main__":
    sys.exit(main())
