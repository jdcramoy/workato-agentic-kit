#!/usr/bin/env bash
# verify.sh — post-install doctor for the agentic-workato-kit.
# Read-only: reports PASS / WARN / FAIL per layer and exits non-zero only on
# hard failures. Run after ./install.sh, and any time something feels off.

set -uo pipefail
cd "$(dirname "$0")"

PASS=0; WARN=0; FAIL=0
row() { # row <status> <check> <detail>
  local icon; case "$1" in PASS) icon="✓"; PASS=$((PASS+1));; WARN) icon="~"; WARN=$((WARN+1));; *) icon="✗"; FAIL=$((FAIL+1));; esac
  printf "  %s %-4s %-28s %s\n" "$icon" "$1" "$2" "$3"
}

echo "== agentic-workato-kit doctor =="

# --- 1. prereqs ---------------------------------------------------------------
command -v git >/dev/null && row PASS "git" "$(git --version | cut -d' ' -f1-3)" || row FAIL "git" "not found"
command -v python3 >/dev/null && row PASS "python3" "$(python3 -V 2>&1)" || row FAIL "python3" "not found"
command -v jq >/dev/null && row PASS "jq" "$(jq --version 2>&1)" || row WARN "jq" "not found (brew install jq)"
CCV=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0")
python3 -c "import sys; v=tuple(int(x) for x in '$CCV'.split('.')); sys.exit(0 if v >= (2,1,287) else 1)" \
  && row PASS "claude code" "$CCV" || row FAIL "claude code" "$CCV — mods need >= 2.1.287"

# --- 2. config ----------------------------------------------------------------
if [ -f config.sh ]; then
  # shellcheck disable=SC1091
  source config.sh
  [ -n "${WORKSPACE_DEV:-}" ] && row PASS "config.sh" "dev ws ${WORKSPACE_DEV}" || row FAIL "config.sh" "WORKSPACE_DEV empty — run ./onboard.sh"
  [ -n "${WORKSPACE_PROD:-}" ] && row PASS "prod config" "prod ws ${WORKSPACE_PROD}" || row WARN "prod config" "no prod workspace — wrappers will not work"
  [ -n "${BACKUP_REPO_URL:-}" ] && row PASS "backup config" "${BACKUP_REPO_URL##*/}" || row WARN "backup config" "no origin URL — local-only commits"
else
  row FAIL "config.sh" "missing — run ./onboard.sh"
fi

# --- 3. bins ------------------------------------------------------------------
for b in wt wt-prod workato workato-prod harness-backup; do
  command -v "$b" >/dev/null && row PASS "bin: $b" "$(command -v "$b")" || row FAIL "bin: $b" "not on PATH (~/.local/bin?)"
done

# --- 4. keychain + live identity (the real check) -----------------------------
if command -v wt >/dev/null && [ -n "${WORKSPACE_DEV:-}" ]; then
  GOT=$(wt api GET /api/users/me 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ "$GOT" = "$WORKSPACE_DEV" ] && row PASS "dev identity" "live ws $GOT matches config" \
    || row FAIL "dev identity" "got '${GOT:-none}', expected $WORKSPACE_DEV (token missing/wrong?)"
fi
if command -v wt-prod >/dev/null && [ -n "${WORKSPACE_PROD:-}" ]; then
  GOT=$(wt-prod api GET /api/users/me 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null)
  [ "$GOT" = "$WORKSPACE_PROD" ] && row PASS "prod identity" "live ws $GOT matches config" \
    || row FAIL "prod identity" "got '${GOT:-none}', expected $WORKSPACE_PROD (keychain entry missing? see README)"
fi

# --- 5. mods ------------------------------------------------------------------
PL=$(claude plugin list 2>/dev/null)
for m in workato-guardrails brain-guard; do
  echo "$PL" | grep -q "$m" && row PASS "mod: $m" "$(echo "$PL" | grep -A1 "$m" | grep -oE 'Version: [0-9.]+' | head -1)" \
    || row FAIL "mod: $m" "not installed (claude plugin install $m@josh-mods)"
done

