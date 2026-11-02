"""Fetch the open-source games the benchmarks play, each at a pinned commit, into a cache folder outside the repository (nothing is committed).

    python bench/fetch_osg.py [--dir F:/PlayFellow/dev/cache/osg]

2048 by Gabriele Cirulli, MIT licence: https://github.com/gabrielecirulli/2048"""
from __future__ import annotations

import argparse
import subprocess
from pathlib import Path

GAMES = {"2048": ("https://github.com/gabrielecirulli/2048.git", "478b6ec346e3787f589e4af751378d06ded4cbbc")}


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--dir", default=r"F:\PlayFellow\dev\cache\osg")
    args = ap.parse_args(argv)
    root = Path(args.dir)
    root.mkdir(parents=True, exist_ok=True)
    for name, (url, commit) in GAMES.items():
        folder = root / name
        if not folder.exists():
            subprocess.run(["git", "clone", "-q", url, str(folder)], check=True)
        subprocess.run(["git", "-C", str(folder), "checkout", "-q", commit], check=True)
        head = subprocess.run(["git", "-C", str(folder), "rev-parse", "HEAD"], capture_output=True, text=True, check=True).stdout.strip()
        print(name, head, "OK" if head == commit else "NOT THE PINNED COMMIT")
        if head != commit:
            return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
