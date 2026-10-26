#!/bin/bash
# Argo installer. Paste in Terminal:
#   curl -fsSL https://raw.githubusercontent.com/panosadamop/argo-mac/main/install.sh | bash
# Downloads the source to ~/.argo (Check for updates pulls into it), builds the app, opens it.
# Another fork: ARGO_REPO=owner/name before bash. It is saved as github.repo in ~/.config/argo/config.json.
set -e
DIR="${ARGO_DIR:-$HOME/.argo}"
REPO="${ARGO_REPO:-panosadamop/argo-mac}"
echo "Installing Argo…"
[ "$(sw_vers -productVersion | cut -d. -f1)" -ge 26 ] || { echo "Argo needs macOS 26 or later."; exit 1; }
if ! xcode-select -p >/dev/null 2>&1; then
  echo "First, Apple's command line tools. A macOS window will open: click Install."
  echo "When it finishes, paste the install line again."
  xcode-select --install 2>/dev/null || true
  exit 1
fi
if [ -d "$DIR/.git" ]; then
  git -C "$DIR" pull -q --ff-only || { echo "Could not update $DIR. Delete that folder, then paste the install line again."; exit 1; }
else
  git clone -q https://github.com/$REPO.git "$DIR"
fi
"$DIR/build.sh"
# config.json: made from its template on first use; point its github.repo at the fork just installed
if [ ! -e "$HOME/.config/argo/config.json" ]; then
  /bin/sh "$HOME/Applications/Argo.app/Contents/Resources/argo.py" --config >/dev/null
  python3 - "$HOME/.config/argo/config.json" "$REPO" <<'PY'
import json, sys
path, repo = sys.argv[1:]
data = json.load(open(path))
data.setdefault('github', {})['repo'] = repo
with open(path, 'w') as f: json.dump(data, f, indent=2); f.write('\n')
PY
fi
open "$HOME/Applications/Argo.app"
echo "Done. The Argo setup window walks you through the rest."
