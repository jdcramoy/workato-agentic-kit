#!/bin/bash
# dream-mini.sh v2 — the hidden lane. Always dreaming, always assembling.
#
# Every run (launchd — HOURLY during the ramp-up phase, taper to 3h later):
#   1. Mine the last 24h (cheap, python only).
#   2. ALWAYS: one vision seed (a tiny headless dream) -> visions/seeds.jsonl.
#      The AI never stops dreaming. Josh's rule: periodic triggers have value;
#      run MORE dreaming at the start, taper the interval later by editing the
#      launchd plist's StartInterval.
#   3. If new signal (new corrections or unanswered dreamer handoffs): a full
#      mini dream report -> dreams/mini-*.md.
#      If NO signal: the workshop — instead of idling, assemble elsewhere with
#      a rotating roster (claim re-verify queue, canon coverage, kit/knowledge
#      drift, 7-day bus digest), posted to the dreamer outbox.
#
# Nothing from this lane ever surfaces in an interactive session. The 07:13
# brief is the only reader.

set -uo pipefail

K="$HOME/.claude/knowledge"
STATE="$K/dreams/data/mini-state.json"
LOG="$K/dreams/data/mini.log"
SEEDS="$K/dreams/visions/seeds.jsonl"
BUS_OUT="$K/dreams/bus/harness-dreamer.jsonl"

[ -f "$HOME/.zshenv" ] && . "$HOME/.zshenv" >/dev/null 2>&1

log() { echo "$(date '+%Y-%m-%dT%H:%M:%S') $1" >> "$LOG"; }
NOW_ISO="$(date -u +%Y-%m-%dT%H:%M:%SZ)"

# --- 1. mine (cheap) ----------------------------------------------------------
OUT=$(python3 "$K/scripts/dream-mine.py" --days 1 2>/dev/null) || { log "mine failed"; exit 0; }
MINE_FILE=$(echo "$OUT" | head -1)
CORRECTIONS=$(python3 -c "import json;print(len(json.load(open('$MINE_FILE')).get('corrections',[])))" 2>/dev/null || echo 0)

LAST_C=0
[ -f "$STATE" ] && LAST_C=$(python3 -c "import json;print(json.load(open('$STATE')).get('corrections',0))" 2>/dev/null)

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

# --- 2. the dream never stops: one seed every run ------------------------------
mkdir -p "$K/dreams/visions"
SEED=$(claude -p "You are the vision organ of Josh's agentic harness. Write ONE vision seed: 2-4 sentences of pure speculation about what this harness, this agent network, or the man who owns both could become over the next 3-12 months. No evidence required. No lists, no headers, no em dashes. Voice: a peer, not a report. Output ONLY the seed text." 2>/dev/null | head -c 800)
if [ -n "$SEED" ]; then
  python3 - "$SEEDS" "$NOW_ISO" "$SEED" << 'PY'
import json, sys
path, ts, seed = sys.argv[1], sys.argv[2], sys.argv[3]
with open(path, "a") as fh:
    fh.write(json.dumps({"ts": ts, "seed": seed}) + "\n")
PY
  log "seed planted"
else
  log "seed call returned empty (gateway hiccup?) — continuing"
fi

# --- 3. signal -> mini dream; quiet -> workshop --------------------------------
TASK_IDX=0
[ -f "$STATE" ] && TASK_IDX=$(python3 -c "import json;print(json.load(open('$STATE')).get('workshop_i',0))" 2>/dev/null || echo 0)
FORCE=${FORCE:-0}

if [ "$FORCE" = "1" ] || [ "$CORRECTIONS" -gt "$LAST_C" ] || [ "${HANDOFFS:-0}" -gt 0 ]; then
  MODE="mini-dream"
  log "signal (corrections $CORRECTIONS vs $LAST_C, handoffs $HANDOFFS) — mini-dream"
  REPORT="$K/dreams/mini-$(date +%Y-%m-%d)-$(date +%H).md"
  claude -p "MINI-DREAM (hidden lane, bounded): read $MINE_FILE and run python3 $K/scripts/gossip-read.py --since 24h --json. Write a mini dream report to $REPORT: under 20 lines, corrections quoted verbatim with your one-line read, any unanswered dreamer handoffs on the bus, no proposals, no file writes outside that report. Then corroborate or post findings to $BUS_OUT (max 2 lines). Output to stdout: ONLY the report path + one line verdict." \
    >> "$LOG" 2>&1
  log "mini-dream complete -> $REPORT"
