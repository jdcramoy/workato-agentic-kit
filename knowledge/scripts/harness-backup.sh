#!/bin/bash
# harness-backup.sh — back up Josh's agentic harness to github.com/Workato-All/josh-orca
#
# Copies the load-bearing trees into the repo (secrets redacted), commits,
# pushes. Runs nightly via LaunchAgent com.josh.harness-backup (23:33) and on
# demand: `harness-backup` (symlinked into ~/.local/bin).
#
# Secrets policy: settings.json values matching TOKEN/KEY/SECRET are replaced
# with [REDACTED-BACKUP] in the repo copy. Transcripts, credentials files, and
# audit logs are never copied. Keychain entries cannot be exported (see README).

set -euo pipefail

# Config (env overrides): BACKUP_REPO_LOCAL = local clone of the backup repo;
# BACKUP_REPO_URL = its origin. With no URL, backup commits locally and skips
# the push (safe default; set both in config.sh).
# Pull repo config from the kit's config.sh when present (the nightly cron
# runs bare, with no env), then allow explicit env overrides on top.
for __cfg in "$HOME/Documents/agentic-workato-kit/config.sh"; do
  [ -f "$__cfg" ] && . "$__cfg"
done 2>/dev/null || true
REPO="${BACKUP_REPO_LOCAL:-$HOME/Documents/josh-orca}"
CLAUDE="$HOME/.claude"
STAMP="$(date '+%Y-%m-%d %H:%M:%S')"

mkdir -p "$REPO"

# --- dream-mine pre-backup (next-10 #7, germination trials) ------------------
# The day's transcript digest (dreams/data/<date>-mine.json) must be INSIDE
# the backup even when the dreamer LLM pass stubs. Guarded: a mining failure
# is logged and the backup CONTINUES — backup must not depend on mining.
DIGEST_OUT="$(python3 "$CLAUDE/knowledge/scripts/dream-mine.py" --days 1 2>&1)" \
  || DIGEST_OUT="DREAM-MINE FAILED (backup continues): $(printf '%s' "$DIGEST_OUT" | tail -1)"
echo "harness-backup: dream-mine --days 1 -> $(printf '%s' "$DIGEST_OUT" | tail -1) ($STAMP)"

# --- canonical -> repo -------------------------------------------------------
# --max-size: large regenerable data artifacts (e.g. wql_aliases.db, 132MB)
# exceed GitHub's 100MB limit and don't belong in git. Excluded, not lost.

rsync -a --delete --max-size='50M' \
  --exclude '.git' --exclude 'node_modules' --exclude '__pycache__' \
  "$CLAUDE/skills/"     "$REPO/harness/skills/"
rsync -a --delete --max-size='50M' \
  --exclude '.git' --exclude '__pycache__' \
  "$CLAUDE/agents/"     "$REPO/harness/agents/"
rsync -a --delete --max-size='50M' \
  --exclude '.git' --exclude '__pycache__' --exclude 'usage-ledger.jsonl' \
  "$CLAUDE/knowledge/"  "$REPO/harness/knowledge/"
# Recipe snapshot history: the rollback payload for every pushed recipe.
# Its own git history is per-snapshot commits and does not travel; the
# snapshot files are the asset.
rsync -a --delete --max-size='50M' \
  --exclude '.git' \
  "$CLAUDE/recipe-history/" "$REPO/harness/recipe-history/"
rsync -a --delete --max-size='50M' \
  --exclude '.git' --exclude 'node_modules' --exclude '.claude-plugin/types' \
  "$HOME/mods/"         "$REPO/mods/"

mkdir -p "$REPO/harness" "$REPO/launchagents" "$REPO/harness/local-bin"

# settings.json, sanitized
python3 - "$CLAUDE/settings.json" "$REPO/harness/settings.json" << 'PY'
import json, re, sys
src, dst = sys.argv[1], sys.argv[2]
d = json.load(open(src))
SECRETISH = re.compile(r'token|secret|api.?key|password|credential', re.I)
def scrub(o):
    if isinstance(o, dict):
        return {k: ('[REDACTED-BACKUP]' if SECRETISH.search(k) and isinstance(v, str) else scrub(v))
                for k, v in o.items()}
    if isinstance(o, list):
        return [scrub(v) for v in o]
    if isinstance(o, str):
        return re.sub(r'(wrkaus|sk)-[A-Za-z0-9._-]{16,}', r'\1-[REDACTED-BACKUP]', o)
    return o
