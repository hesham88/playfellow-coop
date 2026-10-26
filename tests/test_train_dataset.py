"""T-1: the training data. Made only from the game's own state and hand-written phrases; every row says where each part came from; no row holds
any model's output; the held-out part shares no level and no phrase with training; the plans are exactly right. No network, no model."""
import json
import os
import re
from pathlib import Path

import pytest

from train import dataset as ds
from practice_arena.game import ArenaGame

ROOT = Path(__file__).resolve().parents[1]


@pytest.fixture(scope="module")
def rows():
    return ds.generate(60, 30)


# provenance: the data rule ----------------------------------------------------------------------------------------------------------------

def test_every_row_names_where_each_part_came_from(rows):
    for row in rows:
        p = row["provenance"]
        assert p["frame"] == "game state" and p["plan"].startswith("scripted baseline") and p["command"] == "hand-written templates"
        assert p["model_output"] is False and p["models"] == []


def test_every_generated_row_passes_the_validator(rows):
    for row in rows:
        ds.validate_row(row)


def good(rows):
    return json.loads(json.dumps(rows[0]))


@pytest.mark.parametrize("change", [
    lambda r: r["provenance"].pop("plan"),
    lambda r: r["provenance"].update(plan="asked a model"),
    lambda r: r["provenance"].update(frame="a screenshot from a store"),
    lambda r: r["provenance"].update(command="written by a model"),
    lambda r: r["provenance"].update(model_output=True),
    lambda r: r["provenance"].update(models=["some-model"]),
    lambda r: r.pop("provenance"),
    lambda r: r.update(provenance="game state"),
    lambda r: r.update(schema="pf-train/0"),
    lambda r: r.update(split="validation"),
    lambda r: r.update(language="fr"),
    lambda r: r.update(intent="boss"),
    lambda r: r.update(completion="not json"),
    lambda r: r.update(completion=json.dumps({"thought": "x", "say": "y", "actions": ["JUMP"]})),
    lambda r: r.update(completion=json.dumps({"thought": "x", "say": "y", "actions": ["UP"] * 4})),
    lambda r: r.update(completion=json.dumps({"thought": "x", "actions": []})),
])
def test_the_validator_refuses_a_row_that_breaks_the_rule(rows, change):
    row = good(rows)
    change(row)
    with pytest.raises(ds.BadRow):
        ds.validate_row(row)


@pytest.mark.parametrize("name", ["Muse Spark said", "from Gemini", "Claude wrote this", "an OpenAI answer", "GPT output", "Llama", "Glimmer 30B",
                                  "Meta API"])
def test_a_row_that_names_a_model_or_vendor_anywhere_is_refused(rows, name):
    for field in ("command", "prompt"):
        row = good(rows)
        row[field] = row[field] + " " + name
        with pytest.raises(ds.BadRow):
            ds.validate_row(row)
    row = good(rows)
    row["completion"] = json.dumps({"thought": name, "say": "", "actions": []})
    with pytest.raises(ds.BadRow):
        ds.validate_row(row)


def test_a_row_with_a_file_path_is_refused(rows):
    row = good(rows)
    row["prompt"] += " see C:\\somewhere\\file.txt"
    with pytest.raises(ds.BadRow):
        ds.validate_row(row)


def test_a_file_with_a_repeated_id_or_a_bad_row_is_refused(rows, tmp_path):
    path = tmp_path / "x.jsonl"
    path.write_text(json.dumps(rows[0]) + "\n" + json.dumps(rows[0]) + "\n", encoding="utf-8")
    with pytest.raises(ds.BadRow):
        ds.validate_file(path)
    bad = good(rows)
    bad["provenance"]["model_output"] = True
    path.write_text(json.dumps(bad) + "\n", encoding="utf-8")
    with pytest.raises(ds.BadRow):
        ds.validate_file(path)


