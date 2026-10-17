#!/usr/bin/env bash
# knowledge-export.sh — one-way export of the brain's KNOWLEDGE content into
# the team-shareable corpus repo. The ONLY automated path from
# ~/.claude/knowledge (raw, personal) to the cleaned team repo.
#
# Philosophy (Josh, 2026-10-15): start from EVERYTHING knowledge-shaped and
# deny-list the operational/estate/personal classes, publishing each exclusion
# with its reason. Sweeps then gate the export: secrets, PII, people-file
# names, personal-identity content. Fail-loud on every sweep.
#
# NOT exported (by design): the 7.1GB docs corpus (team installs the public
# sources via the workato-dev-kb pack installer), estate snapshots, fleet
# telemetry, ledgers, and anything Josh-personal.
set -euo pipefail

SRC="$HOME/.claude/knowledge"
DST="${1:-$HOME/Documents/knowledge-corpus}"

# --- deny list: dirname → reason -------------------------------------------
# Operational state / fleet plumbing (not knowledge; some is estate data)
DENY_DIRS=(
  workday/            # 77MB derived wql-aliases.db, not docs
  chaos/              # estate twin copies (internal recipes/connections)
  twin/               # estate snapshots (internal asset data)
  ops-visibility/     # estate telemetry
  roi/                # estate cost data
  workato-health/     # watchdog operational state
  app-snapshots/      # app XML snapshots (customer data risk)
  fixtures/           # test fixtures from live estate
  state-snapshots/
  replay-fixtures/
  garden-reports/     # fleet run reports
  dreams/             # fleet dream reports + proposal queue
  bus/                # gossip bus outboxes
  triage/             # triage queue (ticket ops)
  jira-triage/
  morning-brief/      # daily digests
  watchdog-reports/
  mission-control/    # session closeouts (ops noise)
  harness-fix/        # ops sessions
  now/                # decision inbox
  predictions/
  integrity/
  coverage/
  sagas/
  policies/           # standing-order approvals (governance, internal)
  skills-telemetry/
  bench/              # harness A/B internals
  benchmark/
  events/
  config/             # fleet config (paths, profile names)
  people/             # PEOPLE FILES — never ship (Josh, 2026-10-15)
  redteam/            # security verdicts name internal assets + findings
)
DENY_FILES=(
  slack-posts.jsonl   # Slack post log (conversations)
  slack-posts.jsonl.lock
  build-ledger.jsonl  # mutation ledger (asset + session data)
  build-ledger.jsonl.lock
  browser-hotlist.json
  dashboard.html
  harness-sync.err.log
  harness-sync.out.log
  INDEX.md.orig
  questions.jsonl     # Josh's attention queue
  capabilities.jsonl  # internal tooling caps
  error-ledger.md
)
# domains/: personal-identity knowledge (voice = Josh's writing identity)
DENY_DOMAIN_FILES=(
  voice-reps/
  josh-voice-corpus.md
  josh-voice-fb-samples.txt
  writing-voice.md
  josh-writing-voice.md
)

# --- include list: everything knowledge-shaped ------------------------------
INCLUDE_DIRS=(
  domains/ projects/ architecture/ decisions/ positions/ reviews/ library/
  notes/ specs/ workato-terms/ kb-digests/ workato-api/ models-evals/
  evals/ regression-canon/ instruction-patches/ claims/ cortex/ scripts/
)
# never ship any of these, whatever lands in them (deny wins over include)
EXCLUDE_FROM_INCLUDE=(
  projects/btsup-78827-claude-projects-extract/
)
INCLUDE_FILES=(INDEX.md README.md)

set -e
# rebuild in place, preserving .git so the export repo keeps its history
find "$DST" -mindepth 1 -maxdepth 1 ! -name '.git' -exec rm -rf {} + 2>/dev/null || true
mkdir -p "$DST"
for d in "${INCLUDE_DIRS[@]}"; do
  [ -e "$SRC/$d" ] || { echo "WARN: include dir missing: $d"; continue; }
  mkdir -p "$DST/$d"
  EXC=()
  for x in "${EXCLUDE_FROM_INCLUDE[@]}"; do EXC+=(--exclude="${x#projects/}"); done
  rsync -a --exclude=.DS_Store --exclude='*.bak-*' --exclude='*.bak' \
        --exclude='__pycache__/' --exclude='knowledge-export.sh' \
        "${EXC[@]}" "$SRC/$d" "$DST/$d"
