#!/usr/bin/env bash
# uninstall.sh — remove the agentic-workato-kit cleanly.
#
# Default: removes everything the kit installed (mods, agents, skills, bins,
# MCP registration, crons, launchd lanes, prod wrappers) and PRESERVES the
# knowledge tree (your accumulated claims, dreams, ledgers, canon — that's
# your data, not ours). Pass --purge to delete the knowledge tree too.
# Safe to run twice. Never touches: your shell profiles, keychain entries,
# Claude Code itself, or anything the kit didn't install.

set -uo pipefail

PURGE=0
[ "${1:-}" = "--purge" ] && PURGE=1

KIT_AGENTS="brain-gardener workato-watchdog estate-architect promotion-orchestrator harness-dreamer cortex"
KIT_SKILLS="airo-mcp-playbook workato-development-playbook jira-story-standards squad-build platform-onboarding harness-dreamer"
KIT_BINS="wt-prod workato-prod brain-mcp dream-mini harness-backup"
# wt is kit-installed but may be customized; remove only the kit's copy
KIT_LANES="com.josh.dream-mini com.josh.workato-docs-watch"

say() { printf '  %s\n' "$1"; }
echo "== agentic-workato-kit uninstall =="

# 1. mods
for m in workato-guardrails brain-guard; do
  if claude plugin uninstall "${m}@josh-mods" >/dev/null 2>&1; then
    say "mod removed: $m"
  else
    say "mod not installed (skipped): $m"
  fi
done

# 2. MCP registration
if claude mcp list 2>/dev/null | grep -q "^brain:"; then
  claude mcp remove brain >/dev/null 2>&1 && say "mcp removed: brain" || say "mcp removal failed: brain"
else
  say "mcp not registered (skipped): brain"
fi

# 3. launchd lanes
for lane in $KIT_LANES; do
  P="${HOME}/Library/LaunchAgents/${lane}.plist"
  if [ -f "$P" ]; then
    launchctl unload "$P" 2>/dev/null || true
    rm -f "$P" && say "launchd lane removed: $lane"
  fi
done

# 4. crons (project-scoped scheduled tasks with kit prompts)
python3 - << 'PY' 2>/dev/null || true
import json, os, sys
kit_tags = ("[brain-gardener", "[workato-watchdog", "[estate-architect",
            "[corpus-indexer", "[docs-watch", "[harness-backup",
            "[harness-dreamer", "[morning-brief")
for root in (os.path.expanduser("~/Documents"),):
    for dirpath, _, files in os.walk(root):
        if ".claude" not in dirpath:
            continue
        st = os.path.join(dirpath, "scheduled_tasks.json")
        if not os.path.exists(st):
            continue
        try:
            d = json.load(open(st))
        except Exception:
            continue
        tasks = d.get("tasks", [])
        keep = [t for t in tasks if not str(t.get("prompt", "")).startswith(kit_tags)]
        if len(keep) != len(tasks):
            d["tasks"] = keep
            json.dump(d, open(st, "w"), indent=2)
            print(f"  crons removed from {st}: {len(tasks) - len(keep)}")
PY

# 5. agents + skills
for a in $KIT_AGENTS; do
  [ -f "${HOME}/.claude/agents/${a}.md" ] && rm -f "${HOME}/.claude/agents/${a}.md" && say "agent removed: $a"
done
for sk in $KIT_SKILLS; do
  [ -d "${HOME}/.claude/skills/${sk}" ] && rm -rf "${HOME}/.claude/skills/${sk}" && say "skill removed: $sk"
done

# 6. bins
for b in $KIT_BINS; do
  [ -e "${HOME}/.local/bin/${b}" ] && rm -f "${HOME}/.local/bin/${b}" && say "bin removed: $b"
done

# 7. knowledge tree
K="${HOME}/.claude/knowledge"
if [ "$PURGE" = "1" ]; then
  rm -rf "$K" && say "knowledge tree PURGED (${K})"
else
  say "knowledge tree preserved: ${K} (pass --purge to delete)"
fi

# 8. mods source (~/mods) — only remove the two kit plugins, keep the folder
for m in workato-guardrails brain-guard; do
  [ -d "${HOME}/mods/${m}" ] && rm -rf "${HOME}/mods/${m}" && say "mod source removed: ~/mods/${m}"
done
[ -f "${HOME}/mods/.claude-plugin/marketplace.json" ] && {
  if [ -z "$(ls -A "${HOME}/mods" | grep -v '^.claude-plugin$' | head -1)" ]; then
    claude plugin marketplace remove josh-mods >/dev/null 2>&1 && say "marketplace removed: josh-mods"
    rm -rf "${HOME}/mods/.claude-plugin" && say "mods dir emptied"
  else
    say "mods dir kept (other plugins present)"
  fi
}

echo
echo "== done =="
echo "Left in place: keychain tokens, shell profile env vars, Claude Code itself,"
echo "and the kit checkout ($(pwd)). Delete those by hand if you want them gone."
[ "$PURGE" = "0" ] && echo "Reinstall any time: ./onboard.sh && ./install.sh && ./verify.sh"
