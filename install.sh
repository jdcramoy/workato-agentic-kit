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
  if [ -t 0 ]; then
    echo "No config.sh found — starting onboarding (answer ~14 questions, get config.sh):"
    exec ./onboard.sh   # runs install.sh at the end
  else
    cp config.example.sh config.sh
    echo "NOTE: no config.sh and stdin is not a terminal, so onboarding was skipped."
    echo "      Installed from the example — either run ./onboard.sh (interactive) or"
    echo "      edit config.sh by hand, then re-run ./install.sh"
  fi
fi
source config.sh
# placeholder guard: empty workspace IDs produce agents that point at nothing
if [ -z "${WORKSPACE_DEV:-}" ]; then
  echo "WARNING: WORKSPACE_DEV is empty — agents will reference blank workspace IDs."
  echo "         Run ./onboard.sh to fix, then re-run ./install.sh"
fi
if [ "${WORKSPACE_DEV:-}" = "3535597" ] || [ "${WORKSPACE_PROD:-}" = "3535597" ]; then
  echo "NOTE: workspace 3535597 is the kit author's dev workspace; make sure that is intended."
fi

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
    '{{PROFILE_DEV}}': os.environ.get('PROFILE_DEV', 'josh-us'),
    '{{PROFILE_PROD}}': os.environ.get('PROFILE_PROD', 'josh-prod'),
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

# --- 2b. dreams scaffold (dreamer + gossip bus) ------------------------------
D="${K}/dreams"
mkdir -p "${D}/bus" "${D}/proposals" "${D}/data" "${D}/visions"
mkdir -p "${KIT_HOME}/.claude/knowledge/cortex" "${KIT_HOME}/.claude/knowledge/regression-canon"
touch "${KIT_HOME}/.claude/knowledge/cortex/questions.jsonl" "${KIT_HOME}/.claude/knowledge/regression-canon/canon.jsonl"
for a in docs-watch brain-gardener workato-watchdog harness-dreamer estate-architect promotion-orchestrator cortex; do
  touch "${D}/bus/${a}.jsonl"
done
[ -f "${D}/config.json" ] || cp "$(pwd)/knowledge/dreams/config.example.json" "${D}/config.json"
echo "dreams scaffold: trust ladder + gossip outboxes ready (mode: $(python3 -c "import json;print(json.load(open('${D}/config.json'))['mode'])" 2>/dev/null || echo report))"

# git the knowledge tree (proposals-as-branches need it)
if [ ! -d "${K}/.git" ]; then
  git -C "${K}" init -q
  git -C "${K}" add -A
  git -C "${K}" -c user.name="agentic-workato-kit" -c user.email="kit@local" commit -q -m "Knowledge tree scaffold" --allow-empty
fi

# --- 3. mods ----------------------------------------------------------------
mkdir -p "${KIT_HOME}/mods"
cp -R mods/* "${KIT_HOME}/mods/"

# --- Workato KB (RAG++ pipeline): cloned from its own repo (single source of truth) ---
KB_HOME="${KIT_HOME}/Documents/workato-kb"
if [ -d "$KB_HOME/.git" ]; then
  echo "kb: exists — pulling latest"
  git -C "$KB_HOME" pull --ff-only || echo "kb: pull skipped (local changes)"
else
  echo "kb: cloning the pipeline (github.com/Workato-All/workato-kb)..."
  git clone --depth 1 "https://github.com/Workato-All/workato-kb.git" "$KB_HOME" \
    || echo "WARN: kb clone failed — the RAG++ layer won't be available (see kb-pipeline/README.md for manual setup)"
fi
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

# --- 4. skills (playbooks + conventions) ------------------------------------
mkdir -p "${KIT_HOME}/.claude/skills"
# render skill files too (they reference home paths)
find skills -type f \( -name "*.md" -o -name "*.yaml" \) | while read -r f; do
  dest="${KIT_HOME}/.claude/skills/${f#skills/}"
  render "$f" "$dest"
done
echo "skills installed: airo-mcp-playbook, workato-development-playbook, jira-story-standards"

# --- 4b. wt — Workato Toolbox (Developer API wrapper) ------------------------
mkdir -p "${KIT_HOME}/.local/bin"
cp bin/wt "${KIT_HOME}/.local/bin/wt"
chmod +x "${KIT_HOME}/.local/bin/wt"
for w in wt-prod workato-prod prod-bypass; do
  render "bin/$w" "${KIT_HOME}/.local/bin/$w"
  chmod +x "${KIT_HOME}/.local/bin/$w"
done
echo "prod wrappers installed: wt-prod, workato-prod, prod-bypass (keychain account: ${PROFILE_PROD:-josh-prod})"
case ":$PATH:" in
  *":${KIT_HOME}/.local/bin:"*) echo "wt installed: ${KIT_HOME}/.local/bin/wt (on PATH)" ;;
  *) echo "wt installed: ${KIT_HOME}/.local/bin/wt — add ~/.local/bin to your PATH" ;;
esac
echo "wt auth: set WORKATO_API_TOKEN or store a token via workato-platform-cli (keychain)."

# --- 4c. brain MCP server (read-only knowledge access for any agent) ---------
cp bin/brain-mcp "${KIT_HOME}/.local/bin/brain-mcp"
chmod +x "${KIT_HOME}/.local/bin/brain-mcp"
if [ "${KIT_SKIP_INSTALL:-0}" != "1" ]; then
  claude mcp add brain --scope user -- "${KIT_HOME}/.local/bin/brain-mcp" >/dev/null 2>&1 \
    && echo "mcp registered: brain (read-only)" || echo "mcp: brain — register later with: claude mcp add brain -- ~/.local/bin/brain-mcp"
fi

# --- 5. done -----------------------------------------------------------------
cat << 'NEXT'

== Installed. Next steps (manual, one-time): ==
1. Connect MCP servers in Claude Code: AIRO MCP (dev + prod), dependency
   tracker, Atlassian. The kit cannot do this — it needs YOUR accounts.
2. /reload-plugins (or restart) so the mods load.
3. Fill config.sh if you skipped it, re-run ./install.sh, restart again.
4. Run ./verify.sh — 32 checks; fix any FAIL it reports.
5. Smoke test: /guardrails (lists the hooks), /builds (ledger, starts empty),
   then ask for a "watchdog run" for your workspaces.
Schedules (docs-watch 22:31 + launchd 22:15, brain gardener 22:43, watchdog
23:13, harness backup 23:33, harness dreamer 23:43, corpus Mon 06:07, estate
architect Mon 06:37) are per-project cron tasks — create them from your
default work project; the prompts live in schedules/ in this kit. The
nightly order matters: docs-watch feeds the gossip bus first, the dreamer
runs last as reader-in-chief.
5. Prod CLI access: store the prod API token in the keychain
   (security add-generic-password -s workato-platform-cli -a ${PROFILE_PROD:-josh-prod}
   -w <token> -U), then workato-prod / wt-prod target production; every prod
   write is held for confirmation by guardrails hook 13.
NEXT
