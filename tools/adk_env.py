"""AD1: make and check the ADK environment, a virtual environment of its own (the app never imports ADK: it costs seconds at start-up and many packages).

    python tools/adk_env.py --venv <folder>                 create it if missing, install the pins, check them, write the lock beside the pins
    python tools/adk_env.py --venv <folder> --from-lock     reproduce the exact resolved set from the lock instead
    python tools/adk_env.py --venv <folder> --check         only check: ADK at the pinned version, and our package imports there without loading ADK
    add --pip-cache <folder> to keep pip's downloads on a drive of your choice

Then run the ADK side with that environment's python, for example `<folder>/Scripts/python -m pytest tests/test_adk_app.py`.
The folder must be outside this repository and must not be the environment running this script (that would put ADK into it).
"""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
PINS = ROOT / "playfellow_coop" / "adk_app" / "requirements-adk.txt"
LOCK = PINS.with_suffix(".lock")
PIN = re.compile(r"^\s*([A-Za-z0-9_.\-]+)\s*==\s*([A-Za-z0-9_.\-+]+)\s*$")


def pinned(path: Path = PINS) -> dict[str, str]:
    """The exact pins (`name==version`) of a requirements file; ranges are not pins."""
    out = {}
    for line in path.read_text(encoding="utf-8").splitlines():
        match = PIN.match(line.split("#", 1)[0])
        if match:
            out[match.group(1).lower()] = match.group(2)
    return out


def python_of(venv: Path) -> Path:
    return venv / ("Scripts/python.exe" if os.name == "nt" else "bin/python")


def refusal(venv: Path, root: Path = ROOT, running_prefix: str = sys.prefix) -> str:
    """Why this folder must not become the ADK environment ("" when it may)."""
    target = venv.resolve()
    if target == Path(running_prefix).resolve():
        return "that is the environment running this script: ADK would go into it"
    if target == root.resolve() or root.resolve() in target.parents:
        return "the environment must live outside this repository"
    return ""


def _run(args: list, env: dict | None = None) -> subprocess.CompletedProcess:
    return subprocess.run([str(a) for a in args], capture_output=True, text=True, env=env)


def check(venv: Path) -> list[str]:
    """Problems with the environment ([] when it is right): ADK at the pinned version, and importing our package there does not load ADK."""
    python = python_of(venv)
    if not python.is_file():
        return [f"no python at {python}"]
    problems = []
    want = pinned()["google-adk"]
    got = _run([python, "-c", "import importlib.metadata as m, google.adk; print(m.version('google-adk'))"])
    if got.returncode != 0 or got.stdout.strip() != want:
        problems.append(f"google-adk is {got.stdout.strip() or 'missing'}, the pin is {want}")
    lazy = _run([python, "-c", f"import sys; sys.path.insert(0, {str(ROOT)!r}); import playfellow_coop.adk_app.agents; print('google.adk' in sys.modules)"])
    if lazy.stdout.strip().splitlines()[-1:] != ["False"]:
        problems.append("importing playfellow_coop.adk_app loads ADK at once (it must load only when an episode is built)")
    return problems


def install(venv: Path, from_lock: bool = False, pip_cache: Path | None = None) -> int:
    reason = refusal(venv)
    if reason:
        print(f"refused: {reason}")
        return 2
    env = dict(os.environ)
    if pip_cache:
        env["PIP_CACHE_DIR"] = str(pip_cache)
    if not python_of(venv).is_file():
        made = _run([sys.executable, "-m", "venv", venv])
        if made.returncode != 0:
            print(made.stderr[-500:])
            return 1
    source = LOCK if from_lock else PINS
    done = _run([python_of(venv), "-m", "pip", "install", "-r", source], env=env)
    if done.returncode != 0:
        print(done.stdout[-1500:], done.stderr[-1500:])
        return 1
    if not from_lock:
        frozen = _run([python_of(venv), "-m", "pip", "freeze", "--exclude-editable"]).stdout
        LOCK.write_text(f"# Written by tools/adk_env.py from {PINS.name}: the exact set the ADK environment resolved to (Python "
                        f"{_run([python_of(venv), '-c', 'import sys; print(sys.version.split()[0])']).stdout.strip()}, {sys.platform}).\n" + frozen,
                        encoding="utf-8", newline="\n")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Make or check the ADK environment (AD1).")
    parser.add_argument("--venv", type=Path, required=True)
    parser.add_argument("--check", action="store_true")
    parser.add_argument("--from-lock", action="store_true")
    parser.add_argument("--pip-cache", type=Path, default=None)
    args = parser.parse_args(argv)
    if not args.check:
        code = install(args.venv, args.from_lock, args.pip_cache)
        if code:
            return code
    problems = check(args.venv)
    for problem in problems:
        print(f"problem: {problem}")
    if not problems:
        print(f"ok: google-adk {pinned()['google-adk']} in {args.venv}; our package loads ADK only when an episode is built")
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())
