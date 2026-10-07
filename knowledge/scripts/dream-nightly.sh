#!/bin/bash
# dream-nightly.sh — the 23:43 full dream via launchd (session-independent).
# Sources the shell env (launchd doesn't) and spawns the harness-dreamer agent.
set -uo pipefail
[ -f "$HOME/.zshenv" ] && . "$HOME/.zshenv" >/dev/null 2>&1
LOG="$HOME/.claude/knowledge/dreams/data/nightly.log"
echo "$(date '+%F %T') nightly dream start" >> "$LOG"
claude -p "Spawn the harness-dreamer subagent (subagent_type harness-dreamer; if unavailable, general-purpose with $HOME/.claude/agents/harness-dreamer.md as the brief). It executes the full dream loop per its brief. Relay only the report path + verdict." >> "$LOG" 2>&1
printf '{"ts":"%s","job":"harness-dreamer"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" >> "$HOME/.claude/knowledge/garden-reports/heartbeat.jsonl"
echo "$(date '+%F %T') nightly dream done" >> "$LOG"
