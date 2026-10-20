#!/usr/bin/env bash
# mods-deploy.sh — deploy the kit's mods to the runtime marketplace (~/mods).
#
# Direction of truth: the kit repo (mods/) is the SOURCE; ~/mods is the
# DEPLOYED RUNTIME the josh-mods directory marketplace serves from. Edit
# mods in the kit, commit, then run mods-deploy. Editing ~/mods directly
# is how the copies drift (it happened 2026-10-08); if you must hot-edit
# the runtime, the nightly harness-docs sync job diffs ~/mods against the
# kit and copies divergence BACK into the kit (re-placeholdered) — never
# leave the two disagreeing past that.
#
# PLACEHOLDER RENDERING (added 2026-10-20): the kit carries
# /Users/YOUR-USER placeholders — the pre-commit hook bans real
# identifiers from the org repo — and this script renders them to real
# paths at deploy time, so a raw rsync can no longer break the live mods
# with unrendered placeholders (the live mods carried real paths all
# along; kit and live could never agree under the raw copy).
#
# Usage:
#   mods-deploy          deploy kit mods -> ~/mods (rendered, rsync --delete)
#   mods-deploy --check  diff (rendered kit) vs live, change nothing
set -euo pipefail
# resolve symlinks (installed as ~/.local/bin/mods-deploy -> this file)
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
KIT="$(cd "$(dirname "$SELF")/.." && pwd)"
MODS_SRC="$KIT/mods"
MODS_DST="$HOME/mods"
PLACEHOLDER="/Users/YOUR-USER"

[ -d "$MODS_SRC" ] || { echo "no $MODS_SRC"; exit 1; }
MODE="${1:-deploy}"

render_copy() {
  # render_copy <dest>: copy kit mods to <dest> with placeholders rendered
  local dst="$1"
  rm -rf "$dst"
  mkdir -p "$(dirname "$dst")"
  rsync -a --exclude '.git' --exclude '__pycache__' "$MODS_SRC/" "$dst/"
  grep -rl --exclude-dir='.git' --exclude-dir='__pycache__' -F "$PLACEHOLDER" "$dst" \
    | while IFS= read -r f; do
        python3 - "$f" "$PLACEHOLDER" "$HOME" << 'PYEOF'
import sys
path, ph, home = sys.argv[1], sys.argv[2], sys.argv[3]
s = open(path, errors="replace").read()
open(path, "w").write(s.replace(ph, home))
PYEOF
      done
}

if [ "$MODE" = "--check" ]; then
  STAGE="$(mktemp -d)"
  trap 'rm -rf "$STAGE"' EXIT
  render_copy "$STAGE/mods"
  diff -rq "$STAGE/mods" "$MODS_DST" 2>/dev/null | grep -v '.claude-plugin/types' || echo "in sync"
  exit 0
fi

STAGE="$(mktemp -d)"
trap 'rm -rf "$STAGE"' EXIT
render_copy "$STAGE/mods"
rsync -a --delete --exclude '.git' --exclude '__pycache__' \
  "$STAGE/mods/" "$MODS_DST/"
echo "deployed kit mods (rendered) -> $MODS_DST"
echo "next: the marketplace picks up changes on the next plugin reload"
echo "      (/reload-plugins, or restart Claude Code)"
