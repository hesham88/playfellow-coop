#!/usr/bin/env sh
# PlayFellow co-op: the one-line install for Linux and macOS (the offline tests and the key-free replays; play needs Windows).
#   curl -fsSL https://raw.githubusercontent.com/hesham88/playfellow-coop/main/install.sh | sh
# Clones this repository (default: ~/PlayFellow/playfellow-coop; set PLAYFELLOW_DIR to choose), then runs bootstrap.sh there.
set -e
base="${PLAYFELLOW_DIR:-$HOME/PlayFellow}"
repo="$base/playfellow-coop"
for tool in git python3; do
  command -v "$tool" >/dev/null 2>&1 || { echo "PlayFellow needs $tool (and Python 3.11 or newer). Install it, then run this line again."; exit 1; }
done
mkdir -p "$base"
if [ -d "$repo/.git" ]; then
  git -C "$repo" pull --ff-only
else
  git clone https://github.com/hesham88/playfellow-coop.git "$repo"
fi
sh "$repo/bootstrap.sh"
echo
echo "PlayFellow is in $repo:  cd \"$repo\" && ./playfellow doctor"
