"""The entry point wires F9 and F12, chooses the brain, and finds the key only in the environment or the credential manager."""
from __future__ import annotations

import os
from pathlib import Path

import pytest

from brain import BrainError
from playfellow_coop import __main__ as entry
from playfellow_coop.handover import HandOver
from playfellow_coop.muse_brain import MuseBrain


class Parts:
    def __init__(self):
        import controls

        self.brain = "builtin-brain"
        self.card = controls.load_card(Path(os.environ["PLAYFELLOW_ENGINE"]) / "controls" / "practice_arena.yaml")
        self.hands = type("H", (), {"on_stop": lambda s: None, "resume": lambda s: None})()
        self.safety = type("S", (), {"stopped": False, "calls": 0, "stop": lambda s, r: setattr(s, "stopped", True)})()


def test_f9_and_f12_are_registered_and_f9_toggles_the_hand_over():
    parts, said, keys, stops = Parts(), [], {}, []
    seen = {}

    def build(argv):
        import settings

        return parts, settings.Settings()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        seen["handover"] = handover
        keys["f9"]()  # the player presses F9: takes over
        assert handover.human_has_controls
        keys["f9"]()  # and again: gives back, and the summary is said
        return "round_done"

    code = entry.main([], build_fn=build, listen_key=lambda name, cb: keys.__setitem__(name, cb),
                      listen_stop=lambda cb: stops.append(cb), run=run, say=said.append)
    assert code == 0 and "f9" in keys and len(stops) == 1
    assert any("Back with me" in line for line in said) and isinstance(seen["handover"], HandOver)
    assert any("It's yours" in line for line in said)  # the take-over line is said too


def test_a_missing_key_is_a_friendly_stop_not_a_crash():
    said = []

    def build(argv):
        raise BrainError("no_key")

    assert entry.main([], build_fn=build, say=said.append) == 2 and said


def test_the_muse_brain_is_used_only_when_asked_and_needs_a_key(tmp_path):
    import settings

    def parts_builder(cfg):
        return Parts()

    brain_less, _ = entry.build([], build_parts=parts_builder, key_loader=lambda: None)
    assert brain_less.brain == "builtin-brain"
    with pytest.raises(BrainError) as caught:
        entry.build(["--brain", "muse"], build_parts=parts_builder, key_loader=lambda: None)
    assert caught.value.key == "no_key"
    parts, _ = entry.build(["--brain", "muse", "--budget-file", str(tmp_path / "b.json")], build_parts=parts_builder,
                           key_loader=lambda: "unique-key-VALUE-9")
    assert isinstance(parts.brain, MuseBrain) and "unique-key-VALUE-9" not in repr(parts.brain)
    parts.brain.close()
    assert settings is not None


def test_the_key_comes_from_the_environment_and_from_no_file(monkeypatch):
    monkeypatch.setenv("MODEL_API_KEY", "  env-key  ")
    assert entry.load_muse_key() == "env-key"
    monkeypatch.delenv("MODEL_API_KEY")
    monkeypatch.setattr("keyring.get_password", lambda service, name: "vault-key")
    assert entry.load_muse_key() == "vault-key"
    monkeypatch.setattr("keyring.get_password", lambda service, name: None)
    assert entry.load_muse_key() is None


# ---- --marks sam|fake|off ------------------------------------------------------------------------------------------
def _parts_builder(cfg):
    return Parts()


def test_marks_are_off_by_default_and_nothing_is_attached():
    parts, _ = entry.build([], build_parts=_parts_builder, key_loader=lambda: None)
    assert parts.marks_source == "off" and not hasattr(parts, "marker")


def test_sam_marks_need_a_key_and_a_marker_is_attached_when_there_is_one(tmp_path):
    with pytest.raises(BrainError) as caught:
        entry.build(["--marks", "sam", "--budget-file", str(tmp_path / "b.json")], build_parts=_parts_builder, key_loader=lambda: None)
    assert caught.value.key == "no_key"
    from playfellow_coop.sam_marks import SamMarker

    parts, _ = entry.build(["--marks", "sam", "--budget-file", str(tmp_path / "b.json")], build_parts=_parts_builder,
                           key_loader=lambda: "unique-key-VALUE-7")
    assert isinstance(parts.marker, SamMarker) and "unique-key-VALUE-7" not in repr(parts.marker) and parts.marks_source == "sam"
    parts.marker.close()


