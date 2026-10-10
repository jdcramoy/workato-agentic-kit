#!/usr/bin/env bash
# getting-started.sh — post-install adoption walkthrough for the
# agentic-workato-kit. Runs AFTER onboard.sh + install.sh + verify.sh: it does
# not collect config and does not install anything. Each step explains a layer,
# probes your machine for its live state (never a memory of the last run),
# offers the exact command or the manual part, re-probes, and records the
# result. Resumable: progress lives in ~/.claude/getting-started-state.json
# (step statuses only, never tokens or IDs). Re-running jumps through the
# steps, re-probing each; flags: --status prints the checklist and exits,
# --reset clears state.

set -euo pipefail
cd "$(dirname "$0")"

STATE_FILE="${HOME}/.claude/getting-started-state.json"
KIT_DIR="$(pwd)"

# --- config -------------------------------------------------------------------
if [ -f config.sh ]; then
  # shellcheck disable=SC1091
  source config.sh
fi
PROJECT_PATH="${PROJECT_PATH:-$HOME/Documents/workbench}"
PROFILE_DEV="${PROFILE_DEV:-dev}"
PROFILE_PROD="${PROFILE_PROD:-prod}"
WORKSPACE_DEV="${WORKSPACE_DEV:-}"
WORKSPACE_PROD="${WORKSPACE_PROD:-}"

# --- flags --------------------------------------------------------------------
for arg in "$@"; do
  case "$arg" in
    --reset) rm -f "$STATE_FILE"; echo "state cleared: $STATE_FILE"; exit 0 ;;
    --status) exec bash "$0" --status-run ;;
    -h|--help)
      echo "usage: ./getting-started.sh [--status | --reset]"
      echo "  (no flags)  interactive walkthrough, resumes where you left off"
      echo "  --status    print the checklist non-interactively and exit"
      echo "  --reset     clear the state file and start over"
      exit 0 ;;
  esac
done

# --- state (statuses + timestamps only; never secrets) --------------------------
mark() { # mark <step-id> <done|skipped|todo>
  python3 - "$1" "$2" "$STATE_FILE" <<'PY'
import json, os, sys, datetime
step, status, path = sys.argv[1], sys.argv[2], sys.argv[3]
os.makedirs(os.path.dirname(path), exist_ok=True)
try:
    d = json.load(open(path))
except Exception:
    d = {"steps": {}}
now = datetime.datetime.now().isoformat(timespec="seconds")
d.setdefault("steps", {})[step] = {"status": status, "ts": now}
d["updated"] = now
json.dump(d, open(path, "w"), indent=1)
PY
  chmod 600 "$STATE_FILE" 2>/dev/null || true
}

state_of() { # state_of <step-id> -> done|skipped|todo|todo (missing file = todo)
  python3 - "$STATE_FILE" "$1" <<'PY' 2>/dev/null || echo todo
import json, sys
d = json.load(open(sys.argv[1]))
print(d.get("steps", {}).get(sys.argv[2], {}).get("status", "todo"))
PY
}

# --- prompts (EOF takes the safe default, never spins) --------------------------
ask() { # ask <question> <default y|n> -> 0 on yes
  local q="$1" def="${2:-n}" v="" hint="[y/N]"
  [ "$def" = "y" ] && hint="[Y/n]"
  printf "\n%s %s: " "$q" "$hint"
  if ! read -r v; then v="$def"; else [ -z "$v" ] && v="$def"; fi
  case "$v" in [Yy]|[Yy][Ee][Ss]) return 0 ;; *) return 1 ;; esac
}

offer_run() { # offer_run <command> — shows it, asks, runs; EOF/skip = no
  echo "  command:"
  echo "    $1"
  if ask "Run it now?" n; then
    echo "  running ..."
    bash -c "$1"
  else
    echo "  (left for you to run manually)"
  fi
}

# after guidance: re-probe, and record what the probe actually showed
settle() { # settle <step-id> <re-probe-command>  ($? of probe decides)
  local id="$1"; shift
  if "$@"; then
    echo "  probe: passing."
    mark "$id" done
  elif ask "Still failing. Skip this step for now? (EOF/left = stays todo)" n; then
    mark "$id" skipped
  else
    mark "$id" todo
  fi
}

