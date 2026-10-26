"""Run the speed bench: `python bench/speed_bench.py --brain builtin --turns 30`.

It plays the chosen game window for real (so the Practice Arena must be open and in front) and writes one pf-results/1 file into
bench/results/. Run it with a quiet PC; the file labels a dirty working tree as a diagnostic."""
from __future__ import annotations

import argparse
import sys
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE.parent))

import play  # noqa: E402

from meta_playfellow.__main__ import build  # noqa: E402
from meta_playfellow.bench import run_bench  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Time every stage of the composed loop and write one results file.")
    parser.add_argument("--turns", type=int, default=30)
    parser.add_argument("--out", type=Path, default=HERE / "results")
    args, rest = parser.parse_known_args(argv)  # the rest goes to the game and brain options of `python -m meta_playfellow`
    parts, cfg = build(rest)
    brain = "muse" if "muse" in rest else "builtin"
    path = run_bench(parts, cfg, play.system_for(parts, cfg), args.turns, args.out, brain, getattr(parts.brain, "model", "none"))
    print(path)
    return 0


if __name__ == "__main__":
    sys.exit(main())
