#!/usr/bin/env bash
# Obsidian brain-vault: one vault of symlinks spanning the knowledge tree,
# skills, the KB repo, and the KB corpus so the whole brain is browsable
# (and graphable) in Obsidian. Edits write through the symlinks; the repos
# stay canonical.
#
#   bash obsidian-vault.sh [vault-dir]
#
# Default vault: ~/Documents/brain-vault. Open it with Obsidian:
# "Open folder as vault". Keep the vault LOCAL-ONLY — the knowledge people/
# files must never go through a sync service. Exclude *.jsonl in Obsidian's
# Files & Links settings to keep the graph clean.

set -euo pipefail

VAULT="${1:-$HOME/Documents/brain-vault}"
CLAUDE_DIR="$HOME/.claude"
KB_CORPUS="$HOME/.claude/workato-kb/corpus"

mkdir -p "$VAULT"

link() {
  local name="$1" target="$2"
  if [ -e "$target" ]; then
    ln -sfn "$target" "$VAULT/$name"
    echo "  $name -> $target"
  else
    echo "  skip $name (missing: $target)" >&2
  fi
}

echo "Creating brain-vault at $VAULT:"
link "knowledge" "$CLAUDE_DIR/knowledge"
link "skills"    "$CLAUDE_DIR/skills"
link "workato-kb" "$HOME/Documents/workato-kb"
link "memory"    "$CLAUDE_DIR/projects/-Users-joshcramoy-Documents-workbench/memory"
link "kb-corpus" "$KB_CORPUS"

cat <<'NOTE'

Next steps in Obsidian:
  1. Open folder as vault -> the directory above.
  2. Settings -> Files & Links -> Excluded files: add "*.jsonl" (and
     ".venv/**" if the kb repo is linked) to keep the graph clean.
  3. Graph view -> Groups: color by path (knowledge / skills / kb-corpus)
     to make the clusters legible.
  4. Keep this vault local-only. Never enable Obsidian Sync or Publish on
     it — the knowledge tree contains people files that must not leave
     the machine.

NOTE
