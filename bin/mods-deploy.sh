#!/usr/bin/env bash
# mods-deploy.sh — deploy the kit's mods to the runtime marketplace (~/mods).
#
# Direction of truth: the kit repo (mods/) is the SOURCE; ~/mods is the
# DEPLOYED RUNTIME the josh-mods directory marketplace serves from. Edit
# mods in the kit, commit, then run mods-deploy. Editing ~/mods directly
# is how the copies drift (it happened 2026-10-08); if you must hot-edit
# the runtime, the weekly harness-docs sync job diffs ~/mods against the
# kit and copies divergence BACK into the kit — never leave the two
# disagreeing past that.
#
# Usage:
#   mods-deploy          deploy kit mods -> ~/mods (rsync --delete, .git excluded)
#   mods-deploy --check  show the diff only, change nothing
set -euo pipefail
# resolve symlinks (installed as ~/.local/bin/mods-deploy -> this file)
SELF="$(readlink -f "${BASH_SOURCE[0]}")"
KIT="$(cd "$(dirname "$SELF")/.." && pwd)"
MODS_SRC="$KIT/mods"
MODS_DST="$HOME/mods"

[ -d "$MODS_SRC" ] || { echo "no $MODS_SRC"; exit 1; }
MODE="${1:-deploy}"
if [ "$MODE" = "--check" ]; then
  diff -rq "$MODS_SRC" "$MODS_DST" 2>/dev/null | grep -v '.claude-plugin/types' || echo "in sync"
  exit 0
fi
rsync -a --delete --exclude '.git' --exclude '__pycache__' \
  "$MODS_SRC/" "$MODS_DST/"
echo "deployed kit mods -> $MODS_DST"
echo "next: the marketplace picks up changes on the next plugin reload"
echo "      (/reload-plugins, or restart Claude Code)"
