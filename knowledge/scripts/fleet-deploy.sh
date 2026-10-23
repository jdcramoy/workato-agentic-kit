#!/bin/bash
# fleet-deploy.sh — atomic three-way deploy of one fleet file (or all of them).
#
# DESIGN DECISION (2026-10-22, triage fleet-job-atomic-deploy): COPY, not symlink.
# Symlinking ~/.local/bin/fleet/* to the knowledge tree would be "cleaner" but
# changes what launchd executes mid-flight (a knowledge-tree edit becomes live
# instantly, with no deploy step, no receipt, and no kit copy for divergence
# detection). The DEPLOY CHECKLIST doctrine in run-job.sh already defines the
# three-copy contract — canonical (knowledge tree) -> deployed (~/.local/bin,
# what the plists execute) -> kit (~/Documents/agentic-workato-kit, divergence
# detector). This script performs that contract atomically with shasum proof,
# killing the wave3 partial-deploy class (wave3-validator-stub-keying.md: the
# executed copy ran a pre-fix script for ~40s while the fix fanned out by hand).
#
# Atomicity: each destination gets write-to-temp + mv (atomic on same volume),
# so a failed deploy can never leave a half-written executable jobfile. All
# copies are then shasum-verified against the source before the script reports
# success; any mismatch = nonzero exit and a loud message.
#
# Usage:
#   fleet-deploy.sh <name>     deploy ONE file, e.g. watchdog.env, backup.script,
#                              run-job.sh (relative to config/fleet/)
#   fleet-deploy.sh --all      deploy every file in config/fleet/ + jobs/
#
# Source of truth: ~/.claude/knowledge/config/fleet/  (the KNOWLEDGE tree —
# per run-job.sh DEPLOY CHECKLIST; never edit the deployed copies directly).
set -u

SRC_ROOT="$HOME/.claude/knowledge/config/fleet"
DESTS=(
  "$HOME/.local/bin/fleet"
  "$HOME/Documents/agentic-workato-kit/bin/fleet"
)

shasum_file() { shasum -a 256 "$1" 2>/dev/null | cut -d' ' -f1; }

deploy_one() {
  local rel="$1"
  local src="$SRC_ROOT/$rel"
  if [ ! -f "$src" ]; then
    echo "FAIL: no canonical source: $src" >&2
    return 1
  fi
  local mode
  mode="$(stat -f '%Lp' "$src")"
  for dest_root in "${DESTS[@]}"; do
    local dest="$dest_root/$rel"
    mkdir -p "$(dirname "$dest")"
    local tmp="$dest.tmp.$$"
    cp "$src" "$tmp" || { echo "FAIL: cp to $tmp" >&2; return 1; }
    chmod "$mode" "$tmp" || { rm -f "$tmp"; echo "FAIL: chmod $tmp" >&2; return 1; }
    mv -f "$tmp" "$dest" || { rm -f "$tmp"; echo "FAIL: mv $tmp -> $dest" >&2; return 1; }
  done
  # verify: source + both copies byte-identical
  local s_hash first_hash
  s_hash="$(shasum_file "$src")"
  first_hash="$s_hash"
  for dest_root in "${DESTS[@]}"; do
    local d_hash
    d_hash="$(shasum_file "$dest_root/$rel")"
    if [ "$d_hash" != "$first_hash" ]; then
      echo "FAIL: shasum mismatch $rel — $dest_root/$rel differs from canonical" >&2
      return 1
    fi
  done
  echo "OK: $rel deployed+verified (sha256 ${first_hash:0:12}...) -> ${DESTS[*]}"
  return 0
}

main() {
  [ $# -ge 1 ] || { sed -n '2,25p' "$0"; exit 2; }
  local failures=0
  if [ "$1" = "--all" ]; then
    # one atomic pass over every canonical file, jobs/ preserved via rel path
    while IFS= read -r rel; do
      deploy_one "$rel" || failures=$((failures + 1))
    done < <(cd "$SRC_ROOT" && find . -type f ! -name '*.bak-*' | sed 's|^\./||' | sort)
  else
    deploy_one "$1" || failures=$((failures + 1))
  fi
  if [ "$failures" -gt 0 ]; then
    echo "DEPLOY FAILED: $failures file(s) not deployed clean — fix and rerun" >&2
    exit 1
  fi
  echo "DEPLOY COMPLETE: all copies shasum-verified"
}

main "$@"
