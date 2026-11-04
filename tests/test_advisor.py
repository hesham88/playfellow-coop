"""The models' part: what comes back is checked before anything acts on it."""
from playfellow_coop.games.advisor import allowed_key, parse_json, summarise_fight

KEYS = frozenset({"enter", "esc", "d", "l"})


def test_only_a_key_on_the_list_goes_out_whatever_the_model_says():
    assert allowed_key({"key": "Enter"}, KEYS) == "enter"
    assert allowed_key({"key": "q"}, KEYS) is None
    assert allowed_key({"key": "none"}, KEYS) is None
    assert allowed_key({}, KEYS) is None


def test_the_json_is_found_in_a_chatty_answer_and_nonsense_gives_nothing():
    assert parse_json('Sure! {"screen": "bank", "key": "d"} done') == {"screen": "bank", "key": "d"}
    assert parse_json("no json here") == {}
    assert parse_json("{broken") == {}
    assert parse_json("") == {}


def row(r, sh, hl, ts, th):
    return {"range": r, "shields": sh, "hull": hl, "target_shields": ts, "target_hull": th}


def test_a_fight_is_summed_up_in_a_few_numbers():
    s = summarise_fight([row(1000, 1.0, 0.9, 1.0, 0.9), row(200, 0.5, 0.9, 0.6, 0.9), row(400, 0.3, 0.8, 0.2, 0.5), {"range": None}], 510)
    assert (s.rows, s.closest, s.farthest) == (3, 200, 1000)
    assert s.my_shields == (1.0, 0.3) and s.target_hull == (0.9, 0.5)
    assert s.share_in_range == 0.67


def test_no_fight_no_summary():
    assert summarise_fight([], 510) is None
    assert summarise_fight([{"range": None}], 510) is None
