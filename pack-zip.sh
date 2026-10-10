#!/usr/bin/env bash
# pack-zip.sh — build the offline zip distribution of the kit.
#
# Zip = kit MECHANICS only (mods, agents, skills, docs, installer). It does
# NOT bundle the KB pipeline: the KB ships as its own pack
# (Workato-All/workato-dev-kb — content + sanitized pipeline + installer),
# and bundling the author's private upstream (workato-kb.git) shipped
# estate-entangled code to recipients. Git users: clone the kit; KB layer:
# clone + install the pack. (Both need network anyway — the KB's corpus
# syncs from public endpoints on first install.)
#
# Usage: ./pack-zip.sh   → dist/agentic-workato-kit-<date>.zip
set -euo pipefail
cd "$(dirname "$0")"

echo "== pack-zip: verify no secrets / personal identifiers in the payload =="
# 1. credential-shaped tokens, excluding the detector files whose JOB is to
#    contain those patterns (their regex definitions are inert):
#    secrets-scrub.py, the guardrails hook scanner, its test fixtures, this script.
LEAKS=$(grep -rIlE "wrkaus-|ATATT3|xoxb-|sk-ant-|ghp_|gho_|github_pat_|Bearer [A-Za-z0-9]{20}" . 2>/dev/null \
  | grep -vE "^\./(dist|\.git|install-logs|kb-pipeline)" \
  | grep -vE "secrets-scrub\.py$|pack-zip\.sh$|tier2\.test\.ts$|hooks/register\.js$" \
  | head -3 || true)
# 2. personal identifiers — precise list (dev-kb hook pattern). FATAL on any
#    hit: the fleet runtime moved to the author's private knowledge tree
#    (2026-10-10), so the tree should carry NO identifiers. plugin.json author
#    fields are attribution, not identifiers — author name is allowed; the
#    author EMAIL is not. install.sh's workspace-note line names the author's
#    dev workspace deliberately as a safety warning — that single line is the
#    one documented exception; anything else is a leak.
IDLeaks=$(grep -rIlE "joshcramoy@workato\.com|josh-slack-triage|U0A3R9AVAMA|\"Josh Cramoy\"|d42cc899-694d-474e-80ef-c4eb3d43cf9f" . 2>/dev/null \
  | grep -vE "^\./(dist|\.git|install-logs|pack-zip\.sh|config\.sh)" \
  | grep -vE "\.claude-plugin/(plugin|marketplace)\.json$" \
  | head -3 || true)
WSRefs=$(grep -rInE "3535597|3535598" . 2>/dev/null \
  | grep -vE "^\./(dist|\.git|install-logs|pack-zip\.sh|config\.sh)" \
  | head -5 || true)
if [ -n "${LEAKS}${IDLeaks}${WSRefs}" ]; then
  echo "FAIL: leaks found — tokens: ${LEAKS:-none} | identifiers: ${IDLeaks:-none} | workspace-IDs-outside-author-note: ${WSRefs:-none}"
  exit 1
fi
echo "   clean"

echo "== pack-zip: build =="
mkdir -p dist
STAMP=$(date +%F)
ZIP="dist/agentic-workato-kit-${STAMP}.zip"
rm -f "$ZIP"
# exclude: local config (has org IDs), git internals, caches, the private
# upstream snapshot dir if it still exists from an old run
zip -qr "$ZIP" . -x "*.git*" -x "config.sh" -x "dist/*" -x "*.log" -x "__pycache__/*" -x "*.pyc" -x "kb-pipeline/kb/*"
echo "== done: $ZIP ($(du -h "$ZIP" | cut -f1)) =="
echo "note: config.sh excluded (org identifiers) — recipients run onboard.sh for their own config."
echo "note: KB pipeline NOT bundled — recipients add it via Workato-All/workato-dev-kb."
