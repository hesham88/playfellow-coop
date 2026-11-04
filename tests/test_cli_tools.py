"""The command tools: doctor, games, keys, models, stk. Every desktop, credential-store, pip and git touch is injected, so nothing
here opens a window, reads a real key, installs a package or reaches the network. The key is a sentinel that must never be printed."""
from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from playfellow_coop import cli_tools
from playfellow_coop.cli_tools import Env

SENTINEL = "pk-SENTINEL-do-not-print-0123456789"


class Store:
    def __init__(self, value=None):
        self.value = value

    def get(self):
        return self.value

    def set(self, value):
        self.value = value

    def delete(self):
        self.value = None


def env(**over) -> Env:
    lines: list[str] = []
    base = dict(out=lines.append, python=(3, 12, 1), windows=True, has_module=lambda name: True,
                engine_tag=lambda: "pre-hackathon", env_key=lambda: None, store=Store(), list_windows=lambda: [],
                is_blocked=lambda t: False, cards=lambda: ["any_game", "arena_snake", "platformer"],
                run=lambda cmd: pytest.fail(f"nothing may run here: {cmd}"), ask=lambda q: "n",
                secret=lambda q: pytest.fail("no secret prompt expected"), forward=lambda module, args: 0, folder_exists=lambda path: False)
    base.update(over)
    e = Env(**base)
    e.lines = lines
    return e


@pytest.fixture(autouse=True)
def _no_real_subprocess(monkeypatch):
    def refuse(*a, **k):
        raise AssertionError("a real subprocess was started")

    monkeypatch.setattr(subprocess, "run", refuse)
    monkeypatch.setattr(subprocess, "Popen", refuse)


def text(e: Env) -> str:
    return "\n".join(e.lines)


# ---- dispatch --------------------------------------------------------------------------------------------------------------
def test_tool_words_are_recognised_and_flags_are_not():
    assert cli_tools.is_tool(["doctor"]) and cli_tools.is_tool(["keys", "status"]) and cli_tools.is_tool(["stk"])
    assert not cli_tools.is_tool([]) and not cli_tools.is_tool(["--typed"]) and not cli_tools.is_tool(["--brain", "muse"])


def test_flags_still_reach_the_buddy():
    for argv in (["--assist", "--typed"], ["--assist", "4", "--keep", "j,k"], ["--window", "doctor"], ["--brain", "muse", "--overlay"]):
        assert not cli_tools.is_tool(argv), argv


def test_unknown_tool_usage_is_friendly():
    e = env()
    assert cli_tools.run(["keys", "nonsense"], e) == 2 and "keys set" in text(e)


# ---- doctor ----------------------------------------------------------------------------------------------------------------
def test_doctor_all_green():
    e = env(env_key=lambda: None, store=Store(SENTINEL), list_windows=lambda: ["SuperTuxKart", "Notepad"])
    assert cli_tools.run(["doctor"], e) == 0
    out = text(e)
    assert "Python 3.12" in out and "engine" in out.lower() and "pre-hackathon" in out and "credential manager" in out
    assert SENTINEL not in out and str(len(SENTINEL)) not in out


def test_doctor_names_what_is_missing_and_how_to_fix_it():
    e = env(has_module=lambda name: name not in {"play", "PySide6"}, engine_tag=lambda: None)
    assert cli_tools.run(["doctor"], e) == 1
    out = text(e)
    assert "engine" in out.lower() and "PySide6" in out and "doctor --fix" in out


def test_old_python_fails():
    e = env(python=(3, 10, 4))
    assert cli_tools.run(["doctor"], e) == 1 and "3.11" in text(e)


def test_doctor_fix_prints_the_plan_and_asks_before_changing_anything():
    ran = []
    e = env(has_module=lambda name: name not in {"play", "PySide6"}, engine_tag=lambda: None, ask=lambda q: "n", run=ran.append)
    cli_tools.run(["doctor", "--fix"], e)
    assert ran == [] and "git clone" in text(e) and "pip install" in text(e)


def test_doctor_fix_yes_runs_the_plan_through_the_injected_runner():
    ran = []
    e = env(has_module=lambda name: name not in {"play", "PySide6"}, engine_tag=lambda: None, run=lambda cmd: ran.append(cmd) or 0)
    cli_tools.run(["doctor", "--fix", "--yes"], e)
    joined = [" ".join(map(str, c)) for c in ran]
    assert any("git clone" in c and "pre-hackathon" in c for c in joined)
    assert any("pip install" in c and "[all]" in c for c in joined)


def test_doctor_on_another_os_says_play_needs_windows():
    e = env(windows=False)
    cli_tools.run(["doctor"], e)
    assert "Windows" in text(e)


# ---- keys ------------------------------------------------------------------------------------------------------------------
def test_keys_set_reads_hidden_and_never_prints_the_key(capsys):
    store = Store()
    e = env(store=store, secret=lambda q: SENTINEL)
    assert cli_tools.run(["keys", "set"], e) == 0
    assert store.value == SENTINEL
    captured = capsys.readouterr()
    assert SENTINEL not in text(e) and SENTINEL not in captured.out and SENTINEL not in captured.err


