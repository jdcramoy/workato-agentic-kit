#!/bin/bash
# dream-mini.sh — the hidden lane: a silent, headless mini-dream every few
# hours. More hidden: no window, no transcript spam, output lands only in
# knowledge/dreams/ + the gossip bus; the morning brief is the only surface
# that reports it. Longer: launchd fires around the clock, not just when a
# session happens to be open.
#
# Objective trigger built in: most runs are cheap no-ops. The script mines
# the last 24h and calls claude -p ONLY when there is new signal (new
# correction candidates, or unanswered dreamer handoffs on the bus). No
# signal = exit silently.

set -uo pipefail

K="$HOME/.claude/knowledge"
STATE="$K/dreams/data/mini-state.json"
LOG="$K/dreams/data/mini.log"

# launchd doesn't source shell profiles; the gateway env lives in ~/.zshenv
[ -f "$HOME/.zshenv" ] && . "$HOME/.zshenv" >/dev/null 2>&1

log() { echo "$(date '+%Y-%m-%dT%H:%M:%S') $1" >> "$LOG"; }

# --- mine ---------------------------------------------------------------------
OUT=$(python3 "$K/scripts/dream-mine.py" --days 1 2>/dev/null) || { log "mine failed"; exit 0; }
MINE_FILE=$(echo "$OUT" | head -1)
CORRECTIONS=$(python3 -c "import json;print(len(json.load(open('$MINE_FILE')).get('corrections',[])))" 2>/dev/null || echo 0)

# --- gate: new signal since last mini? ----------------------------------------
LAST_C=0
[ -f "$STATE" ] && LAST_C=$(python3 -c "import json;print(json.load(open('$STATE')).get('corrections',0))" 2>/dev/null)
FORCE=${FORCE:-0}

if [ "$FORCE" != "1" ] && [ "$CORRECTIONS" -le "$LAST_C" ]; then
  # second gate: unanswered handoffs to the dreamer on the bus?
  HANDOFFS=$(python3 - "$K/dreams/bus" << 'PY' 2>/dev/null || echo 0
import json, sys, glob, os
n = 0
for p in glob.glob(os.path.join(sys.argv[1], "*.jsonl")):
    if os.path.basename(p) == "harness-dreamer.jsonl":
        continue
    try:
        for line in open(p):
            e = json.loads(line)
            if e.get("kind") == "handoff" and "dreamer" in str(e.get("line", "")):
                n += 1
    except Exception:
        pass
print(n)
PY
)
  if [ "${HANDOFFS:-0}" -eq 0 ]; then
    log "no new signal (corrections $CORRECTIONS <= $LAST_C, handoffs 0) — silent exit"
    exit 0
  fi
fi

# --- dream (hidden, headless, bounded) ----------------------------------------
log "signal detected (corrections $CORRECTIONS, last $LAST_C) — mini-dream"
REPORT="$K/dreams/mini-$(date +%Y-%m-%d)-$(date +%H).md"
claude -p "MINI-DREAM (hidden lane, bounded): read $MINE_FILE and run python3 $K/scripts/gossip-read.py --since 24h --json. Write a mini dream report to $REPORT: under 20 lines, corrections quoted verbatim with your one-line read, any unanswered dreamer handoffs on the bus, one vision seed paragraph maximum, no proposals, no file writes outside that report. Then corroborate or post findings to $K/dreams/bus/harness-dreamer.jsonl (max 2 lines). Output to stdout: ONLY the report path + one line verdict." \
  >> "$LOG" 2>&1

# --- state --------------------------------------------------------------------
python3 -c "import json;json.dump({'corrections':$CORRECTIONS,'updated':'$(date '+%Y-%m-%dT%H:%M:%S')'},open('$STATE','w'))"
log "mini-dream complete -> $REPORT"
echo "$REPORT"
