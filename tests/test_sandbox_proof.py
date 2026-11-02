"""The sandbox proof for the judges: planted hostile skills through the real 3-layer path, each row naming the layer that stopped it, plus harmless skills that must pass. Any hostile row that gets through fails here first."""
from __future__ import annotations

import json

from bench.sandbox_proof import LAYERS, main, run_proof


def test_every_hostile_skill_is_stopped_and_named_with_its_layer_and_three_harmless_ones_pass():
    doc = run_proof()
    assert doc["all_stopped"] is True
    hostile = {row["name"]: row for row in doc["rows"]}
    for name in ("open a socket", "write a file outside the folder", "start a child process", "import os",
                 "import subprocess", "import ctypes", "read an environment variable", "loop forever",
                 "allocate past the memory cap", "call eval", "call exec", "walk frames to escape"):
        assert hostile[name]["stopped"] is True, name
        assert hostile[name]["layer"] in LAYERS and hostile[name]["ms"] >= 0, name
    assert hostile["import os"]["layer"] == "static gate"
    assert hostile["loop forever"]["layer"] != "static gate"  # a bounded-looking loop only the running layers can stop
    assert {row["name"] for row in doc["harmless"]} == {"chase the nearest item", "stay still", "use numpy to steer"}
    assert all(row["passed"] is True for row in doc["harmless"])


def test_the_proof_writes_its_table_and_fails_loudly_when_a_row_gets_through(tmp_path, monkeypatch):
    out = tmp_path / "proof.json"
    assert main(["--out", str(out)]) == 0
    doc = json.loads(out.read_text(encoding="utf-8"))
    assert doc["rows"] and doc["harmless"]
    import bench.sandbox_proof as proof

    monkeypatch.setitem(proof.HOSTILE, "loop forever", proof.HARMLESS["stay still"])
    assert main(["--out", str(tmp_path / "proof2.json")]) == 1  # a hostile row that gets through fails the run
