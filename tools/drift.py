"""Drift report (the plugin's egm-drift-report idea): do the files a design document names still exist, and does the tree hold code the document never mentions?

    python tools/drift.py docs/designs/gegaa-wave/design.md [--package playfellow_coop/universal --package playfellow_coop/skillsmith ...]

Exit code 0 when every named file exists; 1 when any is missing. Files in the listed packages that no backticked name in the document refers to are printed as "not covered" (a note, not a failure).
"""
from __future__ import annotations

import argparse
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
NAME = re.compile(r"`([A-Za-z0-9_./-]+\.(?:py|md|yaml|json))`")


def named_files(text: str) -> list[str]:
    return sorted(set(NAME.findall(text)))


def exists(name: str) -> bool:
    if (ROOT / name).exists():
        return True
    prefixes = ["playfellow_coop", "playfellow_coop/universal", "playfellow_coop/skillsmith", "playfellow_coop/evalkit", "playfellow_coop/harness", "tests", "bench", "docs"]
    return any((ROOT / p / name).exists() for p in prefixes)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("document")
    parser.add_argument("--package", action="append", default=[])
    args = parser.parse_args()
    text = (ROOT / args.document).read_text(encoding="utf-8")
    private = {n for line in text.splitlines() if line.startswith("Private repository") for n in named_files(line)}  # files of the other repository are named but not checked here
    names = [n for n in named_files(text) if n not in private]
    missing = [n for n in names if not exists(n)]
    print(f"{len(names)} files named, {len(missing)} missing")
    for n in missing:
        print(f"  MISSING {n}")
    for package in args.package:
        for path in sorted((ROOT / package).glob("*.py")):
            if path.name != "__init__.py" and path.name not in text:
                print(f"  not covered: {package}/{path.name}")
    return 1 if missing else 0


if __name__ == "__main__":
    raise SystemExit(main())
