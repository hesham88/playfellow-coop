"""The replay recorder: a raw session log (pf-session-log/1, JSON lines) becomes a pf-replay/1 module for the web page.

The one rule that matters: the recorder writes kind "real" ONLY for a real brain (muse, local-open) with real SAM marks from the pinned
address, and a log that cannot prove it is refused. Fixtures here are a FAKE-brain run and are only ever written as kind "sample"."""
from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "demo"))
import record_replay as rr  # noqa: E402
from playfellow_coop import session_log  # noqa: E402

WEB = Path(__file__).resolve().parents[1] / "demo" / "web"
PINNED = rr.PINNED_MARKS_ENDPOINT  # the code's own constant, not a typed host
assert PINNED.startswith("https://")


def header(**changes):
    base = {"type": "header", "schema": "pf-session-log/1", "brain": "muse", "model": "muse-spark", "marks": "sam", "marks_endpoint": PINNED,
            "fake_server": False, "commit": "abcdef0123", "recorded": "2026-10-28", "level": "garden"}
    base.update(changes)
    return {k: v for k, v in base.items() if v is not None}


def turn(**changes):
    base = {"type": "turn", "say": "On my way.", "marks": [{"tag": "R1", "kind": "reward", "x": 100, "y": 200}], "actions": ["down"]}
    base.update(changes)
    return base


def write_log(tmp_path, head, turns, name="session.jsonl"):
    path = tmp_path / name
    path.write_text("".join(json.dumps(line) + "\n" for line in [head, *turns]), encoding="utf-8")
    return path


def fake_head(**changes):
    return header(brain="fake", model="fake-brain", marks="fake", marks_endpoint="http://127.0.0.1:5000", fake_server=True, **changes)


def read_module(path):
    text = Path(path).read_text(encoding="utf-8")
    assert text.count("export default ") == 1
    return json.loads(text.split("export default ", 1)[1].rstrip().rstrip(";"))


# ---- real recordings ---------------------------------------------------------------------------------------------
def test_a_real_muse_run_with_sam_marks_becomes_a_real_recording(tmp_path):
    log = write_log(tmp_path, header(), [turn(), turn(say="", actions=["right", "right"])])
    out = tmp_path / "replay.mjs"
    rr.record(log, out)
    rec = read_module(out)
    assert rec["schema"] == "pf-replay/1" and rec["level"] == "garden"
    assert rec["source"] == {"kind": "real", "brain": "muse-spark", "commit": "abcdef0123", "recorded": "2026-10-28", "marks_from": "sam-3.1"}
    assert [s["actions"] for s in rec["steps"]] == [["down"], ["right", "right"]]
    assert rec["steps"][0] == {"say": "On my way.", "marks": [{"tag": "R1", "kind": "reward", "x": 100, "y": 200}], "actions": ["down"]}


def test_a_local_open_model_is_real_too_and_says_so(tmp_path):
    log = write_log(tmp_path, header(brain="local-open", model="qwen2.5-vl-7b"), [turn()])
    rec = rr.build(rr.read_log(log))
    assert rec["source"]["kind"] == "real" and rec["source"]["brain"] == "local-open:qwen2.5-vl-7b"


@pytest.mark.parametrize("changes", [
    {"brain": "builtin"}, {"brain": "fake"}, {"brain": "scripted"}, {"brain": "anything-else"},
    {"marks": "fake"}, {"marks": "off"}, {"marks": None},
    {"marks_endpoint": "http://127.0.0.1:5000"}, {"marks_endpoint": PINNED + "/"}, {"marks_endpoint": None},
    {"fake_server": True}, {"fake_server": None}, {"fake_server": "no"},
    {"commit": None}, {"commit": "not-a-hash"}, {"recorded": None}, {"recorded": "yesterday"},
    {"model": None}, {"level": "nowhere"}, {"schema": "pf-session-log/9"},
])
def test_a_log_that_cannot_prove_it_is_real_is_refused_as_real(tmp_path, changes):
    log = write_log(tmp_path, header(**changes), [turn()])
    with pytest.raises(rr.Refused):
        rr.build(rr.read_log(log))
    out = tmp_path / "replay.mjs"
    with pytest.raises(rr.Refused):
        rr.record(log, out)
    assert not out.exists()  # nothing is written when the recorder refuses