def test_nothing_is_written_when_a_row_is_bad(tmp_path, monkeypatch):
    def broken(train, heldout):
        row = ds.build_row(1, "coins", "en", 0)
        row["provenance"]["model_output"] = True
        return [row]

    monkeypatch.setattr(ds, "generate", broken)
    with pytest.raises(ds.BadRow):
        ds.write_dataset(tmp_path / "out", 1, 0)
    assert not (tmp_path / "out").exists()


def test_the_data_makers_never_call_a_model_or_the_network():
    import ast
    tree = ast.parse((ROOT / "train" / "dataset.py").read_text(encoding="utf-8"))
    imported = set()
    for node in ast.walk(tree):
        if isinstance(node, ast.Import):
            imported |= {a.name.split(".")[0] for a in node.names}
        elif isinstance(node, ast.ImportFrom):
            imported.add((node.module or "").split(".")[0])
    assert not imported & {"urllib", "http", "httpx", "requests", "socket", "ssl", "websockets", "subprocess", "brain", "ollama", "keyring"}
    assert not any(name.startswith("playfellow_coop.muse") or name.endswith("muse_brain") for name in imported)


# held-out: nothing shared with training -----------------------------------------------------------------------------------------------------

def test_held_out_rows_use_other_levels_and_other_phrases(rows):
    train = [r for r in rows if r["split"] == "train"]
    held = [r for r in rows if r["split"] == "heldout"]
    assert len(train) == 60 and len(held) == 30
    assert not {r["frame"]["seed"] for r in train} & {r["frame"]["seed"] for r in held}
    assert all(ds.is_heldout_seed(r["frame"]["seed"]) for r in held) and not any(ds.is_heldout_seed(r["frame"]["seed"]) for r in train)
    indexes = lambda rs: {(r["language"], r["intent"], int(r["id"].rsplit("-p", 1)[1])) for r in rs}  # noqa: E731
    assert all(ds.is_heldout_phrase(i) for _, _, i in indexes(held)) and not any(ds.is_heldout_phrase(i) for _, _, i in indexes(train))


def test_the_held_out_phrases_never_appear_in_a_training_command(rows):
    held_text = {p for by in ds.PHRASES.values() for items in by.values() for i, p in enumerate(items) if ds.is_heldout_phrase(i)}
    train_commands = " | ".join(r["command"] for r in rows if r["split"] == "train")
    for phrase in held_text:
        assert phrase not in train_commands


def test_every_phrase_list_has_a_held_out_phrase_in_both_languages():
    for language, by in ds.PHRASES.items():
        for intent, items in by.items():
            assert any(ds.is_heldout_phrase(i) for i in range(len(items))) and any(not ds.is_heldout_phrase(i) for i in range(len(items)))


def test_the_held_out_hash_is_stable_and_changes_when_the_set_changes(rows):
    first = ds.heldout_hash(rows)
    assert first == ds.heldout_hash(list(reversed(rows))) == ds.heldout_hash(ds.generate(60, 30))
    assert first != ds.heldout_hash(ds.generate(60, 31))
    changed = json.loads(json.dumps(rows))
    for row in changed:
        if row["split"] == "heldout":
            row["id"] += "x"
            break
    assert first != ds.heldout_hash(changed)


def test_the_hash_covers_the_phrases_too(rows, monkeypatch):
    first = ds.heldout_hash(rows)
    monkeypatch.setitem(ds.PHRASES["en"], "coins", ds.PHRASES["en"]["coins"][:3] + ["a new held-out phrase"] + ds.PHRASES["en"]["coins"][4:])
    assert ds.heldout_hash(rows) != first


# the plans are exactly right -----------------------------------------------------------------------------------------------------------------

def replay(row):
    game = ArenaGame()
    for key in row["frame"]["walk"]:
        game.press(key)
    return game


def distance(game, goals):
    found = ds.route(game, goals)
    return None if found is None else len(found[0])