def test_keys_set_refuses_an_empty_key():
    store = Store()
    e = env(store=store, secret=lambda q: "   ")
    assert cli_tools.run(["keys", "set"], e) == 1 and store.value is None


def test_keys_status_names_only_the_source():
    e = env(store=Store(SENTINEL))
    cli_tools.run(["keys", "status"], e)
    out = text(e)
    assert "credential manager" in out and SENTINEL not in out and SENTINEL[-4:] not in out and str(len(SENTINEL)) not in out


def test_keys_status_when_nothing_is_set():
    e = env()
    cli_tools.run(["keys", "status"], e)
    assert "not set" in text(e) and "keys set" in text(e)


def test_keys_remove_says_when_the_environment_still_provides_one():
    store = Store(SENTINEL)
    e = env(store=store, env_key=lambda: SENTINEL)
    assert cli_tools.run(["keys", "remove"], e) == 0
    assert store.value is None and "MODEL_API_KEY" in text(e) and SENTINEL not in text(e)


def test_the_real_store_uses_the_same_entry_as_the_buddy():
    from playfellow_coop import __main__ as entry

    assert entry.KEY_NAME == cli_tools.KEY_NAME == "MODEL_API_KEY"
    assert entry.KEYRING_SERVICE == cli_tools.KEYRING_SERVICE == "playfellow-coop"


# ---- games -----------------------------------------------------------------------------------------------------------------
def test_games_lists_playable_windows_with_a_start_command():
    e = env(list_windows=lambda: ["SuperTuxKart", "Secret Bank Login", "Celeste"], is_blocked=lambda t: "Bank" in t,
            cards=lambda: ["any_game", "celeste", "platformer"])
    assert cli_tools.run(["games"], e) == 0
    out = text(e)
    assert "SuperTuxKart" in out and "Celeste" in out and "Bank" not in out
    assert '--window "Celeste" --card celeste' in out and '--window "SuperTuxKart" --card any_game' in out
    assert "python -m playfellow_coop stk" in out  # SuperTuxKart has its own pack


def test_games_with_nothing_open_says_start_the_game_first():
    e = env()
    cli_tools.run(["games"], e)
    assert "start the game first" in text(e).lower()


# ---- models ----------------------------------------------------------------------------------------------------------------
def test_models_lists_the_brains_and_measured_costs_from_result_files(tmp_path):
    (tmp_path / "fifteen").mkdir()
    (tmp_path / "fifteen" / "x.json").write_text(
        '{"model": "meta-models/muse-spark-open-1026", "condition": "open-none", "overall": {"episodes": 15, "wins": 15, "cost_usd": 0.03772, "usd_per_win": 0.00251, "local_help_episodes": 15}}',
        encoding="utf-8")
    (tmp_path / "fifteen" / "void.json").write_text(
        '{"model": "muse-spark-1.3", "void": "billing failed", "overall": {"episodes": 15, "wins": 0, "cost_usd": 0.0}}', encoding="utf-8")
    (tmp_path / "fifteen" / "random.json").write_text(
        '{"model": "none", "overall": {"episodes": 40, "wins": 0, "cost_usd": 0.0}}', encoding="utf-8")
    e = env()
    assert cli_tools.run(["models"], e, results=tmp_path) == 0
    assert "void" not in text(e) and "0 of 15" not in text(e) and "0 of 40" not in text(e)
    out = text(e)
    assert "builtin" in out and "muse-spark-1.3" in out and "local-open" in out and "LM Studio" in out
    assert "15 of 15" in out and "0.0025" in out and "assisted" in out


# ---- stk -------------------------------------------------------------------------------------------------------------------
def test_stk_forwards_to_the_mission_with_every_argument():
    seen = []
    e = env(forward=lambda module, args: seen.append((module, args)) or 0)
    assert cli_tools.run(["stk", "--mission", "race", "--difficulty", "novice"], e) == 0
    assert seen == [("playfellow_coop.games.stk.mission", ["--mission", "race", "--difficulty", "novice"])]


def test_stk_widget_forwards_to_the_widget_alone():
    seen = []
    e = env(forward=lambda module, args: seen.append((module, args)) or 0)
    cli_tools.run(["stk", "widget"], e)
    assert seen == [("playfellow_coop.games.stk.widget", [])]


def test_the_engine_clone_goes_beside_this_repository():
    assert cli_tools.engine_clone_dir().parent == Path(cli_tools.__file__).resolve().parents[2]


def test_python_3_14_is_named_as_too_new():
    e = env(python=(3, 14, 4))
    assert cli_tools.run(["doctor"], e) == 1 and "pygame" in text(e)


def test_doctor_fix_does_not_clone_over_an_existing_engine_folder():
    ran = []
    e = env(has_module=lambda name: name != "play", engine_tag=lambda: None, run=lambda cmd: ran.append(cmd) or 0, folder_exists=lambda path: True)
    cli_tools.run(["doctor", "--fix", "--yes"], e)
    joined = [" ".join(map(str, c)) for c in ran]
    assert not any("git clone" in c for c in joined) and any("pip install -e" in c and "playfellow" in c for c in joined)
