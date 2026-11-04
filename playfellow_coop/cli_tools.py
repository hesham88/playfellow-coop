"""The command tools around the buddy: `playfellow <tool>` (`.\\playfellow` on Windows; `python -m playfellow_coop <tool>` once the venv is active).

    doctor [--fix] [--yes]   check Python, Windows, the engine, the packages, the widget, the key and the open games; --fix installs
    games                    the open game windows PlayFellow may play, each with its start command
    keys set|status|remove   the Meta key in the Windows credential manager: hidden input, never printed; only play sends it, to the pinned Meta API
    models                   the brains and model ids, with the measured cost per run from the committed result files
    stk [widget] [args...]   the SuperTuxKart pack from the same command
    mcp [--game TITLE]       the widget MCP server (stdio): Meta's Muse Code or any MCP agent drives the widget on a real game

This module imports nothing from the engine at load time, so `doctor` runs even when the engine is missing. Every touch of the
desktop, the credential store, pip or git goes through `Env`, so tests can replace each one."""
from __future__ import annotations

import getpass
import importlib.util
import json
import os
import platform
import subprocess
import sys
from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

KEY_NAME = "MODEL_API_KEY"  # Meta's own name for the key
KEYRING_SERVICE = "playfellow-coop"
ENGINE_URL = "https://github.com/hesham88/playfellow.git"
ENGINE_TAG = "pre-hackathon"
TOOLS = ("doctor", "games", "keys", "models", "stk", "mcp")
REPO = Path(__file__).resolve().parents[1]
RESULTS = REPO / "results"

REQUIRED = (("httpx", "httpx"), ("certifi", "certifi"), ("PIL", "Pillow"), ("websockets", "websockets"),
            ("sounddevice", "sounddevice"), ("pynput", "pynput"), ("keyring", "keyring"))
OPTIONAL = (("PySide6", "PySide6", "the in-game widget (--overlay)"), ("numpy", "numpy", "the SuperTuxKart pack"),
            ("cv2", "opencv-python-headless", "the SuperTuxKart pack"), ("mss", "mss", "the SuperTuxKart pack"))
ENGINE_MODULES = ("play", "eyes", "safety", "settings")


def engine_clone_dir() -> Path:
    """Where `doctor --fix` clones the engine: beside this repository, where the tests and the buddy look for it."""
    return REPO.parent / "playfellow"


class KeyringStore:  # pragma: no cover - the real credential manager; tests use a fake with the same three methods
    def get(self) -> str | None:
        import keyring
        return (keyring.get_password(KEYRING_SERVICE, KEY_NAME) or "").strip() or None

    def set(self, value: str) -> None:
        import keyring
        keyring.set_password(KEYRING_SERVICE, KEY_NAME, value)

    def delete(self) -> None:
        import keyring
        try:
            keyring.delete_password(KEYRING_SERVICE, KEY_NAME)
        except keyring.errors.PasswordDeleteError:
            pass


def _engine_tag() -> str | None:  # pragma: no cover - reads the real clone
    try:
        import play
    except Exception:
        return None
    folder = Path(play.__file__).resolve().parent
    try:
        done = subprocess.run(["git", "-C", str(folder), "describe", "--tags", "--always"], capture_output=True, text=True, timeout=10)
    except (OSError, subprocess.SubprocessError):
        return "installed (tag not checked)"
    return done.stdout.strip() or "installed (tag not checked)"


def _list_windows() -> list[str]:  # pragma: no cover - needs a desktop
    try:
        from eyes import Screen
        return Screen().list_windows()
    except Exception:
        return []


def _is_blocked(title: str) -> bool:  # pragma: no cover - the engine's own list
    try:
        from games import is_blocked
        return is_blocked(title)
    except Exception:
        return False


def _cards() -> list[str]:  # pragma: no cover - the engine's controls folder
    try:
        import play
        folder = Path(play.SOFTWARE) / "controls"
        return sorted(p.stem for p in folder.glob("*.yaml"))
    except Exception:
        return []


def _forward(module: str, args: list[str]) -> int:  # pragma: no cover - runs the pack in this process
    import runpy
    sys.argv = [module, *args]
    try:
        runpy.run_module(module, run_name="__main__")
    except SystemExit as done:
        return int(done.code or 0) if not isinstance(done.code, str) else 1
    return 0


def _run(cmd: list[str]) -> int:  # pragma: no cover - the real installer, only after the player said yes
    return subprocess.run(cmd).returncode