done
for f in "${INCLUDE_FILES[@]}"; do
  [ -f "$SRC/$f" ] && cp "$SRC/$f" "$DST/$f"
done

# --- stubs: excluded dirs keep their skeleton (Josh, 2026-10-15) -------------
# Every deny-listed dir that exists in the live brain gets a README stub in the
# export: structure stays visible, content stays out, and a future policy
# change populates into an existing place instead of a restructure.
for entry in "${DENY_DIRS[@]}"; do
  d="${entry%%#*}"; d="${d// /}"
  [ -n "$d" ] || continue
  reason=$(grep -F "  $d" "$0" 2>/dev/null | head -1 | sed 's/.*# *//') || true
  [ -n "$reason" ] || reason="operational or personal content, not part of the knowledge export"
  if [ -e "$SRC/$d" ]; then
    mkdir -p "$DST/$d"
    printf '%s\n' \
      "# $d" \
      "" \
      "This directory exists in the live harness but is NOT exported." \
      "" \
      "Why: $reason" \
      "" \
      "The weekly exporter (knowledge-export.sh) rebuilds this repo and keeps" \
      "this directory empty except for this stub. If the export policy ever" \
      "changes to include it, content lands here automatically." \
      > "$DST/$d/EXPORT-STUB.md"
  fi
done
# personal-identity strip inside domains/
for f in "${DENY_DOMAIN_FILES[@]}"; do rm -rf "$DST/domains/$f"; done

# --- genericize: home paths in the exported copy only ------------------------
# ~/... -> ~/... (teammates' HOME differs; strips the personal
# path identifier without touching knowledge). Also neutralizes the raw
# account string when it appears standalone.
grep -rl --exclude-dir=.git -e '~' -e 'YOUR-USER' -e 'jdcramoy' "$DST" 2>/dev/null | while read -r f; do
  python3 -c "
import sys
p = sys.argv[1]
t = open(p).read()
t = t.replace('~', '~')   # slash paths
t = t.replace('YOUR-USER', '<user>')     # slugs: -Users-YOUR-USER-Documents-...
t = t.replace('jdcramoy', '<user>')       # github account name
open(p, 'w').write(t)
" "$f"
done

# --- sweep 1: secrets --------------------------------------------------------
SECRET_HITS=$(grep -IrlnE '(sk-ant-[A-Za-z0-9]{20,}|ghp_[A-Za-z0-9]{30,}|xox[bposa]-[A-Za-z0-9-]{10,}|Bearer [A-Za-z0-9._-]{25,}|api[_-]?key["'"'"']?\s*[:=]\s*["'"'"']?[A-Za-z0-9]{20,})' "$DST" --include='*.md' --include='*.py' --include='*.sh' --include='*.json' --include='*.jsonl' --include='*.yaml' --include='*.yml' 2>/dev/null || true)
if [ -n "$SECRET_HITS" ]; then
  echo "EXPORT FAILED: secret-shaped strings found:"; echo "$SECRET_HITS"; exit 1
fi

# --- redaction layer (audit 2026-10-15) --------------------------------------
# Confidential-support-channel content: requester names are redacted in the
# EXPORTED copy only (the raw knowledge keeps the real names for Josh's work).
# Full names are redacted everywhere; bare first names only inside the files
# the audit flagged, to avoid collateral hits elsewhere.
python3 - "$DST" <<'PYREDACT'
import sys, pathlib
dst = pathlib.Path(sys.argv[1])

