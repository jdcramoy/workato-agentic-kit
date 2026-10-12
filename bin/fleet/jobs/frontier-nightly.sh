#!/bin/bash
# Frontier nightly — zero-LLM loop: twin refresh → calibration resolve →
# precursor radar → skill fitness. No claude spawn; pure python. (2026-10-11)
set -u
LOG="{{HOME}}/.local/state/fleet/frontier-nightly.log"
echo "=== frontier-nightly start $(date -u +%FT%TZ) ===" >> "$LOG"
python3 "{{HOME}}/.claude/knowledge/scripts/twin-snapshot.py" >> "$LOG" 2>&1
python3 "{{HOME}}/.claude/knowledge/scripts/brier-resolve.py" >> "$LOG" 2>&1
python3 "{{HOME}}/.claude/knowledge/scripts/precursor-radar.py" >> "$LOG" 2>&1
python3 "{{HOME}}/.claude/knowledge/scripts/skill-fitness.py" backfill --transcripts-dir "$HOME/.claude/projects" --sample 40 >> "$LOG" 2>&1
python3 "{{HOME}}/.claude/knowledge/scripts/skill-fitness.py" report >> "$LOG" 2>&1
echo "=== frontier-nightly done $(date -u +%FT%TZ) rc=$? ===" >> "$LOG"