def test_a_fake_brain_run_is_never_written_as_real_even_when_asked_nicely(tmp_path):
    log = write_log(tmp_path, fake_head(), [turn()])
    with pytest.raises(rr.Refused):
        rr.record(log, tmp_path / "replay.mjs")  # no --sample: refused
    with pytest.raises(rr.Refused):
        rr.build(rr.read_log(log), kind="real")


def test_real_marks_from_a_fake_server_on_a_real_brain_are_refused(tmp_path):
    log = write_log(tmp_path, header(marks_endpoint="http://localhost:8123", fake_server=True), [turn()])
    with pytest.raises(rr.Refused):
        rr.build(rr.read_log(log))


# ---- sample recordings -------------------------------------------------------------------------------------------
def test_a_fake_run_is_written_as_a_sample_with_no_brain_claims(tmp_path):
    log = write_log(tmp_path, fake_head(), [turn()])
    out = tmp_path / "sample.mjs"
    rr.record(log, out, sample=True)
    rec = read_module(out)
    assert rec["source"] == {"kind": "sample"}


def test_a_sample_never_goes_to_the_pages_own_recording_file(tmp_path):
    log = write_log(tmp_path, fake_head(), [turn()])
    with pytest.raises(rr.Refused):
        rr.record(log, rr.DEFAULT_OUT, sample=True)


def test_a_real_run_cannot_be_relabelled_a_sample(tmp_path):
    log = write_log(tmp_path, header(), [turn()])
    with pytest.raises(rr.Refused):
        rr.record(log, tmp_path / "x.mjs", sample=True)  # the label must match what the run was, both ways


# ---- coordinates, marks, actions ---------------------------------------------------------------------------------
def test_coordinates_are_rounded_and_clamped_to_0_1000_and_bad_marks_are_dropped(tmp_path):
    marks = [{"tag": "A", "kind": "me", "x": 1200, "y": -5}, {"tag": "B", "kind": "reward", "x": 499.6, "y": 0.4},
             {"tag": "C", "kind": "door", "x": float("nan"), "y": 1}, {"tag": "D", "kind": "door", "x": "5", "y": 1},
             {"tag": "E", "kind": "dragon", "x": 1, "y": 1}, {"tag": "LONGERTHANSIX", "kind": "hazard", "x": 3, "y": 4},
             {"kind": "me", "x": 1, "y": 1}, "junk", None]
    rec = rr.build(rr.read_log(write_log(tmp_path, header(), [turn(marks=marks)])))
    assert rec["steps"][0]["marks"] == [{"tag": "A", "kind": "me", "x": 1000, "y": 0}, {"tag": "B", "kind": "reward", "x": 500, "y": 0},
                                        {"tag": "LONGER", "kind": "hazard", "x": 3, "y": 4}]


def test_at_most_32_marks_per_step_are_kept(tmp_path):
    marks = [{"tag": f"R{i}", "kind": "reward", "x": i, "y": i} for i in range(40)]
    rec = rr.build(rr.read_log(write_log(tmp_path, header(), [turn(marks=marks)])))
    assert len(rec["steps"][0]["marks"]) == 32


def test_an_action_off_the_card_or_too_many_actions_refuse_the_log(tmp_path):
    for bad in (["teleport"], ["up"] * 9, "up", [1]):
        with pytest.raises(rr.Refused):
            rr.build(rr.read_log(write_log(tmp_path, header(), [turn(actions=bad)])))


def test_actions_are_lowercased_and_a_turn_with_no_keys_is_kept(tmp_path):
    rec = rr.build(rr.read_log(write_log(tmp_path, header(), [turn(actions=["UP"]), turn(actions=[])])))
    assert [s["actions"] for s in rec["steps"]] == [["up"], []]


def test_a_log_with_no_turns_or_too_many_turns_is_refused(tmp_path):
    with pytest.raises(rr.Refused):
        rr.build(rr.read_log(write_log(tmp_path, header(), [])))
    with pytest.raises(rr.Refused):
        rr.build(rr.read_log(write_log(tmp_path, header(), [turn()] * 2001)))


