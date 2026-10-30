"""PlayFellow on Google ADK: the guardrails are plain functions, the episode graph runs on ADK's real runner with fakes and with a real game, and importing the package does not load ADK."""
from __future__ import annotations

import importlib.util
import subprocess
import sys

import pytest

from playfellow_coop.adk_app.agents import Deps, run_episode
from playfellow_coop.adk_app.callbacks import MAX_HOLD_MS, episode_should_stop, guard_action


def _has_adk() -> bool:
    try:
        return importlib.util.find_spec("google.adk") is not None
    except ModuleNotFoundError:
        return False


# ADK is never installed into the app's environment (AD1). These tests run in the ADK environment: `python tools/adk_env.py --venv <folder>`, then that python.
NEEDS_ADK = pytest.mark.skipif(not _has_adk(), reason="ADK lives in its own environment (AD1): run with the python of `tools/adk_env.py --venv <folder>`")


# ---- guardrails (no ADK needed) -----------------------------------------------------------------------------------------------------
def test_the_guard_drops_keys_off_the_card_cleans_opposites_and_raises_holds_that_are_too_short():
    state = {"allowed_keys": ["left", "right", "up", "space"], "socd_mode": "neutral", "fps": 60}
    safe, notes = guard_action({"keys": ["left", "right", "up", "format_disk"], "hold_ms": 5}, state)
    assert safe["keys"] == ["up"] and safe["hold_ms"] >= 34 and len(notes) == 3
    assert any("not on the controls card" in n for n in notes) and any("opposite" in n for n in notes) and any("shorter than two frames" in n for n in notes)
    safe, notes = guard_action({"keys": ["space"], "hold_ms": 99999}, state)
    assert safe["hold_ms"] == MAX_HOLD_MS and any("cut to" in n for n in notes)
    safe, notes = guard_action({"keys": ["up"], "hold_ms": 45, "click": [1500, -3]}, state)
    assert safe["click"] == [1000.0, 0.0] and any("clamped" in n for n in notes)
    many, notes = guard_action({"keys": ["q", "e", "r", "f", "g", "h", "j", "k"], "hold_ms": 0}, {})
    assert len(many["keys"]) == 6 and any("more than 6 keys" in n for n in notes)


def test_the_guard_presses_nothing_into_a_window_that_is_not_in_front_and_remembers_press_order_for_last_input_mode():
    safe, notes = guard_action({"keys": ["up", "left"], "hold_ms": 100}, {"focus_ok": False})
    assert safe == {"keys": [], "hold_ms": 0} and "not in front" in notes[0]
    state = {"allowed_keys": ["left", "right"], "socd_mode": "last_input"}
    first, _ = guard_action({"keys": ["left"]}, state)
    second, _ = guard_action({"keys": ["left", "right"]}, state)
    assert first["keys"] == ["left"] and second["keys"] == ["right"]  # right went down last


def test_the_loop_exit_rule():
    assert episode_should_stop({"episode_terminated": True}) and episode_should_stop({"player_has_controls": True}) and episode_should_stop({"stop_requested": True})
    assert episode_should_stop({"step": 5, "max_steps": 5}) and not episode_should_stop({"step": 1, "max_steps": 5})


# ---- the graph on ADK's real runner -------------------------------------------------------------------------------------------------
@NEEDS_ADK
def test_an_episode_runs_perceive_route_decide_act_watch_in_a_loop_and_the_watcher_ends_it():
    pressed, grabs = [], []

    def grab():
        grabs.append(len(grabs))
        return {"n": len(grabs)}

    def watch(state):
        return {"episode_terminated": state.get("step", 0) >= 4}

    deps = Deps(grab=grab, perceive_hud=lambda f: {"score": f["n"]}, perceive_space=lambda f: {"x": 1}, perceive_entities=lambda f: {"enemies": 0},
                route=lambda s: ("reflex", ["stable"]), decide=lambda tier, s: {"keys": ["left", "right", "up"], "hold_ms": 50}, act=pressed.append, watch=watch,
                initial_state={"allowed_keys": ["left", "right", "up"], "socd_mode": "neutral", "fps": 60}, max_steps=50)
    result = run_episode(deps)
    assert result["episode_terminated"] and result["step"] == 4 and len(pressed) == 4 and len(grabs) == 4
    assert all(p["keys"] == ["up"] for p in pressed)  # left and right cancelled out in code, outside any prompt
    assert result["tier"] == "reflex" and result["hud"] == {"score": 4} and result["events"] >= 4 * 6
    assert any("opposite" in n for n in result["guard_notes"])


@NEEDS_ADK
def test_the_step_budget_ends_an_episode_nobody_wins_and_a_player_takeover_ends_it_at_once():
    deps = Deps(grab=lambda: {}, max_steps=3)
    assert run_episode(deps)["step"] == 3
    taken = Deps(grab=lambda: {}, max_steps=50, initial_state={"player_has_controls": True})
    result = run_episode(taken)
    assert result["step"] == 1 and result["episode_terminated"]  # one pass, then the watcher sees the player has the controls


@NEEDS_ADK
def test_a_real_game_is_played_through_the_graph_with_a_local_skill_as_the_decider():
    from bench import arena_run as ar
    from playfellow_coop.gym import PlayfellowGym
    from playfellow_coop.skills.paddle_track import TrackPaddle

    env = PlayfellowGym("brick_breaker", lambda s: ar.load_game("brick_breaker", s), seed=0)
    frame, _ = env.reset()
    skill = TrackPaddle()
    skill.reset()
    box = {"frame": frame, "done": False}

    def decide(tier, state):
        key = skill.next_key(box["frame"])
        return {"keys": [key] if key else [], "hold_ms": 0}

    def act(safe):
        key = safe["keys"][0] if safe["keys"] else None
        box["frame"], _, terminated, truncated, _ = env.step(key)
        box["done"] = terminated or truncated

    deps = Deps(grab=lambda: box["frame"], decide=decide, act=act, watch=lambda s: {"episode_terminated": box["done"]}, max_steps=250,
                initial_state={"allowed_keys": ["left", "right", "space"], "socd_mode": "neutral", "fps": 60})
    result = run_episode(deps)
    assert result["step"] == 250 and env.card().progress > 0.0 and result["pressed"] is not None  # the ball was launched and bricks fell: a real game, played through ADK


# ---- ADK is loaded only when needed -------------------------------------------------------------------------------------------------
def test_importing_the_package_does_not_load_adk():
    root = str(__import__("pathlib").Path(__file__).resolve().parents[1])
    code = ("import sys; sys.path.insert(0, %r); import playfellow_coop.adk_app, playfellow_coop.adk_app.callbacks, playfellow_coop.adk_app.agents; print('google.adk' in sys.modules)" % root)
    out = subprocess.run([sys.executable, "-c", code], capture_output=True, text=True, timeout=120)
    assert out.stdout.strip().splitlines()[-1] == "False", out.stderr[-300:]
