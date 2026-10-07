#!/usr/bin/env bash
# agentic-workato-kit installer
# Installs: 2 mods (workato-guardrails, brain-guard), 4 agents
# (brain-gardener, workato-watchdog, estate-architect, promotion-orchestrator),
# the knowledge-tree scaffold + scripts, and the weekly/nightly schedules.
#
# Prerequisites (checked below): Claude Code >= 2.1.287, git, python3, jq.
# You must ALSO connect these MCP servers in Claude Code before anything
# Workato-facing works: your AIRO MCP (dev + prod), the dependency tracker,
# and Atlassian. See README.md.
set -euo pipefail

cd "$(dirname "$0")"

echo "== agentic-workato-kit installer =="

# --- prerequisites ---------------------------------------------------------
command -v git >/dev/null    || { echo "FAIL: git not found"; exit 1; }
command -v python3 >/dev/null || { echo "FAIL: python3 not found"; exit 1; }
command -v jq >/dev/null     || { echo "FAIL: jq not found (brew install jq)"; exit 1; }
CC_VERSION=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0")
echo "Claude Code: ${CC_VERSION}"
python3 -c "import sys; v=tuple(int(x) for x in '$CC_VERSION'.split('.')); sys.exit(0 if v >= (2,1,287) else 1)" \
  && echo "mod support: OK" || { echo "FAIL: mods need Claude Code >= 2.1.287"; exit 1; }

# --- config ----------------------------------------------------------------
if [ ! -f config.sh ]; then
  cp config.example.sh config.sh
  echo "NOTE: created config.sh from the example — EDIT IT (workspace IDs, Jira field IDs), then re-run ./install.sh"
  echo "      (the kit is installed but agents will reference placeholder values until you do)"
fi
source config.sh

render() {
  # render <src> <dest>: token substitution via python (config values may
  # contain |, /, [] — sed delimiters are not safe here)
  python3 - "$1" "$2" << 'PYEOF'
import sys, os
src, dest = sys.argv[1], sys.argv[2]
text = open(src).read()
repl = {
    '{{HOME}}': os.environ.get('KIT_HOME', os.environ['HOME']),
    '{{WORKSPACE_DEV}}': os.environ.get('WORKSPACE_DEV', ''),
    '{{WORKSPACE_PROD}}': os.environ.get('WORKSPACE_PROD', ''),
    '{{ENV_DEV_NAME}}': os.environ.get('ENV_DEV_NAME', ''),
    '{{ENV_PROD_NAME}}': os.environ.get('ENV_PROD_NAME', ''),
    '{{JIRA_CLOUD_ID}}': os.environ.get('JIRA_CLOUD_ID', ''),
    '{{JIRA_PROJECT}}': os.environ.get('JIRA_PROJECT', ''),
    '{{GOVERNING_EPIC}}': os.environ.get('GOVERNING_EPIC', ''),
    '{{FIELD_MANIFEST}}': os.environ.get('FIELD_MANIFEST', ''),
    '{{FIELD_ENV_CASCADE}}': os.environ.get('FIELD_ENV_CASCADE', ''),
    '{{FIELD_SOURCE_ENV}}': os.environ.get('FIELD_SOURCE_ENV', ''),
    '{{FIELD_POINTS}}': os.environ.get('FIELD_POINTS', ''),
    '{{PROJECT_PATH}}': os.environ.get('PROJECT_PATH', ''),
}
pp = repl['{{PROJECT_PATH}}']
repl['{{PROJECT_SLUG}}'] = '-' + pp.lstrip('/').replace('/', '-') if pp else ''
for k, v in repl.items():
    text = text.replace(k, v)
os.makedirs(os.path.dirname(dest) or '.', exist_ok=True)
open(dest, 'w').write(text)
PYEOF
}

# --- 1. agents -------------------------------------------------------------
mkdir -p "${KIT_HOME}/.claude/agents"
for a in agents/*.md; do
  render "$a" "${KIT_HOME}/.claude/agents/$(basename "$a")"
  echo "agent installed: $(basename "$a" .md)"
done

# --- 2. knowledge tree + scripts -------------------------------------------
K="${KIT_HOME}/.claude/knowledge"
mkdir -p "${K}/domains" "${K}/projects" "${K}/scripts" "${K}/claims" \
         "${K}/garden-reports" "${K}/architecture" "${K}/replay-fixtures"
for f in knowledge/scripts/*; do render "$f" "${K}/scripts/$(basename "$f")"; done
chmod +x "${K}/scripts/"*.py 2>/dev/null || true
[ -f "${K}/claims/claims.jsonl" ] || echo '[]' > /dev/null # claims seeded empty
touch "${K}/claims/claims.jsonl"
[ -f "${K}/INDEX.md" ] || render "knowledge/INDEX.template.md" "${K}/INDEX.md"

# git the knowledge tree (proposals-as-branches need it)
if [ ! -d "${K}/.git" ]; then
  git -C "${K}" init -q
  git -C "${K}" add -A
  git -C "${K}" -c user.name="agentic-workato-kit" -c user.email="kit@local" commit -q -m "Knowledge tree scaffold" --allow-empty
fi

# --- 3. mods ----------------------------------------------------------------
mkdir -p "${KIT_HOME}/mods"
cp -R mods/* "${KIT_HOME}/mods/"
# render hardcoded homes inside the hooks
for f in "${KIT_HOME}/mods/"*/hooks/register.js; do
  sed -i '' "s|{{HOME}}|${KIT_HOME}|g" "$f" 2>/dev/null || \
  sed -i "s|{{HOME}}|${KIT_HOME}|g" "$f"
done
for m in workato-guardrails brain-guard; do
  if [ "${KIT_SKIP_INSTALL:-0}" = "1" ]; then
    echo "mod: ${m} (KIT_SKIP_INSTALL=1 — skipped claude plugin install)"
  else
    claude plugin marketplace add "${KIT_HOME}/mods" >/dev/null 2>&1 || true
    claude plugin install "${m}@josh-mods" >/dev/null 2>&1 && echo "mod installed: ${m}" || \
      echo "mod: ${m} — run: claude plugin install ${m}@josh-mods"
  fi
done

# --- 4. skills (optional, template) -----------------------------------------
mkdir -p "${KIT_HOME}/.claude/skills"
cp -R skills/* "${KIT_HOME}/.claude/skills/" 2>/dev/null || true
echo "skills installed (adapt to your team's conventions)"

# --- 5. done -----------------------------------------------------------------
cat << 'NEXT'

== Installed. Next steps (manual, one-time): ==
1. Connect MCP servers in Claude Code: AIRO MCP (dev + prod), dependency
   tracker, Atlassian. The kit cannot do this — it needs YOUR accounts.
2. /reload-plugins (or restart) so the mods load.
3. Fill config.sh if you skipped it, re-run ./install.sh, restart again.
4. Smoke test: /guardrails (lists the hooks), /builds (ledger, starts empty),
   then ask for a "watchdog run" for your workspaces.
Schedules (brain gardener 22:43, docs-watch 22:31 + launchd 22:15, watchdog
23:13, corpus Mon 06:07, estate architect Mon 06:37) are per-project cron
tasks — create them from your default work project; the prompts live in
schedules/ in this kit.
NEXT
