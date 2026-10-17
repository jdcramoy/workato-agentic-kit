#!/bin/bash
# effdash-daily.sh — zero-LLM daily dashboard refresh + fleet heartbeat row.
# Runs the pure-python dashboard builder; appends to the heartbeat ledger so the
# morning brief / harness-health notice a silent failure (missing daily row).
set -u
LOG="$HOME/.local/state/effdash.log"
HB="$HOME/.claude/knowledge/garden-reports/heartbeat.jsonl"
{
  echo "=== effdash run $(date '+%F %T') ==="
  /usr/bin/python3 "$HOME/.claude/knowledge/scripts/efficiency-dash.py"
  rc=$?
  if [ -f "$HB" ]; then
    echo "{\"ts\":\"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\",\"job\":\"effdash\",\"rc\":\"$rc\"}" >> "$HB"
  fi
  echo "rc=$rc"
} >> "$LOG" 2>&1
