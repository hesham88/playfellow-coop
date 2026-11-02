"""The accessibility benchmark runs the real assist and split-controls code on a game from pixels, and a breach is impossible to miss."""
from __future__ import annotations

from bench import access_bench as ab
from bench import arena_run as ar


def _load(seed):
    return ar.load_game("snake", seed)


def test_an_assisted_part_is_judged_by_the_games_own_progress_and_says_so():
    e = ab.episode("snake", 0, "assist", _load, requests=1, part_turns=300)
    part = e["parts"][0]
    assert set(part) >= {"request", "done", "ended", "turns", "actions", "done_by"}
    assert e["breaches"] == 0 and e["refused"] == 0
    if part["done"]:
        assert part["done_by"] == "game_progress"
    assert part["actions"] <= part["turns"] <= 300


def test_a_kept_key_never_reaches_the_game_and_every_attempt_is_counted():
    key = ar.load_game("snake", 0).keys[0]
    e = ab.episode("snake", 0, "split", _load, requests=1, part_turns=200, owned=[key])
    assert e["owned"] == [key] and e["key_use"][key] == 0 and e["breaches"] == 0


def test_the_summary_counts_breaches_and_gives_an_interval():
    episodes = [ab.episode("snake", 0, c, _load, requests=1, part_turns=60) for c in ("assist", "random")]
    rows = ab.summarise(episodes)
    assert rows["assist/ALL"]["breaches"] == 0 and len(rows["assist/ALL"]["done_rate_95"]) == 2
    assert ab.wilson(0, 0) == (0.0, 0.0) and ab.wilson(5, 5)[1] == 1.0