# ---- privacy -----------------------------------------------------------------------------------------------------
def test_nothing_private_ends_up_in_the_output(tmp_path):
    path_text = "C:" + "\\Users\\zed\\Desktop\\notes.txt"
    key_text = "sk-" + "a1b2c3d4e5f6" * 3
    extra = {"thought": "THOUGHT-SECRET", "prompt": "PROMPT-SECRET", "image": "IMAGE-SECRET", "path": path_text, "api_key": key_text,
             "user": "zed", "text": "TEXT-SECRET"}
    turns = [turn(say="Hi from " + path_text, **extra), turn(say="mail me at zed@example.com"), turn(say="key " + key_text),
             turn(say="Zed says go"), turn(say="Going up now.")]
    head = header(**{"api_key": key_text, "prompt": "HEAD-PROMPT-SECRET", "host": "ZED-PC"})
    out = tmp_path / "replay.mjs"
    rr.record(write_log(tmp_path, head, turns), out, private_words=["Zed"])
    text = out.read_text(encoding="utf-8")
    for needle in ("SECRET", "zed", "Zed", "ZED", "sk-", "Users", "@", ":\\"):
        assert needle not in text
    rec = read_module(out)
    assert [s["say"] for s in rec["steps"]] == ["", "", "", "", "Going up now."]  # a line with anything private is dropped whole
    assert set(rec) == {"schema", "source", "level", "steps"} and set(rec["steps"][0]) == {"say", "marks", "actions"}


def test_a_private_looking_header_value_refuses_the_log(tmp_path):
    for changes in ({"model": "C:" + "\\Users\\zed\\m.gguf"}, {"model": "x@y.com"}, {"model": "a" * 100}):
        with pytest.raises(rr.Refused):
            rr.build(rr.read_log(write_log(tmp_path, header(brain="local-open", **changes), [turn()])))


def test_the_default_private_words_include_the_os_user_name(monkeypatch, tmp_path):
    monkeypatch.setattr(session_log.getpass, "getuser", lambda: "Quentin")
    rec = rr.build(rr.read_log(write_log(tmp_path, header(), [turn(say="quentin is here")])))
    assert rec["steps"][0]["say"] == ""


def test_a_long_line_is_cut_to_what_the_player_accepts(tmp_path):
    rec = rr.build(rr.read_log(write_log(tmp_path, header(), [turn(say="go " * 100)])))
    assert len(rec["steps"][0]["say"]) <= 140


# ---- the file itself ---------------------------------------------------------------------------------------------
def test_the_output_is_a_deterministic_js_module_and_the_write_is_whole(tmp_path):
    log = write_log(tmp_path, header(), [turn()])
    one, two = tmp_path / "one.mjs", tmp_path / "two.mjs"
    rr.record(log, one)
    rr.record(log, two)
    assert one.read_bytes() == two.read_bytes()
    assert one.read_text(encoding="utf-8").startswith("//")  # it says it was written by the recorder
    assert list(tmp_path.glob("*.tmp")) == []


def test_a_broken_log_is_refused_not_crashed_on(tmp_path):
    bad = tmp_path / "bad.jsonl"
    bad.write_text("not json\n", encoding="utf-8")
    with pytest.raises(rr.Refused):
        rr.record(bad, tmp_path / "x.mjs")
    with pytest.raises(rr.Refused):
        rr.record(tmp_path / "missing.jsonl", tmp_path / "x.mjs")


def test_the_command_line_refuses_with_a_message_and_exit_2_and_writes_nothing(tmp_path, capsys):
    log = write_log(tmp_path, fake_head(), [turn()])
    out = tmp_path / "x.mjs"
    assert rr.main([str(log), "--out", str(out)]) == 2
    assert "refus" in capsys.readouterr().out.lower() and not out.exists()
    assert rr.main([str(log), "--out", str(out), "--sample"]) == 0 and out.exists()


def test_the_committed_sample_fixture_is_what_the_recorder_makes_from_the_committed_fake_run(tmp_path):
    out = tmp_path / "recorded_sample.mjs"
    rr.record(WEB / "fixtures" / "sample_session.jsonl", out, sample=True)
    assert out.read_bytes() == (WEB / "fixtures" / "recorded_sample.mjs").read_bytes()
