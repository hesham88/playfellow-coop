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