# --- probes ---------------------------------------------------------------------
probe_mcp() { # live: each expected server shows Connected in claude mcp list
  local list ok=0
  list=$(cd "$PROJECT_PATH" 2>/dev/null && claude mcp list 2>/dev/null || true)
  for s in workato-airo-mcp-server workato-airo-mcp-prod workato-dependency-tracker atlassian; do
    if echo "$list" | grep -q "$s.*Connected"; then
      echo "  ✓ $s connected"
    else
      echo "  ✗ $s not connected"
      ok=1
    fi
  done
  return "$ok"
}

probe_keychain() { # live: wt talks to the API and returns the configured ws id
  local ok=0 got=""
  if command -v wt >/dev/null && [ -n "$WORKSPACE_DEV" ]; then
    got=$(wt api GET /api/users/me 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
    if [ "$got" = "$WORKSPACE_DEV" ]; then echo "  ✓ dev identity: live ws $got matches config"
    else echo "  ✗ dev identity: got '${got:-none}', expected $WORKSPACE_DEV"; ok=1; fi
  fi
  if command -v wt-prod >/dev/null && [ -n "$WORKSPACE_PROD" ]; then
    got=$(wt-prod api GET /api/users/me 2>/dev/null | python3 -c "import sys,json;print(json.load(sys.stdin).get('id',''))" 2>/dev/null || true)
    if [ "$got" = "$WORKSPACE_PROD" ]; then echo "  ✓ prod identity: live ws $got matches config"
    else echo "  ✗ prod identity: got '${got:-none}', expected $WORKSPACE_PROD"; ok=1; fi
  fi
  return "$ok"
}

probe_settings() { # settings.json parses + carries the prod-write ask gate
  python3 - "${HOME}/.claude/settings.json" <<'PY'
import json, sys
try:
    d = json.load(open(sys.argv[1]))
except FileNotFoundError:
    print("  ✗ ~/.claude/settings.json does not exist"); sys.exit(1)
except Exception as e:
    print(f"  ✗ ~/.claude/settings.json does not parse: {e}"); sys.exit(1)
p = d.get("permissions", {})
rules = list(p.get("ask", [])) + list(p.get("allow", []))
hits = [r for r in rules if "workato-airo-mcp-prod" in r]
if hits:
    print("  ✓ settings.json parses; prod MCP gate present: " + ", ".join(hits[:3]))
    sys.exit(0)
print("  ✗ settings.json parses but has no prod MCP permission rule")
sys.exit(1)
PY
}

probe_plugins() { # both mods show in claude plugin list
  local ok=0 pl
  pl=$(claude plugin list 2>/dev/null || true)
  for m in workato-guardrails brain-guard; do
    if echo "$pl" | grep -q "$m"; then echo "  ✓ mod installed: $m"
    else echo "  ✗ mod not installed: $m"; ok=1; fi
  done
  return "$ok"
}

probe_schedules() { # tagged self-rearming cron tasks in the work project
  local st="${PROJECT_PATH}/.claude/scheduled_tasks.json" n=""
  n=$(python3 -c "
import json
d=json.load(open('$st'))
print(sum(1 for t in d.get('tasks',[]) if str(t.get('prompt','')).startswith('[')))" 2>/dev/null || echo 0)
  if [ "${n:-0}" -ge 5 ]; then echo "  ✓ $n tagged self-rearming cron tasks in $PROJECT_PATH"; return 0; fi
  echo "  ✗ ${n:-0} tagged cron tasks (expected >= 5) — schedules not created yet"
  return 1
}

probe_ladder() { # trust-ladder config exists and reads back a mode
  local mode
  mode=$(python3 -c "import json;print(json.load(open('${HOME}/.claude/knowledge/dreams/config.json'))['mode'])" 2>/dev/null || true)
  if [ -n "$mode" ]; then echo "  ✓ trust ladder configured, mode: $mode"; return 0; fi
  echo "  ✗ no trust-ladder config (dreamer would run as report by default)"
  return 1
}

# --- non-interactive checklist ---------------------------------------------------
if [ "${1:-}" = "--status-run" ]; then
  echo "== getting-started checklist =="
  printf "  %-12s %s\n" "step" "status"
  for s in verify mcp settings keychain plugins schedules ladder firsttask; do
    printf "  %-12s %s\n" "$s" "$(state_of "$s")"
  done
  echo
  echo "state file: $STATE_FILE"
  echo "re-run:     ./getting-started.sh   (re-probes everything, resumes at the first todo)"
  exit 0
fi

# --- walkthrough -----------------------------------------------------------------
cat <<'EOT'
== agentic-workato-kit getting started ==
onboard.sh collected your config, install.sh installed the pieces, verify.sh
reports pass/fail. This walkthrough is the layer between install and fluency:
each step probes your machine live, tells you exactly what to do, and records
what actually happened. Press return to accept [defaults]; EOF is always safe.

EOT

if [ -f "$STATE_FILE" ]; then
  echo "progress so far (from the last run; every probe below is live regardless):"
  bash "$0" --status-run | sed -n '2,12p'
fi

# -- step 1: the doctor ------------------------------------------------------------
echo
echo "== step 1 of 8: verify.sh, the doctor =="
cat <<'EOT'
verify.sh runs 32 read-only checks across prereqs, config, binaries, live dev
and prod identities, mods, the knowledge tree, agents, skills, MCP health,
crons, and backup. Run it first so the rest of this walkthrough starts from
where you actually are, not where the installer hopes you are. The FAIL and
WARN lines it prints are what the following steps resolve or explain.
EOT
echo "  running ./verify.sh ..."
VOUT=$(./verify.sh 2>&1 || true)
echo "$VOUT" | grep '✗' | head -12 || true
VFAIL=$(echo "$VOUT" | grep -oE '[0-9]+ fail' | grep -oE '[0-9]+' | tail -1 || echo 0)
echo "  summary: $(echo "$VOUT" | grep -E '^== [0-9]+ pass' | tail -1 || echo 'verify.sh did not print a summary')"
mark verify done
echo "  (recorded: done — the step is running it; the findings drive the next steps)"

# -- step 2: MCP authorization ------------------------------------------------------
echo
echo "== step 2 of 8: MCP authorization (the step people skip) =="
cat <<'EOT'
Every Workato-facing capability rides on four MCP servers, and each needs YOUR
account: the kit cannot do your OAuth. Registration (claude mcp add) and
authentication (the /mcp OAuth flow inside Claude Code) are both one-time.

- workato-airo-mcp-server — the DEV AIRO: recipe_builder_*, blueprint_*,
  genie_*, data_table_*. Everything you build in dev goes through here.
- workato-airo-mcp-prod — the PROD AIRO: reads are allowlisted, every write
  prompts. Needed for production reviews and the promotion pipeline.
- workato-dependency-tracker — blast radius, recipe logic, connection health.
- atlassian — Jira and Confluence: the story-points gate, promotion stories,
  triage filing. OAuth through your Atlassian account.

brain is a fifth server the installer registers itself (claude mcp add brain
--scope user, read-only) — no action needed.

Register with your workspace's MCP URLs (from your Workato admin or whoever
shared this kit), then authenticate inside Claude Code:

    claude mcp add --transport http <name> <url> --scope user
    claude mcp add --transport sse atlassian https://mcp.atlassian.com/v1/sse --scope user

then in Claude Code: /mcp, select each server, authenticate.
EOT
if probe_mcp; then
  echo "  probe: all four connected."
  mark mcp done
else
  echo "  finish the registrations and the /mcp OAuth for each server above."
  settle mcp probe_mcp
fi

# -- step 3: settings.json ------------------------------------------------------------
echo
echo "== step 3 of 8: settings.json — the permission gate =="
cat <<'EOT'
The two mods bring their own hooks; what ~/.claude/settings.json must carry is
the permissions layer around production. The prod-write confirm gate (hook 13)
already holds Bash-level prod writes, and the MCP-side ask rule holds the prod
AIRO write tools at the permission layer. The kit reads KIT_HOME (defaults to
HOME) at install time; nothing else is env-configured at runtime.

If the probe below fails, merge this into ~/.claude/settings.json (print only,
never overwritten by this script):

    {
      "permissions": {
        "ask": [
          "mcp__workato-airo-mcp-prod"
        ]
      }
    }

That single rule asks before every prod AIRO tool call; reads stay readable by
adding allow rules for the specific read tools if you want less friction.
EOT
if probe_settings; then
  mark settings done
else
  echo "  apply the snippet above by hand (keep your existing keys)."
  settle settings probe_settings
fi

# -- step 4: keychain tokens ------------------------------------------------------------
echo
echo "== step 4 of 8: keychain tokens (wt dev, wt-prod) =="
cat <<'EOT'
wt and wt-prod read the Workato API token from the macOS keychain
(service workato-platform-cli, account = your CLI profile name) on every
invocation, so no token ever sits in a shell profile or file. The real test
is a live call: wt api GET /api/users/me must return the workspace id that
config.sh holds for that environment.
EOT
if probe_keychain; then
  mark keychain done
else
  echo "  store a missing token by pasting it below (input hidden, never echoed;"
  echo "  get one from Workato > Workspace admin > API clients > generate token):"
  if [ -z "$WORKSPACE_DEV" ] && [ -z "$WORKSPACE_PROD" ]; then
    echo "  (no workspace ids in config.sh — run ./onboard.sh first)"
  fi
  if [ -n "$WORKSPACE_DEV" ]; then
    printf "\n  dev token for account %s (paste, return to skip): " "$PROFILE_DEV"
    TOK=""; read -rs TOK || TOK=""
    if [ -n "$TOK" ]; then
      security add-generic-password -s workato-platform-cli -a "$PROFILE_DEV" -w "$TOK" -U \
        && echo "  ✓ stored in keychain (account: $PROFILE_DEV)"
      unset TOK
    else
      echo "  (skipped — the exact command, run it yourself:)"
      echo "    security add-generic-password -s workato-platform-cli -a $PROFILE_DEV -w <token> -U"
    fi
  fi
  if [ -n "$WORKSPACE_PROD" ]; then
    printf "\n  prod token for account %s (paste, return to skip): " "$PROFILE_PROD"
    TOK=""; read -rs TOK || TOK=""
    if [ -n "$TOK" ]; then
      security add-generic-password -s workato-platform-cli -a "$PROFILE_PROD" -w "$TOK" -U \
        && echo "  ✓ stored in keychain (account: $PROFILE_PROD)"
      unset TOK
    else
      echo "  (skipped — the exact command, run it yourself:)"
      echo "    security add-generic-password -s workato-platform-cli -a $PROFILE_PROD -w <token> -U"
    fi
  fi
  echo
  echo "  re-probing with a live API call ..."
  settle keychain probe_keychain
fi

# -- step 5: plugins loaded ---------------------------------------------------------------
echo
echo "== step 5 of 8: mods loaded (guardrails + brain-guard) =="
cat <<'EOT'
The two plugins must be installed AND loaded. install.sh registers them; a
fresh install needs /reload-plugins (or a Claude Code restart) before the
hooks fire. Smoke test in Claude Code, in this order:

    /guardrails   lists the loaded hooks — expect 13 in workato-guardrails
                  plus 5 in brain-guard. Fewer than 13 means the mod did not
                  load: restart, then claude plugin validate ~/mods/workato-guardrails
    /builds       the build ledger summary; a fresh install starts empty
    /cockpit      the session + ledger pane

The probe below only checks installation; the hook count is what /guardrails
shows inside a session.
EOT
if probe_plugins; then
  echo "  if this is a fresh install, still run /reload-plugins then /guardrails once."
  if ask "Ran /reload-plugins and /guardrails, hook counts look right?" n; then
    mark plugins done
  elif ask "Skip for now? (EOF/left = stays todo)" n; then mark plugins skipped; else mark plugins todo; fi
else
  echo "  missing mods. Install then reload:"
  echo "    claude plugin install workato-guardrails@josh-mods"
  echo "    claude plugin install brain-guard@josh-mods"
  echo "  then in Claude Code: /reload-plugins, and /guardrails to see the hooks."
  settle plugins probe_plugins
fi

# -- step 6: schedules ----------------------------------------------------------------------
echo
echo "== step 6 of 8: schedules — the nightly order is load-bearing =="
cat <<'EOT'
The agents run on schedules you create (they are per-project tasks, not files
this script can write). Two surfaces: ./install-launchd.sh installs the
script-only launchd jobs (docs crawler 22:15 runs with no session open), and
the agent jobs are Claude Code cron tasks created from your default work
project, pasting each prompt template from schedules/README.md.

The nightly order matters because the agents talk over the gossip bus:

    22:15  docs-watch (launchd)     first poster: platform doc deltas
    22:31  docs-watch summary       in-session
    22:43  brain gardener           curates knowledge, posts findings
    23:13  workato watchdog         connection health, stalls, autopsies
    23:33  harness backup           git snapshot, secrets redacted
    23:43  harness dreamer          reader-in-chief: merges the whole night
    07:13  morning brief            one digest for you

Each agent reads what the earlier ones posted; the dreamer runs last so the
dream synthesizes the night. Creating them out of order does not break
anything, but a docs-watch that fires after the dreamer starves the dream.
EOT
if probe_schedules; then
  mark schedules done
else
  echo "  full instructions and the exact prompts: $KIT_DIR/schedules/README.md"
  offer_run "open \"$KIT_DIR/schedules/README.md\""
  settle schedules probe_schedules
fi

# -- step 7: trust ladder ----------------------------------------------------------------------
echo
echo "== step 7 of 8: the dreamer trust ladder =="
cat <<'EOT'
The nightly dreamer writes reports and proposes harness changes under a
ladder enforced by ~/.claude/knowledge/dreams/config.json. One rung at a
time, and only when the previous rung earned trust:

    report      write the dream report, zero writes outside dreams/
    propose     + file proposals you review (nothing applies)
    auto-safe   + auto-apply only knowledge deltas, INDEX lines, claim stamps
    auto-dev    + bounded dev fixes overnight, cap 3, snapshot-verify-ledger,
                  any failure reverts and downgrades to a proposal

never_auto is constitutional in every mode: skills, hooks, mods, agents,
settings, crons, MCP config, and commands are proposal-only forever.

Recommended ramp: run report for a week, read the dream reports with your
coffee, then upgrade. Upgrade and downgrade are one command:

    python3 ~/.claude/knowledge/scripts/dream-config.py show
    python3 ~/.claude/knowledge/scripts/dream-config.py set-mode propose
EOT
if probe_ladder; then
  if ask "Set the mode now (the command above; default leaves it as is)?" n; then
    offer_run "python3 ~/.claude/knowledge/scripts/dream-config.py show"
  fi
  mark ladder done
else
  echo "  no config found. Restore the default (mode report):"
  offer_run "cp \"$KIT_DIR/knowledge/dreams/config.example.json\" \"${HOME}/.claude/knowledge/dreams/config.json\""
  settle ladder probe_ladder
fi

# -- step 8: first real session -----------------------------------------------------------------
echo
echo "== step 8 of 8: your first real session =="
cat <<'EOT'
What a good first task looks like: a small, real, dev-workspace change — fix a
failing recipe step, add a missing field mapping, write one test case for a
recipe that has none. Not a migration. Ask for it in plain language in a
Claude Code session in your work project; the playbook skills
(airo-mcp-playbook, workato-development-playbook) load automatically and the
guardrails hooks ledger and snapshot as you go.

The two standing surfaces, both interactive approval queues:
    /triage      open findings from the watchers, ranked by urgency: file a
                 story, build now, queue, reject, defer
    /proposals   pending dreamer proposals as decision cards

The morning brief (knowledge/morning-brief/<date>.md, 07:13) is the one daily
read once the schedules run: machine heartbeat first, bus patterns, dream
verdict, your Jira movements.

Last piece: the first harness-backup run. It snapshots skills, agents, the
knowledge tree, mods, and settings into a git repo with secrets redacted —
this is what makes agent changes reversible. config.sh needs BACKUP_REPO_LOCAL
(and BACKUP_REPO_URL if you want remote pushes) before it works.
EOT
if [ -n "${BACKUP_REPO_LOCAL:-}" ] && [ -d "${BACKUP_REPO_LOCAL}/.git" ]; then
  echo "  backup repo: ${BACKUP_REPO_LOCAL} (origin: ${BACKUP_REPO_URL:-local-only})"
  offer_run "bash \"${HOME}/.claude/knowledge/scripts/harness-backup.sh\""
  if ask "Smoke tests run (/guardrails, /builds) and first backup done?" n; then
    mark firsttask done
  elif ask "Skip for now? (EOF/left = stays todo)" n; then mark firsttask skipped; else mark firsttask todo; fi
else
  echo "  backup not configured yet: set BACKUP_REPO_LOCAL (+ BACKUP_REPO_URL) in"
  echo "  config.sh, re-run ./install.sh, then: bash ~/.claude/knowledge/scripts/harness-backup.sh"
  if ask "Everything else here understood (mark done, backup deferred)?" n; then
    mark firsttask done
  elif ask "Skip for now? (EOF/left = stays todo)" n; then mark firsttask skipped; else mark firsttask todo; fi
fi

# --- closing checklist -------------------------------------------------------------------------
echo
echo "== getting-started checklist =="
printf "  %-12s %s\n" "step" "status"
for s in verify mcp settings keychain plugins schedules ladder firsttask; do
  printf "  %-12s %s\n" "$s" "$(state_of "$s")"
done
echo
echo "state file: $STATE_FILE"
echo "re-run any time: ./getting-started.sh   (--status for the quiet view, --reset to start over)"
