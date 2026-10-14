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
# Zero-LLM probe gate (2026-10-11, proposal #2): if jobs/<name>.probe exists
# and is executable it runs BEFORE any claude spawn:
#   exit 0            -> SIGNAL: there is work, run the job normally
#   exit 7            -> NO SIGNAL: write a skip-heartbeat row
#                        (status "skipped-no-signal") and exit. Zero tokens,
#                        zero claude spawn. The skip row keeps harness-health
#                        liveness green (the probe itself is the liveness
#                        signal) while the status field keeps it distinct
#                        from a stub.
#   any other nonzero -> BROKEN probe: log it and RUN the job anyway (fail
#                        open). A buggy probe must never silently suppress a
#                        job — the 2026-10-07 stub-night lesson.
#
# DEPLOY CHECKLIST: the canonical source of this file and jobs/ is the
# KNOWLEDGE tree (~/.claude/knowledge/config/fleet). Deploy = copy to
# ~/Documents/agentic-workato-kit/bin/fleet (kit sync) AND to
# ~/.local/bin/fleet (what the plists execute). All three identical, or a
# job resolves a diverged copy (the 2026-10-10 partial-deploy incident:
# 7 jobs' files missing -> exit 1/127 for 2 days).
#
# Usage: run-job.sh <name> [extra claude args...]
# Args after <name> are passed through to the claude invocation, so a job's
# plist can carry dispatch-level flags (e.g. --add-dir for cortex).
set -u
NAME="$1"
shift
# ${1+...} guard: bash 3.2 + set -u treats empty "$@" as unbound
PASS_ARGS="${1+"$@"}"
DIR="$(dirname "$0")"
JOB="$DIR/jobs/$NAME"
LOG="$HOME/.local/state/fleet/$NAME.log"
LOCK="/tmp/fleet-$NAME.lock"
# Ledger paths are overridable for probe testing (FLEET_HEARTBEAT /
# FLEET_VALIDATE_LEDGER): a throwaway test job must not write rows into the
# real append-only ledgers.
HEARTBEAT="${FLEET_HEARTBEAT:-$HOME/.claude/knowledge/garden-reports/heartbeat.jsonl}"
VALIDATE_LEDGER="${FLEET_VALIDATE_LEDGER:-$HOME/.claude/knowledge/garden-reports/fleet-validation.jsonl}"

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

# ---- budget preflight (P1 PRICEBOOK, 2026-10-13) -----------------------------
# If BUDGET_USD_CAP is set (jobs/<name>.env or the environment), fleet-cost.py
# compares the job's trailing-7d median gateway costUSD against the cap:
#   exit 7 -> over cap: write a skip-heartbeat row (status "skipped-budget",
#             same atomic_io mechanism as the probe skip) and exit 0.
#   ANY other outcome (no cap, no cost data, script broken) -> run the job
#             normally. Fail-open: a buggy preflight must never suppress a job.
# Default (no cap set) = pure telemetry, never skip.
if [ -n "${BUDGET_USD_CAP:-}" ] && [ -x "$HOME/.claude/knowledge/scripts/fleet-cost.py" ]; then
  python3 "$HOME/.claude/knowledge/scripts/fleet-cost.py" --preflight "$NAME" --cap "$BUDGET_USD_CAP"
  prc=$?
  if [ "$prc" -eq 7 ]; then
    off="$(date +%z)"; off="${off:0:3}:${off:3}"
    echo "{\"ts\":\"$(date +%Y-%m-%dT%H:%M:%S)${off}\",\"job\":\"$NAME\",\"status\":\"skipped-budget\",\"cap\":\"$BUDGET_USD_CAP\"}" | python3 "$HOME/.claude/knowledge/scripts/atomic_io.py" "$HEARTBEAT"
    echo "$(date '+%F %T') $NAME: budget preflight — trailing-7d median cost over cap $BUDGET_USD_CAP — skipped (zero tokens)" >> "$LOG"
    exit 0
  fi
fi

# ---- zero-LLM probe gate (contract in the header comment) -------------------
PROBE="$JOB.probe"
PROBE_NOSIGNAL=7
if [ -f "$PROBE" ] && [ -x "$PROBE" ]; then
  PROBE_OUT="$LOG.probe-out"
  # 60s cap: a hung probe must not hang the runner. Timeout (SIGALRM) is a
  # nonzero that is not the no-signal code -> broken -> fail open, run.
  perl -e 'alarm shift; exec @ARGV' 60 "$PROBE" > "$PROBE_OUT" 2>&1
  prc=$?
  if [ "$prc" -eq "$PROBE_NOSIGNAL" ]; then
    # skip-heartbeat row: same append mechanism as the success heartbeat.
    # ts carries the LOCAL offset (iso-with-offset) so it parses correctly
    # next to the Z-format rows; probe stdout is collapsed to one line.
    pmsg="$(tr -d '\r' < "$PROBE_OUT" | tr '\n' ' ' | sed 's/\\/\\\\/g; s/"/\\"/g' | cut -c1-200)"
    off="$(date +%z)"; off="${off:0:3}:${off:3}"
    mkdir -p "$(dirname "$HEARTBEAT")"
    echo "{\"ts\":\"$(date +%Y-%m-%dT%H:%M:%S)${off}\",\"job\":\"$NAME\",\"status\":\"skipped-no-signal\",\"probe\":\"$pmsg\"}" | python3 "$HOME/.claude/knowledge/scripts/atomic_io.py" "$HEARTBEAT"
    echo "$(date '+%F %T') $NAME: probe no signal — skipped (zero tokens)" >> "$LOG"
    exit 0
  elif [ "$prc" -ne 0 ]; then
    echo "$(date '+%F %T') $NAME: PROBE BROKEN (rc=$prc, out: $(head -c 200 "$PROBE_OUT" | tr '\n' ' ')) — failing open, running job" >> "$LOG"
  fi
  # prc=0 -> signal: fall through to the normal run below
fi

hb_count() { # heartbeat lines for this job (always a single number)
  local n=""
  [ -f "$HEARTBEAT" ] && n="$(grep -c "\"job\": *\"$NAME\"" "$HEARTBEAT" 2>/dev/null || true)"
  echo "${n:-0}"
}
write_heartbeat() {
  mkdir -p "$(dirname "$HEARTBEAT")"
  echo "{\"ts\":\"$(date -u '+%Y-%m-%dT%H:%M:%SZ')\",\"job\":\"$NAME\"}" | python3 "$HOME/.claude/knowledge/scripts/atomic_io.py" "$HEARTBEAT"
}

OUT="$LOG.run"   # per-attempt output capture: the stub test is emptiness

run_job() {
  if [ "${CLAUDE_JOB:-yes}" = "yes" ]; then
    perl -e 'alarm shift; exec @ARGV' "${TIMEOUT:-1200}" "$CLAUDE_BIN" -p "$(cat "$JOB.prompt")" < /dev/null \
      ${EXTRA_ARGS:-} ${PASS_ARGS:-} > "$OUT" 2>&1
  else
    perl -e 'alarm shift; exec @ARGV' "${TIMEOUT:-1200}" bash "$JOB.script" >> "$OUT" 2>&1
  fi
  # capture the SPAWN's rc, not cat's — cat previously masked the claude exit
  # code here, so an alarm-killed spawn logged "stub rc=0" (found 2026-10-11
  # during the probe-gate tests; the stub contract requires the real rc)
  local jrc=$?
  cat "$OUT" >> "$LOG"
  return "$jrc"
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
