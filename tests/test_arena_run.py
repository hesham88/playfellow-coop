"""The headless arena benchmark: real turn loop, virtual screen and hands, honest per-episode numbers, Wilson intervals, no overwrite."""
from __future__ import annotations

import json
import os
from pathlib import Path

import pytest

from bench import arena_run as ar

ENGINE = Path(os.environ["PLAYFELLOW_ENGINE"])


def card_keys(game):
    import controls
    return list(controls.load_card(ENGINE / "controls" / f"arena_{game}.yaml").actions)


def test_wilson_interval_matches_known_values_and_handles_no_episodes():
    lo, hi = ar.wilson(5, 10)
    assert round(lo, 3) == 0.237 and round(hi, 3) == 0.763
    assert ar.wilson(0, 0) == (0.0, 1.0)
    lo, hi = ar.wilson(10, 10)
    assert hi == 1.0 and lo > 0.69


def test_a_random_brain_plays_a_real_episode_through_the_real_turn_loop_and_the_numbers_are_measured():
    keys = card_keys("snake")
    episode = ar.run_episode("snake", 0, ar.RandomBrain(keys), max_turns=12, max_calls=12, engine_dir=ENGINE)
    assert episode.turns >= 1 and episode.ticks >= 1          # keys reached the game: it ticked
    assert episode.ended in ("won", "lost", "turn_cap") and episode.seconds >= 0
    assert episode.invalid_plans == 0                        # the random brain sends valid JSON
    assert episode.progress is None or 0 <= episode.progress <= 1


def test_the_same_seed_gives_the_same_game_and_a_plan_that_is_not_on_the_card_does_nothing():
    class OffCard:
        last_request = {}

        def ask(self, system, text, images):
            return json.dumps({"thought": "x", "say": "", "actions": ["TELEPORT"]})

    a = ar.run_episode("snake", 3, OffCard(), max_turns=4, engine_dir=ENGINE)
    b = ar.run_episode("snake", 3, OffCard(), max_turns=4, engine_dir=ENGINE)
    assert (a.ticks, a.progress) == (b.ticks, b.progress) and a.ticks == 0 and a.invalid_plans == a.turns


def test_the_call_cap_ends_the_episode_and_tokens_and_cost_are_summed_from_the_brain():
    class Counting:
        def __init__(self, keys):
            self.keys, self.n, self.last_request = keys, 0, {}

        def ask(self, system, text, images):
            self.n += 1
            self.last_request = {"tokens_in": 100, "tokens_cached": 40, "tokens_out": 10, "cost_usd": 0.001}
            return json.dumps({"thought": "", "say": "", "actions": [self.keys[0]]})

    brain = Counting(card_keys("snake"))
    episode = ar.run_episode("snake", 0, brain, max_turns=50, max_calls=3, engine_dir=ENGINE)
    assert brain.n <= 3 and episode.tokens_in == 100 * brain.n and episode.tokens_cached == 40 * brain.n
    assert episode.cost_usd == pytest.approx(0.001 * brain.n)


def test_the_summary_and_the_results_file_say_what_was_measured_and_never_overwrite(tmp_path):
    eps = [ar.Episode("snake", i, won=i < 2, turns=10, tokens_in=500, tokens_out=50, cost_usd=0.002, seconds=3.0, progress=0.5) for i in range(5)]
    s = ar.summarise(eps)
    assert s["episodes"] == 5 and s["wins"] == 2 and s["win_rate"] == 0.4 and s["tokens_per_win"] == 1375.0 and s["usd_per_win"] == pytest.approx(0.005)
    out = tmp_path / "r.json"
    ar.write_results(out, "random", "random", "none", ["snake"], eps, note="test")
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["schema"] == "pf-arena-run/1" and doc["overall"]["wins"] == 2 and len(doc["episodes"]) == 5
    with pytest.raises(FileExistsError):
        ar.write_results(out, "random", "random", "none", ["snake"], eps)


def test_every_listed_game_loads_and_has_a_card():
    for key in ar.GAMES:
        assert ar.load_game(key, 0) is not None
        assert (ENGINE / "controls" / f"arena_{key}.yaml").is_file(), key


def test_progress_scores_are_zero_at_the_start_and_one_when_won_for_every_game(tmp_path):
    import os
    os.environ.setdefault("SDL_VIDEODRIVER", "dummy")
    for key in ar.PROGRESS:
        game = ar.load_game(key, 0)
        p0 = dict(game.progress())
        assert ar.PROGRESS[key](p0, game.progress()) == pytest.approx(0.0, abs=0.05), key


def test_a_random_run_now_reports_a_progress_number_not_none():
    keys = card_keys("snake")
    episode = ar.run_episode("snake", 0, ar.RandomBrain(keys), max_turns=15, engine_dir=ENGINE)
    assert episode.progress is not None and 0.0 <= episode.progress <= 1.0


