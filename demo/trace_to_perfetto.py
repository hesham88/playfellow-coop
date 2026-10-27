"""Make a Perfetto-readable file from a pf-trace/1 file: python demo/trace_to_perfetto.py trace.jsonl out.json. Then open ui.perfetto.dev and choose Open trace file.
Nothing is uploaded."""
from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from playfellow_coop import trace_perfetto  # noqa: E402

if __name__ == "__main__":
    if len(sys.argv) != 3:
        sys.exit("usage: python demo/trace_to_perfetto.py trace.jsonl out.json")
    print(trace_perfetto.convert(sys.argv[1], sys.argv[2]), "events written to", sys.argv[2])