def test_the_keys_are_on_the_controls_card_and_the_card_is_the_engines(rows):
    from controls import load_card
    card = load_card(Path(os.environ["PLAYFELLOW_ENGINE"]) / "controls" / "practice_arena.yaml")
    assert set(ds.ALLOWED) == set(card.actions)
    for row in rows:
        assert set(json.loads(row["completion"])["actions"]) <= set(ds.ALLOWED)


def test_the_completion_is_accepted_by_the_engines_own_reply_check(rows):
    from controls import load_card
    from reply import parse_reply
    card = load_card(Path(os.environ["PLAYFELLOW_ENGINE"]) / "controls" / "practice_arena.yaml")
    for row in rows:
        reply = parse_reply(row["completion"], card, 8)
        assert not reply.confused and reply.dropped == [] and len(reply.steps) == len(json.loads(row["completion"])["actions"]), row["id"]


def test_every_plan_walks_toward_its_target_one_square_per_key_without_a_bump(rows):
    for row in rows:
        game = replay(row)
        reply, tile = ds.plan_for(game, row["intent"], row["language"])
        assert reply == json.loads(row["completion"])
        if not reply["actions"]:
            continue
        avoid = frozenset({game.key} if game.key and row["intent"] != "key" else ())
        before = len(ds.route(game, {tile}, avoid=avoid)[0])
        moves, bumps = game.moves, game.bumps  # the seeded walk before the frame may have bumped; only the plan's own keys count
        for action in reply["actions"]:
            game.press(action.lower())
        after = 0 if game.player == tile else len(ds.route(game, {tile}, avoid=avoid)[0])
        assert game.bumps == bumps and game.moves == moves + len(reply["actions"]) and after == before - len(reply["actions"]), row["id"]


def test_a_plan_is_the_start_of_a_shortest_walk():
    game = ArenaGame()
    reply, tile = ds.plan_for(game, "key", "en")
    full, end = ds.route(game, {game.key})
    assert tile == end == game.key and reply["actions"] == full[:ds.MAX_STEPS]


def test_the_locked_door_gets_an_honest_sentence_and_no_keys():
    game = ArenaGame()
    for language in ("en", "ar"):
        reply, tile = ds.plan_for(game, "door", language)
        assert reply["actions"] == [] and tile is None and reply["say"] == ds.SAY[language]["locked"]


def test_with_the_key_in_hand_the_door_is_a_target_and_the_key_command_says_so():
    game = ArenaGame()
    for key in ds.route(game, {game.key})[0]:
        game.press(key.lower())
    assert game.has_key
    reply, tile = ds.plan_for(game, "door", "en")
    assert tile == game.door and reply["actions"]
    reply, tile = ds.plan_for(game, "key", "en")
    assert reply["actions"] == [] and reply["say"] == ds.SAY["en"]["have_key"]


def test_no_coins_left_is_said_plainly():
    game = ArenaGame()
    game.coins.clear()
    reply, tile = ds.plan_for(game, "coins", "ar")
    assert reply["actions"] == [] and tile is None and reply["say"] == ds.SAY["ar"]["none"]


def test_walking_to_a_coin_does_not_pick_up_the_key_on_the_way():
    for seed in range(1, 40):
        game, _ = ds.make_state(seed)
        had = game.has_key
        reply, _tile = ds.plan_for(game, "coins", "en")
        for key in reply["actions"]:
            game.press(key.lower())
        assert game.has_key == had, seed


def test_the_target_label_is_the_one_the_picture_shows(rows):
    for row in rows:
        reply = json.loads(row["completion"])
        if reply["actions"]:
            assert row["target_tag"] and row["target_tag"] in {m["tag"] for m in row["marks"]}
            assert f"[{row['target_tag']}]" in row["prompt"]
        else:
            assert row["target_tag"] is None


# the commands and the languages ------------------------------------------------------------------------------------------------------------------

def test_both_languages_and_all_three_intents_are_in_the_data(rows):
    assert {r["language"] for r in rows} == {"en", "ar"} and {r["intent"] for r in rows} == {"coins", "key", "door"}