def test_the_spend_cap_stops_before_the_next_model_call_and_sam_requests_are_counted():
    class FakeMarker:
        calls = 0

        def __call__(self, image):
            FakeMarker.calls += 2  # two phrases asked for this picture
            return []

    class Pricey:
        def __init__(self, keys):
            self.keys, self.last_request = keys, {}

        def ask(self, system, text, images):
            self.last_request = {"tokens_in": 10, "tokens_out": 5, "cost_usd": 0.03}
            return json.dumps({"thought": "", "say": "", "actions": [self.keys[0]]})

    episode = ar.run_episode("snake", 0, Pricey(card_keys("snake")), max_turns=20, max_calls=20, marker=FakeMarker(), engine_dir=ENGINE, max_usd=0.05)
    assert episode.ended == "cap" and episode.turns <= 2
    assert episode.extra["sam_requests"] == FakeMarker.calls and episode.cost_usd == pytest.approx(0.03 * episode.turns + FakeMarker.calls * 2.5 / 1000)


def test_a_skill_turn_counts_as_a_valid_plan_and_records_its_steps():
    episode = ar.run_episode("snake", 1, ar.ScriptedChooser("chase_food"), max_turns=2, max_calls=2, engine_dir=ENGINE, skills=True)
    assert episode.won and episode.invalid_plans == 0 and episode.extra["skill_steps"] > 50


def test_a_checkpoint_keeps_every_finished_episode_resumes_the_same_experiment_and_refuses_a_different_one(tmp_path):
    cfg = {"brain": "muse", "games": ["snake"], "seeds": 3, "turns": 5, "skills": True}
    path = tmp_path / "run.partial.jsonl"
    first = ar.Checkpoint(path, cfg)
    assert first.load() == []
    first.add(ar.Episode("snake", 0, won=True, cost_usd=0.004))
    first.add(ar.Episode("snake", 1, won=False, cost_usd=0.005))
    with open(path, "a", encoding="utf-8") as handle:
        handle.write('{"game": "snake", "seed": 2, "wo')  # a crash while writing the third line
    again = ar.Checkpoint(path, dict(cfg)).load()
    assert [(e.game, e.seed) for e in again] == [("snake", 0), ("snake", 1)] and again[0].won
    with pytest.raises(ValueError, match="different configuration"):
        ar.Checkpoint(path, {**cfg, "turns": 9}).load()
    assert ar.config_hash(cfg) == ar.config_hash(dict(reversed(list(cfg.items()))))  # the order of the settings does not matter
    ar.Checkpoint(path, cfg).finish()
    assert not path.exists()


def test_the_runner_writes_a_checkpoint_per_episode_and_removes_it_when_the_results_file_is_complete(tmp_path, monkeypatch):
    monkeypatch.setenv("PLAYFELLOW_ENGINE", str(ENGINE))
    from bench import run_condition
    out = tmp_path / "r.json"
    assert run_condition.main(["--brain", "random", "--games", "snake", "--seeds", "2", "--turns", "4", "--out", str(out), "--engine", str(ENGINE)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["overall"]["episodes"] == 2 and not (tmp_path / "r.json.partial.jsonl").exists()


def test_results_say_when_wins_had_local_skill_help_so_nobody_reports_them_as_the_model_alone(tmp_path):
    helped = ar.Episode("snake", 0, won=True, progress=1.0, extra={"skill_steps": 120})
    alone = ar.Episode("snake", 1, won=False, progress=0.2)
    summary = ar.summarise([helped, alone])
    assert summary["local_help_episodes"] == 1 and summary["skill_steps_total"] == 120
    out = tmp_path / "r.json"
    ar.write_results(out, "c", "b", "m", ["snake"], [helped, alone])
    assert "local help" in json.loads(out.read_text(encoding="utf-8"))["note"]
    plain = tmp_path / "p.json"
    ar.write_results(plain, "c", "b", "m", ["snake"], [alone])
    assert "local help" not in json.loads(plain.read_text(encoding="utf-8"))["note"]


def test_results_carry_the_rung_the_action_shares_and_an_interval_for_progress(tmp_path):
    helped = [ar.Episode("snake", i, won=True, progress=1.0, ticks=100, extra={"skill_steps": 90}) for i in range(3)]
    out = tmp_path / "h.json"
    ar.write_results(out, "c", "muse", "m", ["snake"], helped)
    honest = json.loads(out.read_text(encoding="utf-8"))["honesty"]
    assert honest["rung"]["key"] == "human_skills" and honest["label"] == "[Assisted: Human Local Skill]" and abs(honest["action_share"]["human_skill"] - 0.9) < 1e-9
    assert honest["progress_iqm"]["estimate"] == 1.0 and honest["progress_iqm"]["ci95"][0] <= 1.0
    raw = [ar.Episode("snake", i, progress=0.2, ticks=40) for i in range(3)]
    out2 = tmp_path / "r.json"
    ar.write_results(out2, "c", "muse", "m", ["snake"], raw)
    honest = json.loads(out2.read_text(encoding="utf-8"))["honesty"]
    assert honest["rung"]["key"] == "raw_paused" and honest["label"] == "[Model Alone]" and honest["action_share"]["model_chunk"] == 1.0
    out3 = tmp_path / "f.json"
    ar.write_results(out3, "c", "random", "none", ["snake"], raw)
    assert json.loads(out3.read_text(encoding="utf-8"))["honesty"]["label"] == "[Local floor: no model]"