else
  MODE="workshop"
  # every other quiet pulse is the CORTEX (the brain agent): attention,
  # coherence, curiosity — the general proactive agent Josh asked for.
  if [ $((TASK_IDX % 2)) -eq 1 ]; then
    MODE="cortex"
    log "cortex pulse"
    claude -p "You are the Cortex (the brain agent). Read your brief at $HOME/.claude/agents/cortex.md and run ONE bounded pulse: read the grounds (bus 24h, newest dream + seeds, claims, canon, latest watchdog/regression, build ledger), rewrite $HOME/.claude/knowledge/cortex/attention-queue.md (max 7 items), append max 3 questions to $HOME/.claude/knowledge/cortex/questions.jsonl, post max 3 findings to $HOME/.claude/knowledge/dreams/bus/cortex.jsonl. Contradictions first. Nothing changed = one quiet bus line. Output: ONLY one line — pulse summary." >> "$LOG" 2>&1
    log "cortex pulse complete"
  else
  case $((TASK_IDX % 4)) in
    0) NOTE=$(python3 -c "
import json
claims=[json.loads(l) for l in open('$K/claims/claims.jsonl') if l.strip()]
active=[c for c in claims if c.get('status')=='active']
oldest=min(active, key=lambda c: c.get('last_verified',''), default=None)
print(\"claim re-verify queue: \" + oldest['id'] + \" '\" + oldest['subject'] + \"' last verified \" + str(oldest['last_verified']) if oldest else 'no active claims')" 2>/dev/null || echo "claims read failed") ;;
    1) NOTE=$(python3 -c "
import json
try:
    canon=[json.loads(l) for l in open('$K/regression-canon/canon.jsonl') if l.strip()]
    open_=[c for c in canon if c.get('status')!='tested']
    print('canon coverage: ' + str(len(canon)) + ' entries, ' + str(len(open_)) + ' without test cases' + (' — open: ' + ', '.join(str(c['recipe_id']) + ':' + c['signature'] for c in open_[:3]) if open_ else ' — full coverage'))
except FileNotFoundError:
    print('canon not initialized')" 2>/dev/null) ;;
    2) NOTE=$(python3 -c "
import subprocess
r=subprocess.run(['git','-C','$HOME/Documents/agentic-workato-kit','log','--oneline','-1'],capture_output=True,text=True)
k=subprocess.run(['git','-C','$K','status','--porcelain'],capture_output=True,text=True)
print('kit HEAD: ' + r.stdout.strip()[:60] + '; knowledge repo dirty files: ' + str(len(k.stdout.splitlines())))" 2>/dev/null || echo "drift check failed") ;;
    3) NOTE=$(python3 "$K/scripts/gossip-read.py" --since 7d 2>/dev/null | tail -4 | tr '\n' ' | ') ;;
  esac
  python3 - "$BUS_OUT" "$NOW_ISO" "$NOTE" << 'PY'
import json, sys
bus, ts, note = sys.argv[1], sys.argv[2], sys.argv[3]
with open(bus, "a") as fh:
    fh.write(json.dumps({
        "ts": ts, "agent": "harness-dreamer", "kind": "finding",
        "subject": "workshop-" + ts[:10] + "-" + ts[11:13] + "h",
        "line": "Workshop (quiet-lane assembly): " + note[:300],
        "refs": [], "thread_id": "workshop-log", "corroborations": 0, "ttl_days": 7,
    }) + "\n")
PY
  log "workshop task $((TASK_IDX % 4)) complete"
  fi
fi

# --- state ---------------------------------------------------------------------
python3 - "$STATE" "$CORRECTIONS" "$NOW_ISO" "$MODE" "$TASK_IDX" << 'PY' 2>/dev/null || true
import json, sys
path, c, ts, mode, idx = sys.argv[1], int(sys.argv[2]), sys.argv[3], sys.argv[4], int(sys.argv[5])
json.dump({"corrections": c, "updated": ts,
           "workshop_i": idx + 1 if mode in ("workshop", "cortex") else idx}, open(path, "w"))
PY
# dashboard stays fresh: every lane run regenerates it (page self-refreshes)
python3 "$K/scripts/brain-dashboard.py" >/dev/null 2>&1 || true
echo "done ($MODE)"
