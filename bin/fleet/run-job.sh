#!/bin/bash
# Fleet runner v2: one job per invocation, WITH run validation and
# auto-remediation. A job "ran" only counts when there is EVIDENCE of work
# (a heartbeat for this job inside the run window, or real log content
# beyond the start/done bookends). rc=0 from a silent claude exit is a STUB,
# not a run. Contract (Josh, 2026-10-08): if we expect jobs to run, we
# validate that they ran, and remediate when they did not:
#   stub 1x -> retry immediately
#   stub 2x -> record to garden-reports/fleet-validation.jsonl (the watchdog
#              escalates that to the bus + morning brief; never silent)
# Success writes the heartbeat MECHANICALLY (the model's own check-in stays
# allowed but is no longer the enforcement layer).
#
# Usage: run-job.sh <name>
set -u
NAME="$1"
DIR="$(dirname "$0")"
JOB="$DIR/jobs/$NAME"
LOG="$HOME/.local/state/fleet/$NAME.log"
LOCK="/tmp/fleet-$NAME.lock"
HEARTBEAT="$HOME/.claude/knowledge/garden-reports/heartbeat.jsonl"
VALIDATE_LEDGER="$HOME/.claude/knowledge/garden-reports/fleet-validation.jsonl"

# mkdir lock: atomic on macOS; stale locks (host crash) older than 6h are broken
if ! mkdir "$LOCK" 2>/dev/null; then
  if [ -n "$(find "$LOCK" -maxdepth 0 -mmin +360 2>/dev/null)" ]; then
    echo "$(date '+%F %T') $NAME: breaking stale lock" >> "$LOG"
    rm -rf "$LOCK"
    mkdir "$LOCK" || { echo "$(date '+%F %T') $NAME: lock still held" >> "$LOG"; exit 0; }
  else
    echo "$(date '+%F %T') $NAME: already running, skipping" >> "$LOG"
    exit 0
  fi
fi
trap 'rm -rf "$LOCK" 2>/dev/null' EXIT

# shellcheck source=/dev/null
source "$JOB.env"

echo "$(date '+%F %T') $NAME: start" >> "$LOG"
cd "$JOB_CWD" || { echo "$(date '+%F %T') $NAME: cwd fail" >> "$LOG"; exit 1; }

# launchd environment repair: launchd gives us a minimal PATH (no ~/.local/bin,
# where claude/wt live) and never reads ~/.zshenv (where the AI-gateway and
# Workato env live — zsh-only file). Source the export lines bash-compatible
# and prepend the local bin dir. This is why every launchd-fired claude job
# silently stubbed before 2026-10-08 (root cause, proven by env -i repro).
export PATH="$HOME/.local/bin:$PATH"
if [ -f "$HOME/.zshenv" ]; then
  eval "$(grep -E '^(export )?(ANTHROPIC_|WORKATO_|FIREWORKS_)' "$HOME/.zshenv" 2>/dev/null)" || true
fi
CLAUDE_BIN="${CLAUDE_BIN:-$(command -v claude || echo "$HOME/.local/bin/claude")}"

hb_count() { # heartbeat lines for this job (always a single number)
  local n=""
  [ -f "$HEARTBEAT" ] && n="$(grep -c "\"job\": *\"$NAME\"" "$HEARTBEAT" 2>/dev/null || true)"
  echo "${n:-0}"
}
write_heartbeat() {
  mkdir -p "$(dirname "$HEARTBEAT")"
  echo "{\"ts\":\"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\",\"job\":\"$NAME\"}" >> "$HEARTBEAT"
}

OUT="$LOG.run"   # per-attempt output capture: the stub test is emptiness

run_job() {
  if [ "${CLAUDE_JOB:-yes}" = "yes" ]; then
    perl -e 'alarm shift; exec @ARGV' "${TIMEOUT:-1200}" "$CLAUDE_BIN" -p "$(cat "$JOB.prompt")" < /dev/null \
      ${EXTRA_ARGS:-} > "$OUT" 2>&1
  else
    perl -e 'alarm shift; exec @ARGV' "${TIMEOUT:-1200}" bash "$JOB.script" >> "$OUT" 2>&1
  fi
  cat "$OUT" >> "$LOG"
}

validated() { # $1 = heartbeat count before; real output file or a fresh heartbeat
  local hb_now
  hb_now="$(hb_count)"
  [ "$((hb_now - $1))" -gt 0 ] && return 0
  [ -s "$OUT" ] && return 0
  return 1
}

attempt() { # echoes "valid" or "stub rc=N"
  local h_before rc
  h_before="$(hb_count)"
  run_job
  rc=$?
  if [ "$rc" -eq 0 ] && validated "$h_before"; then
    echo "valid"
  else
    echo "stub rc=$rc"
  fi
}

RESULT="$(attempt)"
if [ "$RESULT" != "valid" ]; then
  echo "$(date '+%F %T') $NAME: no work evidence ($RESULT) — retrying once" >> "$LOG"
  RESULT="$(attempt)"
fi

if [ "$RESULT" = "valid" ]; then
  write_heartbeat
  echo "$(date '+%F %T') $NAME: done validated" >> "$LOG"
  exit 0
fi

echo "$(date '+%F %T') $NAME: VALIDATION FAILED after retry ($RESULT) — job did not run; escalated" >> "$LOG"
mkdir -p "$(dirname "$VALIDATE_LEDGER")"
echo "{\"ts\":\"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\",\"job\":\"$NAME\",\"result\":\"$RESULT\",\"action\":\"retry-exhausted\",\"note\":\"double stub; watchdog escalates to bus + brief\"}" >> "$VALIDATE_LEDGER"
# Never die loudly: fleet jobs are never cron-critical; the ledger is the alarm.
exit 0