@dataclass
class Env:
    out: Callable[[str], None] = print
    python: tuple = field(default_factory=lambda: tuple(sys.version_info[:3]))
    windows: bool = field(default_factory=lambda: sys.platform == "win32")
    has_module: Callable[[str], bool] = lambda name: importlib.util.find_spec(name) is not None
    engine_tag: Callable[[], str | None] = _engine_tag
    env_key: Callable[[], str | None] = lambda: (os.environ.get(KEY_NAME, "").strip() or None)
    store: object = field(default_factory=KeyringStore)
    list_windows: Callable[[], list[str]] = _list_windows
    is_blocked: Callable[[str], bool] = _is_blocked
    cards: Callable[[], list[str]] = _cards
    run: Callable[[list[str]], int] = _run
    ask: Callable[[str], str] = input
    secret: Callable[[str], str] = getpass.getpass
    forward: Callable[[str, list[str]], int] = _forward
    folder_exists: Callable[[Path], bool] = lambda path: (Path(path) / ".git").is_dir()


def is_tool(argv: list[str]) -> bool:
    return bool(argv) and argv[0] in TOOLS


def run(argv: list[str], env: Env | None = None, results: Path = RESULTS) -> int:
    env = env or Env()
    tool, rest = argv[0], argv[1:]
    if tool == "doctor":
        return doctor(env, fix="--fix" in rest, yes="--yes" in rest)
    if tool == "keys":
        return keys(env, rest[0] if rest else "status")
    if tool == "games":
        return games(env)
    if tool == "models":
        return models(env, results)
    if tool == "mcp":
        return env.forward("playfellow_coop.widget_mcp", rest)
    return stk(env, rest)


# ---- doctor --------------------------------------------------------------------------------------------------------------
def _key_source(env: Env) -> str | None:
    if env.env_key():
        return f"the environment variable {KEY_NAME}"
    try:
        return "the Windows credential manager" if env.store.get() else None
    except Exception:
        return None


def doctor(env: Env, fix: bool = False, yes: bool = False) -> int:
    say, problems, plan = env.out, 0, []
    say("PlayFellow doctor: checks this PC; sends nothing, calls no model.")
    major, minor = env.python[0], env.python[1]
    if (3, 11) <= (major, minor) <= (3, 13):
        say(f"  ok       Python {major}.{minor}.{env.python[2]}")
    else:
        problems += 1
        why = "3.14 and newer are too new for the engine's pygame" if (major, minor) > (3, 13) else f"this is {major}.{minor}"
        say(f"  MISSING  Python 3.11, 3.12 or 3.13 ({why}): install 3.13 from python.org, then run the bootstrap again")
    say("  ok       Windows" if env.windows else "  note     not Windows: tests and replays run here; playing a game needs Windows")
    engine_ok = all(env.has_module(m) for m in ENGINE_MODULES)
    if engine_ok:
        tag = env.engine_tag() or "installed (tag not checked)"
        say(f"  ok       PlayFellow engine ({tag})")
    else:
        problems += 1
        say(f"  MISSING  the PlayFellow engine (tag {ENGINE_TAG}): `doctor --fix` installs it from {engine_clone_dir()}")
        if not env.folder_exists(engine_clone_dir()):  # cloned before but not installed: only the install is missing
            plan.append(["git", "clone", "--depth", "1", "--branch", ENGINE_TAG, ENGINE_URL, str(engine_clone_dir())])
        plan.append([sys.executable, "-m", "pip", "install", "-e", str(engine_clone_dir())])
    missing = [pip for mod, pip in REQUIRED if not env.has_module(mod)]
    if missing:
        problems += 1
        say(f"  MISSING  packages: {', '.join(missing)}")
    else:
        say("  ok       packages (" + ", ".join(pip for _, pip in REQUIRED) + ")")
    optional_missing = []
    for mod, pip, use in OPTIONAL:
        if env.has_module(mod):
            say(f"  ok       {pip} ({use})")
        else:
            optional_missing.append(pip)
            say(f"  optional {pip} is not installed: needed for {use}")
    if missing or optional_missing:
        plan.append([sys.executable, "-m", "pip", "install", "-e", f"{REPO}[all]"])
    source = _key_source(env)
    if source:
        say(f"  ok       Meta key: set, from {source} (never shown)")
    else:
        say("  optional Meta key: not set. The built-in brain plays with no key; for Muse run `playfellow keys set`")
    titles = [t for t in env.list_windows() if not env.is_blocked(t)]
    say(f"  ok       {len(titles)} window(s) PlayFellow may play now; `playfellow games` lists them" if titles
        else "  note     no game window open yet: start your game, then `playfellow games`")
    if not plan:
        say("All set." if not problems else "")
        return 0 if not problems else 1
    if not fix:
        say("Run `playfellow doctor --fix` to install what is missing.")
        return 1 if problems else 0
    say("The fix will run:")
    for cmd in plan:
        say("  " + " ".join(cmd))
    if not yes and env.ask("Go ahead? [y/N] ").strip().lower() not in {"y", "yes"}:
        say("Nothing was changed.")
        return 1 if problems else 0
    for cmd in plan:
        if env.run(cmd) != 0:
            say("This step failed: " + " ".join(cmd))
            return 1
    say("Done. Run `playfellow doctor` once more to see everything green.")
    return 0