def test_arabic_rows_are_arabic_and_marked_not_yet_checked_by_a_native_speaker(rows):
    for row in rows:
        if row["language"] == "ar":
            assert any("\u0600" <= c <= "\u06ff" for c in row["command"]) and any("\u0600" <= c <= "\u06ff" for c in json.loads(row["completion"])["say"])
            assert row["provenance"]["arabic_checked_by_native_speaker"] is False
        else:
            assert row["provenance"]["arabic_checked_by_native_speaker"] is None and not any("\u0600" <= c <= "\u06ff" for c in row["command"])


def test_the_commands_vary_with_fillers_and_slips_but_stay_recognisable(rows):
    english = [r["command"] for r in rows if r["language"] == "en"]
    assert len(set(english)) > len(english) // 2
    assert any(c.startswith(("please ", "ok buddy,", "hey,", "quick,")) for c in english)


# determinism, files and the manifest -------------------------------------------------------------------------------------------------------------

def test_the_same_numbers_give_the_same_rows():
    assert ds.generate(20, 10) == ds.generate(20, 10)


def test_ids_are_unique_across_both_parts(rows):
    assert len({r["id"] for r in rows}) == len(rows)


def test_the_files_the_manifest_and_the_counts(tmp_path):
    manifest = ds.write_dataset(tmp_path / "out", 24, 12)
    assert manifest["rows"] == {"train": 24, "heldout": 12} and manifest["model_output_rows"] == 0
    assert manifest["arabic_checked_by_native_speaker"] is False and len(manifest["heldout_sha256"]) == 64
    assert ds.validate_file(tmp_path / "out" / "train.jsonl") == 24 and ds.validate_file(tmp_path / "out" / "heldout.jsonl") == 12
    on_disk = json.loads((tmp_path / "out" / "manifest.json").read_text(encoding="utf-8"))
    assert on_disk == manifest
    assert on_disk["heldout_sha256"] == ds.heldout_hash(ds.generate(24, 12))


def test_no_row_in_the_files_has_a_local_path_or_a_key(tmp_path):
    ds.write_dataset(tmp_path / "out", 24, 12)
    pattern = re.compile(r"[A-Za-z]:[\\/]+(Users|PlayFellow)\b|AIza[0-9A-Za-z_\-]{30,}|\bsk-[A-Za-z0-9_\-]{20,}|pdl_(live|sdbx)_|@[a-z0-9.-]+\.[a-z]{2,}", re.I)
    for name in ("train.jsonl", "heldout.jsonl", "manifest.json"):
        assert not pattern.search((tmp_path / "out" / name).read_text(encoding="utf-8"))


def test_pictures_are_written_once_per_level_when_asked(tmp_path):
    ds.write_dataset(tmp_path / "out", 12, 6, images=True)
    pictures = list((tmp_path / "out" / "frames").glob("*.png"))
    assert pictures and len(pictures) <= 18


def test_the_command_line_writes_the_set_and_says_so(tmp_path, capsys):
    assert ds.main(["--out", str(tmp_path / "o"), "--train", "12", "--heldout", "6"]) == 0
    assert "12 training rows, 6 held-out rows" in capsys.readouterr().out
    assert (tmp_path / "o" / "manifest.json").is_file()


def test_the_scripted_baseline_is_named_as_a_teacher_and_never_as_the_buddys_play():
    text = (ROOT / "train" / "dataset.py").read_text(encoding="utf-8")
    assert "teacher for training labels ONLY" in text and "never shown as the buddy playing" in text
    assert ds.PROVENANCE["plan"] == "scripted baseline (teacher for labels only)"


def test_the_generator_is_not_imported_by_anything_that_plays():
    for path in (ROOT / "playfellow_coop").rglob("*.py"):
        assert not re.search(r"^\s*(from|import)\s+train\b", path.read_text(encoding="utf-8"), re.MULTILINE), path.name
