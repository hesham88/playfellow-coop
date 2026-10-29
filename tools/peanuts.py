"""Draft the hierarchy of README.md files (the elephant's food, docs/egm.md): one per package folder, one line per file, taken from each module's own first docstring line.

    python tools/peanuts.py [--write] [--force]

Without --write it only prints what it would write. An existing README.md is never overwritten unless --force: a README that a person has corrected is better than a regenerated one.
"""
from __future__ import annotations

import argparse
import ast
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
FOLDERS = ["playfellow_coop", "bench", "train", "deploy", "tests"]


def first_line(path: Path) -> str:
    try:
        doc = ast.get_docstring(ast.parse(path.read_text(encoding="utf-8")))
    except (SyntaxError, UnicodeDecodeError):
        doc = None
    if not doc:
        return "(no description yet: write one)"
    first_paragraph = doc.strip().split(chr(10) * 2)[0]
    paragraph = " ".join(first_paragraph.split())  # the whole first paragraph, on one line
    cut = paragraph.find(". ")
    sentence = paragraph if cut < 0 else paragraph[: cut + 1]
    return sentence if len(sentence) <= 240 else sentence[:237].rsplit(" ", 1)[0] + "..."


def readme_for(folder: Path) -> str:
    files = sorted(p for p in folder.iterdir() if p.suffix == ".py" and p.name != "__init__.py")
    init = folder / "__init__.py"
    purpose = first_line(init) if init.exists() and ast.get_docstring(ast.parse(init.read_text(encoding="utf-8") or "")) else f"The `{folder.name}` folder."
    lines = [f"# {folder.name}", "", purpose, "", "## Files", ""]
    lines += [f"- `{p.name}`: {first_line(p)}" for p in files]
    subs = sorted(d for d in folder.iterdir() if d.is_dir() and d.name != "__pycache__" and (d / "__init__.py").exists())
    if subs:
        lines += ["", "## Folders", ""] + [f"- `{d.name}/`: see its README.md" for d in subs]
    return "\n".join(lines) + "\n"


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--write", action="store_true")
    parser.add_argument("--force", action="store_true")
    args = parser.parse_args()
    folders = []
    for name in FOLDERS:
        base = ROOT / name
        if base.is_dir():
            folders.append(base)
            folders += sorted(d for d in base.rglob("*") if d.is_dir() and d.name != "__pycache__" and any(p.suffix == ".py" for p in d.iterdir()))
    for folder in folders:
        target = folder / "README.md"
        if target.exists() and not args.force:
            print(f"keep   {target.relative_to(ROOT)}")
            continue
        text = readme_for(folder)
        print(f"{'write' if args.write else 'would'} {target.relative_to(ROOT)} ({text.count(chr(10))} lines)")
        if args.write:
            target.write_text(text, encoding="utf-8", newline="\n")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