json.dump(scrub(d), open(dst, 'w'), indent=2)
PY

for f in CLAUDE.md scheduled_tasks.json; do
  [ -f "$CLAUDE/$f" ] && cp "$CLAUDE/$f" "$REPO/harness/$f"
done
[ -f "$HOME/.workato/profiles" ] && cp "$HOME/.workato/profiles" "$REPO/harness/workato-profiles.json"
for f in "$HOME/.local/bin/"*; do
  [ -f "$f" ] && [ ! -L "$f" ] && cp "$f" "$REPO/harness/local-bin/"
done
cp "$HOME/Library/LaunchAgents/com.josh."*.plist "$REPO/launchagents/" 2>/dev/null || true

# --- git remotes: josh-knowledge + the kit (nightly auto-push) ---------------
# Both repos carry their own origin. Commit anything dirty and push, with a
# token-shaped-string scan on the staged diff: a hit REFUSES the push (reset,
# report). Up-to-date repos are a silent no-op. josh-orca above is the
# whole-harness snapshot; this is the two repos' own git history going remote.
auto_push() { # $1 = repo path, $2 = name
  local repo="$1" name="$2"
  git -C "$repo" rev-parse --is-inside-work-tree >/dev/null 2>&1 || return 0
  git -C "$repo" remote get-url origin >/dev/null 2>&1 || return 0
  if [ -n "$(git -C "$repo" status --porcelain 2>/dev/null)" ]; then
    git -C "$repo" add -A
    if git -C "$repo" diff --cached | grep -qE '(wrkaus|sk|ghp|github_pat)-?[A-Za-z0-9._-]{16,}'; then
      echo "harness-backup: $name push REFUSED — token-shaped string staged ($STAMP)"
      git -C "$repo" reset -q
      return 0
    fi
    git -C "$repo" commit -q -m "nightly auto-backup $STAMP" || true
  fi
  if git -C "$repo" push -q origin main 2>/dev/null; then
    REMOTE_NOTE="$REMOTE_NOTE
- $name: pushed ($(git -C "$repo" log --oneline -1 | head -c 60))"
  fi
}
REMOTE_NOTE=""
auto_push "$CLAUDE/knowledge" "josh-knowledge"
auto_push "$HOME/Documents/agentic-workato-kit" "workato-agentic-kit"

# manifest
cat > "$REPO/backup-manifest.md" << EOF
# Backup manifest
- Stamp: $STAMP
- skills: $(find "$REPO/harness/skills" -name SKILL.md 2>/dev/null | wc -l | tr -d ' ') skills
- agents: $(ls "$REPO/harness/agents" 2>/dev/null | wc -l | tr -d ' ') agents
- mods: $(ls "$REPO/mods" 2>/dev/null | tr '\n' ' ')
- knowledge files: $(find "$REPO/harness/knowledge" -type f 2>/dev/null | wc -l | tr -d ' ')
- recipe-history snapshots: $(find "$REPO/harness/recipe-history" -name '*.json' 2>/dev/null | wc -l | tr -d ' ')
- git remotes:$REMOTE_NOTE
- Settings secrets: redacted. Transcripts/keychain: never copied.
EOF

# --- commit + push -----------------------------------------------------------

cd "$REPO"
git add -A
if git diff --cached --quiet; then
  echo "harness-backup: no changes ($STAMP)"
else
  git commit -q -m "harness backup $STAMP"
  if [ -n "${BACKUP_REPO_URL:-}" ]; then
    git push -q origin main 2>/dev/null || git push -q origin master
    echo "harness-backup: committed + pushed ($STAMP)"
  else
    echo "harness-backup: committed LOCALLY only — set BACKUP_REPO_URL in config.sh to push ($STAMP)"
  fi
fi