# ---- keys ----------------------------------------------------------------------------------------------------------------
def keys(env: Env, action: str) -> int:
    say = env.out
    if action == "set":
        value = (env.secret("Paste your Meta Model API key (hidden, stored in the Windows credential manager): ") or "").strip()
        if not value:
            say("No key given: nothing was stored.")
            return 1
        env.store.set(value)
        say("Stored in the Windows credential manager (service playfellow-coop). It is never printed, logged or sent anywhere but "
            "the pinned Meta API address.")
        return 0
    if action == "status":
        source = _key_source(env)
        say(f"Meta key: set, from {source}." if source else "Meta key: not set. Run `playfellow keys set` (on Windows, in the repository folder: .\\playfellow keys set).")
        return 0
    if action == "remove":
        env.store.delete()
        say("Removed from the Windows credential manager.")
        if env.env_key():
            say(f"The environment variable {KEY_NAME} still provides a key; clear it to remove that one too.")
        return 0
    say("Use: python -m playfellow_coop keys set | keys status | keys remove")
    return 2


# ---- games ---------------------------------------------------------------------------------------------------------------
def _card_for(title: str, cards: list[str]) -> str:
    plain = "".join(ch for ch in title.lower() if ch.isalnum())
    for card in cards:
        name = "".join(ch for ch in card.lower() if ch.isalnum())
        if not card.startswith("arena_") and name and name in plain:
            return card
    return "any_game"


def games(env: Env) -> int:
    say = env.out
    titles, seen = [], set()
    for title in env.list_windows():
        title = title.strip()
        if title and title not in seen and not env.is_blocked(title):
            seen.add(title)
            titles.append(title)
    if not titles:
        say("No game window is open. Start the game first, then run this again.")
        return 0
    cards = env.cards()
    say("Open windows PlayFellow may play (it presses keys only while the chosen one is in front):")
    for n, title in enumerate(titles, 1):
        card = _card_for(title, cards)
        say(f'  {n}. {title}\n       python -m playfellow_coop --window "{title}" --card {card} --overlay --assist --typed')
        if "supertuxkart" in title.lower():
            say("       python -m playfellow_coop stk --mission race --difficulty novice   (its own pack: minimap driving, menus, results)")
    say("any_game is the general controls card; add --brain muse with a key, and --input scancode for full-screen games.")
    return 0


# ---- models --------------------------------------------------------------------------------------------------------------
BRAINS = (
    ("builtin", "the engine's built-in brain", "no key, no network, $0", "python -m playfellow_coop --typed"),
    ("muse", "muse-spark-1.3 on the Meta Model API (default)", "needs a Meta key", "python -m playfellow_coop --brain muse"),
    ("local-open", "any open model on this PC through LM Studio", "no key, no network, $0", "python -m playfellow_coop --brain local-open --model <id>"),
)


BASELINES = {"none", "builtin-nav", "scripted-chooser"}


def _measured(results: Path) -> list[str]:
    rows = []
    for path in sorted(results.glob("*/*.json")):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, ValueError):
            continue
        overall = data.get("overall") if isinstance(data, dict) else None
        if not isinstance(overall, dict) or not data.get("model") or overall.get("cost_usd") is None:
            continue
        if data.get("void") or data["model"] in BASELINES:  # a void file is not a result; baselines are not brains
            continue
        episodes, wins = overall.get("episodes"), overall.get("wins")
        if not episodes:
            continue
        kind = "assisted" if overall.get("local_help_episodes") else "model alone"
        per_win = overall.get("usd_per_win")
        per = f", ${per_win:.4f} a win" if isinstance(per_win, (int, float)) else ""
        rows.append(f"  {data['model']:<36} {kind:<12} {wins} of {episodes} wins, ${overall['cost_usd']:.4f} in all{per}   "
                    f"({path.relative_to(results.parent).as_posix()})")
    return rows


def models(env: Env, results: Path) -> int:
    say = env.out
    say("Brains (--brain):")
    for name, what, cost, cmd in BRAINS:
        say(f"  {name:<11} {what}; {cost}\n              {cmd}")
    rows = _measured(results)
    if rows:
        say("Measured (committed result files; assisted = the model picks a pre-written skill):")
        for row in rows:
            say(row)
    return 0


# ---- stk -----------------------------------------------------------------------------------------------------------------
def stk(env: Env, rest: list[str]) -> int:
    if rest and rest[0] == "widget":
        return env.forward("playfellow_coop.games.stk.widget", rest[1:])
    return env.forward("playfellow_coop.games.stk.mission", rest)