DROP_FILES = [
    # org-wide claude.ai projects extract: employee emails + private project
    # titles carrying deal sizes/customer names (audit findings 1-2; a third
    # file, org-wide-projects-joined, appeared 2026-10-15 afternoon — the
    # whole extract directory is denied, whatever lands in it)
    "projects/btsup-78827-claude-projects-extract/org-wide-projects-20261015.csv",
    "projects/btsup-78827-claude-projects-extract/projects-raw-20261015.json",
    "projects/btsup-78827-claude-projects-extract/org-wide-projects-joined-20261015.csv",
    # org-chart-derived artifacts carrying colleague names as data
    "notes/2026-10-09-org-chart-mcp-handoff.md",
    "projects/estate-monitor/architecture/asset-graph.svg",
    "projects/estate-monitor/architecture/system-map.svg",
    "projects/hr-genie/architecture/asset-graph.svg",
    "projects/hr-genie/architecture/system-map.svg",
    "notes/2026-10-10-pikin-harness-pitch-draft.md",
]
FULL_NAMES = {
    # confidential-support-channel requesters (audit findings 3-8)
    "Ruben Filipe da Silva Ferreira": "[requester]",
    "Rodrigo Majuelo Jr": "[requester]",
    "Anna Monica De Los Reyes": "[requester]",
    "Patricia Guevarra": "[requester]",
    "Choon Yen Khoo": "[requester]",
    "Dipakkumar K": "[requester]",
    "Ai Ito": "[requester]",
    "Yu Lin": "[requester]",
    # colleague names in work notes (audit: work-context mentions are fine,
    # names still stay out of the shipped copy)
    "Alexey Pikin": "[colleague]",
    "Brooke Shepard": "[colleague]",
    "Adam Seligman": "[colleague]",
    "Grace Ng": "[colleague]",
    "Weizhuang Tan": "[colleague]",
    "Sam Cox": "[colleague]",
}
# EVERY people-file full name redacts globally as [colleague] — generated from
# the people dir at export time, so the map can never go stale.
import os
people_dir = pathlib.Path(os.path.expanduser("~/.claude/knowledge/people"))
for pf in people_dir.glob("*.md"):
    first_line = pf.read_text(errors="replace").splitlines()[0] if pf.exists() else ""
    if first_line.startswith("#") and "<" not in first_line:
        nm = first_line.lstrip("# ").strip()
        if nm and nm not in FULL_NAMES:
            FULL_NAMES[nm] = "[colleague]"
# file-scoped bare first names (audit findings 3-8)
SCOPED_FILES = [
    "projects/btsup-78227-ops-genie-planwise/README.md",
    "projects/btsup-78227-ops-genie-planwise/root-cause-2026-10-10.md",
    "projects/btsup-78227-ops-genie-planwise/draft-customer-reply-2026-10-12.md",
    "projects/btsup-78227-ops-genie-planwise/draft-customer-reply-2026-10-14-consent-ask.md",
    "cortex/investigations/btsup-78227-slack-trigger.md",
    "projects/hr-genie/btsup-service-desk-triage-2026-10-09.md",
    "projects/hr-genie/btsup-77184-and-72246-investigation-2026-10-09.md",
    "projects/hr-genie/btsup-drafts/btsup-76729-reply.md",
    "projects/hr-genie/BTSUP-76729-closing-reply-draft-2026-10-12.md",
    "projects/hr-genie/btsup-drafts/btsup-73287-reply.md",
    "projects/hr-genie/btsup-drafts/btsup-77184-reply.md",
    "projects/hr-genie/btsup-drafts/btsup-drafts-2026-10-11.md",
    "projects/hr-genie/btsup-drafts-2026-10-11.md",
    "projects/hr-genie/btsup-drafts/BTSUP-73287-deel-time-off-approvals-feasibility.md",
    "projects/btsup-customer-replies/BTSUP-78227-reply-draft.md",
    "projects/hr-genie.md",
    "projects/airo-pm-feedback-2026-10.md",
    "projects/airo-pm-filing-package-2026-10-15.md",
]
FIRST_NAMES = ["Ruben", "Rodrigo", "Patricia", "Anna", "Dipakkumar", "Choon", "Davis", "Ng", "Fan", "Goh"]

for rel in DROP_FILES:
    p = dst / rel
    if p.exists():
        p.unlink()

def scrub(path, names):
    p = dst / path
    if not p.exists():
        return
    t = p.read_text()
    for n in names:
        t = t.replace(n, "[requester]")
    p.write_text(t)

# full names are unambiguous: redact across the ENTIRE export (any text file)
for p in dst.rglob("*"):
    if p.suffix not in (".md", ".py", ".sh", ".json", ".jsonl", ".txt", ".yaml", ".yml"):
        continue
    if ".git" in p.parts:
        continue
    t = p.read_text(errors="replace")
    changed = False
    for n, label in FULL_NAMES.items():
        if n in t:
            t = t.replace(n, label)
            changed = True
    if changed:
        p.write_text(t)