# --- 6. knowledge + dreams ----------------------------------------------------
K="${HOME}/.claude/knowledge"
[ -f "${K}/INDEX.md" ] && row PASS "knowledge tree" "$(find "$K" -name '*.md' | wc -l | tr -d ' ') files" || row FAIL "knowledge tree" "INDEX.md missing"
[ -d "${K}/.git" ] && row PASS "knowledge git" "repo initialized" || row WARN "knowledge git" "not a repo (proposals-as-branch disabled)"
[ -f "${K}/dreams/config.json" ] && row PASS "dreamer config" "mode: $(python3 -c "import json;print(json.load(open('${K}/dreams/config.json'))['mode'])" 2>/dev/null || echo '?')" \
  || row WARN "dreamer config" "missing (dreamer runs as report)"
N_OUT=$(ls "${K}/dreams/bus/"*.jsonl 2>/dev/null | wc -l | tr -d ' ')
[ "${N_OUT:-0}" -ge 6 ] && row PASS "gossip bus" "$N_OUT outboxes" || row WARN "gossip bus" "$N_OUT outboxes (expected >= 6)"

# --- 7. agents + skills -------------------------------------------------------
for a in brain-gardener workato-watchdog estate-architect promotion-orchestrator; do
  [ -f "${HOME}/.claude/agents/$a.md" ] && row PASS "agent: $a" "installed" || row FAIL "agent: $a" "missing"
done
for sk in airo-mcp-playbook workato-development-playbook; do
  [ -f "${HOME}/.claude/skills/$sk/SKILL.md" ] && row PASS "skill: $sk" "installed" || row FAIL "skill: $sk" "missing"
done
[ -f "${HOME}/.claude/agents/harness-dreamer.md" ] && row PASS "agent: harness-dreamer" "installed" || row FAIL "agent: harness-dreamer" "missing"

# --- 8. MCP servers -----------------------------------------------------------
# health checks are occasionally flaky right after other CLI calls: one retry
mcp_check() { # mcp_check <server-name-substring>
  local i
  for i in 1 2; do
    MCP=$(cd "${PROJECT_PATH:-$HOME/Documents/workbench}" && claude mcp list 2>/dev/null)
    echo "$MCP" | grep -q "$1.*Connected" && return 0
    [ "$i" = 1 ] && sleep 3
  done
  return 1
}
mcp_check "workato-airo-mcp-server" && row PASS "mcp: airo dev" "connected" || row WARN "mcp: airo dev" "not connected"
mcp_check "workato-dependency-tracker" && row PASS "mcp: dependency tracker" "connected" || row WARN "mcp: dependency tracker" "not connected"
mcp_check "workato-airo-mcp-prod" && row PASS "mcp: airo prod" "connected" || row WARN "mcp: airo prod" "not connected (only needed for prod reviews)"

# --- 9. crons -----------------------------------------------------------------
ST="${PROJECT_PATH:-$HOME/Documents/workbench}/.claude/scheduled_tasks.json"
if [ -f "$ST" ]; then
  N_TAGS=$(python3 -c "
import json
d=json.load(open('$ST'))
print(sum(1 for t in d.get('tasks',[]) if str(t.get('prompt','')).startswith('[')))" 2>/dev/null)
  [ "${N_TAGS:-0}" -ge 5 ] && row PASS "crons" "$N_TAGS tagged self-rearming jobs" \
    || row WARN "crons" "$N_TAGS tagged jobs (expected >= 5) — see schedules/README.md"
else
  row WARN "crons" "no scheduled_tasks.json at $ST"
fi

# --- 10. backup ---------------------------------------------------------------
[ -d "${BACKUP_REPO_LOCAL:-/nonexistent}/.git" ] && row PASS "backup repo" "last commit: $(git -C "${BACKUP_REPO_LOCAL}" log -1 --format='%cs')" \
  || row WARN "backup repo" "not initialized"

echo
echo "== $PASS pass, $WARN warn, $FAIL fail =="
[ "$FAIL" -eq 0 ] && echo "Hard failures: none. WARNs are optional layers you can live without." \
  || echo "Fix FAILs (run ./onboard.sh if config-shaped), then re-run ./verify.sh"
exit $(( FAIL > 0 ? 1 : 0 ))
