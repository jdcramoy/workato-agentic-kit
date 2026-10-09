#!/usr/bin/env bash
# pack-zip.sh — build the offline zip distribution of the kit.
#
# Zip = fully self-contained: bundles a snapshot of the workato-kb pipeline
# code (kb-pipeline/kb) so recipients WITHOUT GitHub access get everything.
# Git users should clone the repo instead (the installer pulls latest).
#
# Usage: ./pack-zip.sh   → dist/agentic-workato-kit-<date>.zip
set -euo pipefail
cd "$(dirname "$0")"

echo "== pack-zip: snapshot the KB pipeline =="
rm -rf kb-pipeline/kb
git clone --depth 1 -q https://github.com/Workato-All/workato-kb.git kb-pipeline/kb
rm -rf kb-pipeline/kb/.git kb-pipeline/kb/.venv kb-pipeline/kb/__pycache__
echo "   snapshot: $(ls kb-pipeline/kb | wc -l | tr -d ' ') top-level entries"

echo "== pack-zip: verify no secrets in the payload =="
LEAKS=$(grep -rIlE "wrkaus-|ATATT3|xoxb-|sk-ant-|ghp_|Bearer [A-Za-z0-9]{20}" kb-pipeline/kb 2>/dev/null | head -3 || true)
if [ -n "${LEAKS}" ]; then echo "FAIL: token-like strings found in: $LEAKS"; exit 1; fi
echo "   clean"

echo "== pack-zip: build =="
mkdir -p dist
STAMP=$(date +%F)
ZIP="dist/agentic-workato-kit-${STAMP}.zip"
rm -f "$ZIP"
# exclude: local config (has org IDs), git internals, caches
zip -qr "$ZIP" . -x "*.git*" -x "config.sh" -x "dist/*" -x "*.log" -x "__pycache__/*" -x "*.pyc"
echo "== done: $ZIP ($(du -h "$ZIP" | cut -f1)) =="
echo "note: config.sh excluded (org identifiers) — recipients run onboard.sh for their own config."