# bare first names only inside the flagged files (collateral risk elsewhere)
for rel in set(SCOPED_FILES):
    scrub(rel, FIRST_NAMES)

# INDEX.md: strip lines pointing into people/ (the dir is not shipped, so the
# pointers dangle and carry last names)
idx = dst / "INDEX.md"
if idx.exists():
    kept = [l for l in idx.read_text().splitlines(keepends=True) if "people/" not in l]
    idx.write_text("".join(kept))

# personal draft aimed at a specific person (audit): not shipped
pitch = dst / "notes/2026-10-10-pikin-harness-pitch-draft.md"
if pitch.exists():
    pitch.unlink()
PYREDACT

# live-prod sensitive-data-access observation (audit finding 9) and the
# compliance-key keychain pointer (finding 10) are redacted, not shipped.
RED_NOTES=$(find "$DST" -name 'hr-genie.md' -o -name 'anthropic-compliance-api.md')
for f in $RED_NOTES; do
  python3 -c "
import sys, re
p = sys.argv[1]
t = open(p).read()
# Leapsome/prod sensitive-data probe note
t = re.sub(r'Phase-0 probe note[^\n]*', '[redacted: live-prod sensitive-data access observation]', t)
t = re.sub(r'sees typed overview answers[^\n]*', '', t)
# compliance-key keychain item/account pointers
t = re.sub(r'[Kk]eychain item name[^\n]*', '[redacted: keychain pointer]', t)
open(p, 'w').write(t)
" "$f"
done

# --- sweep 2: people-file real names (PII) -----------------------------------
# Names from people/*.md (H1 title) must not appear in the exported copy.
PII_HITS=""
for pf in "$SRC"/people/*.md; do
  [ -f "$pf" ] || continue
  name=$(head -1 "$pf" | sed -n 's/^#[[:space:]]*\(.*\)$/\1/p')
  [ -n "$name" ] || continue
  case "$name" in *"<"*|*"Name"*) continue;; esac  # skip template files
  hits=$(grep -IFrl "$name" "$DST" 2>/dev/null || true)
  [ -n "$hits" ] && PII_HITS="$name: $hits"$'\n'
done
if [ -n "$PII_HITS" ]; then
  echo "EXPORT FAILED: people-file names appear in exported content (scrub before shipping):"; printf '%s' "$PII_HITS"; exit 1
fi

# --- sweep 3: personal identifiers -------------------------------------------
IDENT_HITS=$(grep -IrlniE --exclude-dir=.git 'YOUR-USER|jdcramoy' "$DST" 2>/dev/null || true)
if [ -n "$IDENT_HITS" ]; then
  echo "EXPORT FAILED: personal account identifiers found:"; echo "$IDENT_HITS"; exit 1
fi

# --- sweep 4: email PII --------------------------------------------------------
# Real-person emails outside the org domain fail the export. (Org-domain mail
# is fine: the audience IS the team.)
EMAIL_HITS=$(grep -IrhoE '[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}' "$DST" 2>/dev/null \
  | grep -viE '@(workato\.com|example\.com|example\.org|yourcompany\.com|<domain>|users\.noreply\.github\.com)$' \
  | grep -viE '^(noreply|no-reply|donotreply|git|canary|test|tests|user|username|name|foo|bar|someone|you|your\.name|email)@' \
  | grep -viE '@[A-Za-z0-9_-]{20,}\.(md|txt|json)($|:)' \
  | sort -u || true)
if [ -n "$EMAIL_HITS" ]; then
  echo "EXPORT FAILED: non-org email addresses found (PII):"; echo "$EMAIL_HITS"; exit 1
fi

# --- report ------------------------------------------------------------------
FILES=$(find "$DST" -type f | wc -l | tr -d ' ')
SIZE=$(du -sh "$DST" | cut -f1)
echo "exported knowledge core -> $DST"
echo "  files: $FILES  size: $SIZE"
echo "  sweeps: secrets OK, PII OK, personal-identifiers OK"
echo "  excluded: ${#DENY_DIRS[@]} dir classes + ledgers + voice/people identity content"