def test_fake_marks_start_a_local_server_and_are_said_loudly_at_the_start_and_the_end(tmp_path, monkeypatch):
    from playfellow_coop import sam_marks

    monkeypatch.setitem(sam_marks.ENDPOINTS, "sam", sam_marks.ENDPOINTS["sam"])  # restored afterwards
    said, ran = [], {}
    parts_holder = {}

    def build(argv):
        parts, cfg = entry.build(["--marks", "fake", "--budget-file", str(tmp_path / "b.json")], build_parts=_parts_builder,
                                 key_loader=lambda: None)
        parts_holder["parts"] = parts
        ran["endpoint"] = sam_marks.ENDPOINTS["sam"]
        return parts, cfg

    import settings

    code = entry.main([], build_fn=lambda argv: (lambda p_c: (p_c[0], settings.Settings()))(build(argv)),
                      listen_key=lambda name, cb: None, listen_stop=lambda cb: None,
                      run=lambda *a, **k: "round_done", say=said.append)
    banner = [line for line in said if line.startswith("FAKE MARKS ON")]
    assert code == 0 and len(banner) == 2 and "NOT SAM output" in banner[0]
    assert ran["endpoint"].startswith("http://127.0.0.1:")  # the fake lives on this PC; it never talks to Meta
    parts_holder["parts"].marker.close()


def test_a_fake_marks_bench_run_is_labelled_a_diagnostic_and_names_its_marks(tmp_path):
    import json

    from playfellow_coop import bench
    from tests.test_session_and_handover import Brain, make

    parts, cfg = make(Brain())
    parts.marks_source = "fake"
    path = bench.run_bench(parts, cfg, "system", 2, tmp_path, "builtin", "none", git=("a" * 40, False), wait=lambda s: False)
    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["metrics"]["marks"] == "fake" and data["metrics"]["label"] == "diagnostic: FAKE marks, not SAM output"

# ---- the gaps found in review: SAM on by default with the Muse brain; the hand-over lines are spoken -----------------------
def test_the_muse_brain_turns_sam_marks_on_unless_told_otherwise(tmp_path):
    from playfellow_coop.sam_marks import SamMarker

    common = ["--budget-file", str(tmp_path / "b.json")]
    parts, _ = entry.build(["--brain", "muse", *common], build_parts=_parts_builder, key_loader=lambda: "unique-key-VALUE-5")
    assert parts.marks_source == "sam" and isinstance(parts.marker, SamMarker)
    parts.marker.close()
    parts.brain.close()
    off, _ = entry.build(["--brain", "muse", "--marks", "off", *common], build_parts=_parts_builder, key_loader=lambda: "unique-key-VALUE-5")
    assert off.marks_source == "off" and not hasattr(off, "marker")
    off.brain.close()


def test_the_hand_over_confirmations_are_said_out_loud_not_dropped():
    parts, said = Parts(), []

    def build(argv):
        import settings

        return parts, settings.Settings()

    def run(p, cfg, system, timer, handover, on_event, commands=None, latency=None):
        on_event("say", "I've got it.")  # what the session emits when the player hands a part over
        on_event("say", "")  # an empty line is not said
        on_event("thought", "private reasoning")  # thoughts stay out of the voice
        return "round_done"

    assert entry.main([], build_fn=build, listen_key=lambda n, cb: None, listen_stop=lambda cb: None, run=run, say=said.append) == 0
    assert "I've got it." in said and "private reasoning" not in said and said.count("") == 0

# ---- --brain local-open: an open model on THIS PC through the engine's LM Studio brain (its memory check included) ----------
def test_local_open_uses_the_engines_lm_studio_brain_needs_no_key_and_a_model_name():
    from brain.lmstudio import LMStudioBrain

    parts, _ = entry.build(["--brain", "local-open", "--model", "some-open-model"], build_parts=_parts_builder, key_loader=lambda: None)
    assert isinstance(parts.brain, LMStudioBrain) and parts.brain.model == "some-open-model"
    assert parts.marks_source == "off" and not hasattr(parts, "marker")  # SAM costs money and needs a key: only on request
    with pytest.raises(BrainError) as caught:
        entry.build(["--brain", "local-open"], build_parts=_parts_builder, key_loader=lambda: None)
    assert "--model" in caught.value.friendly()


def test_the_muse_brain_still_defaults_to_its_own_model_name(tmp_path):
    parts, _ = entry.build(["--brain", "muse", "--marks", "off", "--budget-file", str(tmp_path / "b.json")], build_parts=_parts_builder,
                           key_loader=lambda: "unique-key-VALUE-3")
    assert parts.brain.model == "muse-spark"
    parts.brain.close()
