#!/usr/bin/env sh
# PlayFellow co-op: install on Linux or macOS, for the offline tests and the key-free replays.
# Playing a game needs Windows (the buddy reads a Windows game window and presses keys there); use bootstrap.ps1 there.
#   sh bootstrap.sh
# Python 3.11 to 3.13: the engine's pygame has no build for 3.14 yet.
set -e
repo=$(cd "$(dirname "$0")" && pwd)
engine="$(dirname "$repo")/playfellow"
python=""
for candidate in python3.13 python3.12 python3.11 python3; do
  # the version must fit AND be able to make a virtual environment (Debian's system Python often lacks ensurepip)
  if command -v "$candidate" >/dev/null 2>&1 && "$candidate" -c 'import sys, ensurepip, venv; sys.exit(0 if (3, 11) <= sys.version_info[:2] <= (3, 13) else 1)' 2>/dev/null; then
    python="$candidate"; break
  fi
done
[ -n "$python" ] || { echo "PlayFellow needs Python 3.11, 3.12 or 3.13 with venv (3.14 is too new for the engine's pygame; on Debian/Ubuntu: apt install python3-venv)."; exit 1; }
[ -d "$repo/.venv" ] || "$python" -m venv "$repo/.venv"
py="$repo/.venv/bin/python"
[ -d "$engine/.git" ] || git clone --depth 1 --branch pre-hackathon https://github.com/hesham88/playfellow.git "$engine"
"$py" -m pip install --upgrade pip --quiet
"$py" -m pip install -e "$engine" --quiet
"$py" -m pip install -e "$repo" pytest setuptools --quiet
(cd "$repo" && "$py" -m playfellow_coop doctor) || true
echo
echo "Next: ./playfellow doctor, and .venv/bin/python -m pytest -q for the offline tests (play itself needs Windows)"
