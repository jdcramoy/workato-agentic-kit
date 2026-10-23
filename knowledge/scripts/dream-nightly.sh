#!/bin/bash
# dream-nightly.sh — the dedicated headless dreamer lane (manual trigger +
# fallback), built 2026-10-16 per accepted proposal
# 2026-10-12-dreamer-headless-lane.
#
# Topology: the PRIMARY lane is launchd com.josh.fleet.dreamer 23:43 ->
# run-job.sh dreamer (validated runner; TIMEOUT=1800 via jobs/dreamer.env).
# Both lanes are session-independent headless calls — the dreamer never
# depends on an idle interactive session. THIS script is the standalone
# fallback and manual trigger; fire it directly any time:
#   bash ~/.claude/knowledge/scripts/dream-nightly.sh
#
# Contention: this lane locks the SAME lock file as the fleet lane
# (/tmp/fleet-dreamer.lock), so a manual run and the nightly run can never
# double-dream; a concurrent starter exits quietly. Stale locks (host crash)
# older than 6h are broken, same rule as run-job.sh.
#
# Bounded: the claude spawn carries the same timeout the other fleet jobs
# carry (1800s, via the perl-alarm pattern run-job.sh uses — macOS has no
# GNU timeout). On timeout or failure NO heartbeat is written: a run that
# did not complete must not check in; the missing heartbeat is what the
# harness-health ladder escalates on.
set -uo pipefail
[ -f "$HOME/.zshenv" ] && . "$HOME/.zshenv" >/dev/null 2>&1
export PATH="$HOME/.local/bin:$PATH"   # launchd gives a minimal PATH; claude lives in ~/.local/bin

LOCK="/tmp/fleet-dreamer.lock"
LOG="$HOME/.claude/knowledge/dreams/data/nightly.log"
HB="$HOME/.claude/knowledge/garden-reports/heartbeat.jsonl"
TIMEOUT=1800   # same bound as fleet jobs/dreamer.env

if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    echo "$(date '+%F %T') nightly dream: breaking stale lock" >> "$LOG"
    rm -rf "$LOCK"
    mkdir "$LOCK" || { echo "$(date '+%F %T') nightly dream: lock still held" >> "$LOG"; exit 0; }
  else
    echo "$(date '+%F %T') nightly dream: dreamer already running (lane lock held), skipping" >> "$LOG"
    exit 0
  fi
fi
trap 'rm -rf "$LOCK" 2>/dev/null' EXIT

echo "$(date '+%F %T') nightly dream start (headless lane)" >> "$LOG"
perl -e 'alarm shift; exec @ARGV' "$TIMEOUT" \
  claude -p "Spawn the harness-dreamer subagent (subagent_type harness-dreamer; if unavailable, general-purpose with $HOME/.claude/agents/harness-dreamer.md as the brief). It executes the full dream loop per its brief. Relay only the report path + verdict." \
  --permission-mode bypassPermissions >> "$LOG" 2>&1
rc=$?
if [ "$rc" -eq 0 ]; then
  printf '{"ts":"%s","job":"harness-dreamer"}\n' "$(date -u +%Y-%m-%dT%H:%M:%SZ)" | python3 "$HOME/.claude/knowledge/scripts/atomic_io.py" "$HB"
  echo "$(date '+%F %T') nightly dream done (headless lane, validated)" >> "$LOG"
else
  echo "$(date '+%F %T') nightly dream FAILED rc=$rc (rc=142 = timeout after ${TIMEOUT}s) — no heartbeat" >> "$LOG"
fi
