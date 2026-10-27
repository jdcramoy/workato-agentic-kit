#!/usr/bin/env bash
# agentic-workato-kit installer
# Installs: 2 mods (workato-guardrails, brain-guard), the agent SOPs
# (11-agent fleet), the knowledge-tree scaffold + scripts (incl. the frontier
# stack: estate twin, integrity mesh, denominator oracle, calibration ledger,
# precursor radar, saga journals, standing orders, skill league, chaos
# canary, shadow estate), the frontier-nightly zero-LLM fleet job, and the
# weekly/nightly schedules.
#
# Prerequisites (checked below): Claude Code >= 2.1.287, git, python3, jq.
# You must ALSO connect these MCP servers in Claude Code before anything
# Workato-facing works: your AIRO MCP (dev + prod), the dependency tracker,
# and Atlassian. See README.md.
#
# Failure behavior: every run logs to ./install-logs/install-<timestamp>.log.
# A non-zero exit prints which step failed, what completed, what did not, and
# the log path. The installer is idempotent — fix the cause and re-run; file
# copies are safe to repeat and there is no automatic rollback (none needed).
set -euo pipefail

cd "$(dirname "$0")"

# --- logging: capture every step's output to a timestamped log ---------------
# Everything the installer prints (stdout + stderr) is tee'd to the log, so a
# failed run can be triaged after the fact. The path is echoed up front and
# again on any failure.
LOG_DIR="$(pwd)/install-logs"
mkdir -p "$LOG_DIR"
LOG="${LOG_DIR}/install-$(date +%Y%m%d-%H%M%S).log"
# tee in process substitution: output still lands on the user's terminal
exec > >(tee -a "$LOG" 2>&1)
echo "install log: $LOG"

# --- step tracking, degraded-items list, temp cleanup, failure trap ----------
# STEPS is the ordered install pipeline. CURRENT_STEP is the one in flight.
# COMPLETED accumulates finished steps; DEGRADED accumulates non-fatal
# failures (installed-but-partial) that get a fix-it summary at the end.
STEPS=(prereqs config agents knowledge+dreams mods+kb skills cli-tools)
CURRENT_STEP="startup"
COMPLETED=()
DEGRADED=()
TMPFILES=()

begin_step() { # begin_step <name> — move to the next pipeline step
  CURRENT_STEP="$1"
  echo
  echo "== step: $1 =="
}

finish_step() { # finish_step <name> — mark it completed
  COMPLETED+=("$1")
}

degraded() { # degraded <description including the exact fix command>
  echo "  DEGRADED: $1"
  DEGRADED+=("$1")
}

fail_step() { # fail_step <message> — fatal; the EXIT trap adds context
  echo "FAIL: $1"
  exit 1
}

cleanup_tmp() { # remove any temp files this run created (never returns nonzero:
               # a 1 here would trip set -e inside the EXIT trap)
  local t
  [ "${#TMPFILES[@]}" -gt 0 ] || return 0
  for t in "${TMPFILES[@]}"; do
    if [ -n "$t" ] && [ -e "$t" ]; then rm -f "$t"; fi
  done
  return 0
}

on_exit() { # single place that reports a failed run
  local rc=$?
  cleanup_tmp
  [ "$rc" -eq 0 ] && return
  local not_done="" seen=0 s
  for s in "${STEPS[@]}"; do
    [ "$s" = "$CURRENT_STEP" ] && seen=1
    [ "$seen" = 1 ] && not_done="$not_done $s"
  done
  echo
  echo "INSTALL FAILED (exit $rc) at step: $CURRENT_STEP"
  if [ "${#COMPLETED[@]}" -gt 0 ]; then
    echo "  completed before failure:${COMPLETED[*]/#/ }"
  else
    echo "  completed before failure: none"
  fi
  echo "  not completed:$not_done"
  echo "  file copies already made are idempotent — no rollback was attempted and"
  echo "  none is needed; re-running ./install.sh repeats or skips them safely."
  if [ "${#DEGRADED[@]}" -gt 0 ]; then
    echo "  degraded items from this run (fix these too):"
    local d
    for d in "${DEGRADED[@]}"; do echo "    - $d"; done
  fi
  echo "  Full output: $LOG"
  echo "  Resume: fix the cause above, then re-run ./install.sh (safe to re-run)."
}
trap on_exit EXIT
trap 'echo "install.sh: command failed at line $LINENO (step: $CURRENT_STEP)" >&2' ERR

# --- retries + error classification for network-shaped steps -----------------
classify_failure() { # classify_failure <desc> <rc> <output-file>
  local desc="$1" rc="$2" out="$3" hint
  if grep -qiE 'could not resolve host|connection (timed out|refused)|failed to connect|network|SSL|curl: \([0-9]+\)' "$out" 2>/dev/null; then
    hint="network — check your connection/proxy/VPN and try again"
  elif grep -qiE 'permission denied|EACCES' "$out" 2>/dev/null; then
    hint="permissions — check ownership of the target directory"
  elif grep -qiE 'authentication|401|403|invalid credentials' "$out" 2>/dev/null; then
    hint="auth — a token or credential is missing/rejected"
  elif grep -qiE 'command not found|not a git repository' "$out" 2>/dev/null; then
    hint="tool/version — a required command is missing or too old"
  else
    hint="unclassified — the full output above is in the log"
  fi
  echo "FAIL: $desc (exit $rc) — $hint"
}

with_retry() { # with_retry <desc> <attempts> <cmd...> — bounded retries with
               # short sleeps; classifies the failure after exhaustion
  local desc="$1" attempts="$2"; shift 2
  local i rc=0
  local out; out="$(mktemp -t kitretry)"; TMPFILES+=("$out")
  for i in $(seq 1 "$attempts"); do
    echo "  attempt $i/$attempts: $desc"
    if "$@" >"$out" 2>&1; then
      cat "$out"
      rm -f "$out"
      return 0
    else
      # capture INSIDE the else: after `fi`, $? is the if-statement's status (0)
      rc=$?
    fi
    cat "$out"
    if [ "$i" -lt "$attempts" ]; then
      echo "  retrying in 3s..."
      sleep 3
    fi
  done
  classify_failure "$desc" "$rc" "$out"
  rm -f "$out"
  return "$rc"
}

run_fixed() { eval "$1"; }  # lets with_retry wrap a command string

with_retry_stream() { # with_retry_stream <desc> <attempts> <cmd...> — same
                      # bounded retries, but output streams live (needed for
                      # interactive fixers like the Homebrew installer that
                      # prompt for a password; no capture, so no classify)
  local desc="$1" attempts="$2"; shift 2
  local i rc=0
  for i in $(seq 1 "$attempts"); do
    echo "  attempt $i/$attempts: $desc"
    if "$@"; then
      return 0
    else
      rc=$?
    fi
    if [ "$i" -lt "$attempts" ]; then
      echo "  retrying in 3s..."
      sleep 3
    fi
  done
  echo "FAIL: $desc (exit $rc) — see the output above; full log: $LOG"
  return "$rc"
}

echo "== agentic-workato-kit installer =="

# --- step: prereqs — check, offer to fix, re-verify --------------------------
# Interactive: offers the one-command fix and re-checks. Headless: fail-fast
# with the exact fix command printed (no prompting into a pipe). The fix
# command itself gets bounded retries so a flaky network does not kill the run.

INTERACTIVE="[ -t 0 ]"

fix_or_fail() {  # $1 what, $2 fix command
  if $INTERACTIVE; then
    printf "  %s is missing/outdated. Fix it now with: %s\n      [Y/n] " "$1" "$2"
    read -r reply
    if [[ ! "$reply" =~ ^[Nn] ]]; then
      echo "  running: $2"
      if ! with_retry_stream "fix: $1" 3 run_fixed "$2"; then
        fail_step "the fix command for '$1' failed after retries — run it yourself ('${2}') and re-run ./install.sh"
      fi
    else
      fail_step "$1 is required. Install it ('${2}'), then re-run ./install.sh"
    fi
  else
    echo "FAIL: $1 missing/outdated (headless mode — run this yourself, then re-run ./install.sh):"
    echo "  ${2}"
    exit 1
  fi
}

ensure() {  # $1 binary, $2 fix command
  command -v "$1" >/dev/null || fix_or_fail "$1" "$2"
  command -v "$1" >/dev/null || { echo "FAIL: $1 still not on PATH after the fix (PATH may need: export PATH=...); re-run ./install.sh"; exit 1; }
  echo "  ok: $1 ($($1 --version 2>/dev/null | head -1 | head -c 60))"
}

begin_step prereqs

# brew is the fix engine for everything below it
if ! command -v brew >/dev/null; then
  fix_or_fail "Homebrew" '/bin/bash -c "$(curl -fsSL https://raw.githubusercontent.com/Homebrew/install/HEAD/install.sh)"'
fi
ensure git "brew install git"
ensure jq "brew install jq"
if ! command -v python3.12 >/dev/null; then
  fix_or_fail "python3.12 (the KB venv needs it; torch has no 3.14 wheels)" "brew install python@3.12"
fi
ensure python3.12 "brew install python@3.12"
ensure claude "brew install --cask claude-code"

CC_VERSION=$(claude --version 2>/dev/null | grep -oE '[0-9]+\.[0-9]+\.[0-9]+' || echo "0")
echo "Claude Code: ${CC_VERSION}"
python3 -c "import sys; v=tuple(int(x) for x in '$CC_VERSION'.split('.')); sys.exit(0 if v >= (2,1,287) else 1)" \
  && echo "mod support: OK" || fix_or_fail "Claude Code >= 2.1.287 (mods need it)" "claude update"

finish_step prereqs

# --- step: config ------------------------------------------------------------
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
# KIT_HOME guard: a hand-written config.sh may have dropped the default
: "${KIT_HOME:=${HOME}}"
# placeholder guard: empty workspace IDs produce agents that point at nothing
if [ -z "${WORKSPACE_DEV:-}" ]; then
  echo "WARNING: WORKSPACE_DEV is empty — agents will reference blank workspace IDs."
  echo "         Run ./onboard.sh to fix, then re-run ./install.sh"
fi
# PROJECT_PATH must EXIST, not just be set: verify.sh cd's into it (the MCP +
# cron checks), and the tagged crons live under <PROJECT_PATH>/.claude.
# Onboarding defaults it to ~/Documents/workbench, which a fresh machine does
# not have — create it now rather than let verify.sh spam cd errors later.
: "${PROJECT_PATH:=${KIT_HOME}/Documents/workbench}"
if [ ! -d "$PROJECT_PATH" ]; then
  if mkdir -p "$PROJECT_PATH" 2>/dev/null; then
    echo "created project dir: $PROJECT_PATH (crons + verify.sh checks live here)"
  else
    degraded "PROJECT_PATH '$PROJECT_PATH' missing and could not be created — set PROJECT_PATH in config.sh to an existing directory, then re-run ./install.sh"
  fi
fi

finish_step config

render() {
  # render <src> <dest>: token substitution via python (config values may
  # contain |, /, [] — sed delimiters are not safe here).
  # FATAL on failure: a silently missing or truncated render corrupts the
  # install, so a bad template, missing file, or unwritable dest stops the run.
  local src="$1" dest="$2"
  if ! python3 - "$src" "$dest" << 'PYEOF'
import sys, os
src, dest = sys.argv[1], sys.argv[2]
text = open(src).read()
repl = {
    '{{HOME}}': os.environ.get('KIT_HOME', os.environ['HOME']),
    '{{WORKSPACE_DEV}}': os.environ.get('WORKSPACE_DEV', ''),
    '{{WORKSPACE_PROD}}': os.environ.get('WORKSPACE_PROD', ''),
    '{{ENV_DEV_NAME}}': os.environ.get('ENV_DEV_NAME', ''),
    '{{ENV_PROD_NAME}}': os.environ.get('ENV_PROD_NAME', ''),
    '{{PROFILE_DEV}}': os.environ.get('PROFILE_DEV', 'dev'),
    '{{PROFILE_PROD}}': os.environ.get('PROFILE_PROD', 'prod'),
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
  then
    fail_step "render failed: template '${src}' -> destination '${dest}'. A bad template, a missing file, or an unwritable destination corrupts the install — fix the cause (the python error is above) and re-run ./install.sh"
  fi
}

# --- step: agents ------------------------------------------------------------
begin_step agents
mkdir -p "${KIT_HOME}/.claude/agents"
for a in agents/*.md; do
  [ -f "$a" ] || continue  # no-match glob under set -u must not render a literal path
  render "$a" "${KIT_HOME}/.claude/agents/$(basename "$a")"
  echo "agent installed: $(basename "$a" .md)"
done
finish_step agents

# --- step: knowledge + dreams -------------------------------------------------
begin_step knowledge+dreams
K="${KIT_HOME}/.claude/knowledge"
mkdir -p "${K}/domains" "${K}/projects" "${K}/scripts" "${K}/claims" \
         "${K}/garden-reports" "${K}/architecture" "${K}/replay-fixtures" \
         "${K}/integrity" "${K}/predictions" "${K}/coverage" "${K}/sagas" \
         "${K}/policies" "${K}/skills-telemetry" "${K}/twin" "${K}/chaos" \
         "${K}/now" "${K}/instruction-patches" "${K}/scripts/frontier"
for f in knowledge/scripts/*; do
  [ -f "$f" ] || continue  # skip dirs (e.g. __pycache__) and no-match literals
  render "$f" "${K}/scripts/$(basename "$f")"
done
# frontier contracts ride along as data (not rendered — no tokens inside)
if [ -f knowledge/scripts/frontier/CONTRACTS.md ]; then
  cp knowledge/scripts/frontier/CONTRACTS.md "${K}/scripts/frontier/CONTRACTS.md"
fi
if ! chmod +x "${K}/scripts/"*.py 2>/dev/null; then
  degraded "knowledge scripts not marked executable (permissions?) — fix: chmod +x ${K}/scripts/*.py"
fi
# --- user model (preference store + context compiler) --------------------------
# install.sh renders the generic engine as user-model.py; with a USER_NAME from
# onboarding it also installs the personal copy <name>-model.py (store dir
# follows the name), writes user-model.conf so the generic entrypoint serves
# the personal store, and seeds the store with the get-to-know-you answers.
UM_SCRIPT="${K}/scripts/user-model.py"
if [ -f "$UM_SCRIPT" ]; then
  UM_NAME="${USER_NAME:-}"
  if [ -n "$UM_NAME" ]; then
    cp "$UM_SCRIPT" "${K}/scripts/${UM_NAME}-model.py"
    chmod +x "${K}/scripts/${UM_NAME}-model.py"
    printf '%s\n' "$UM_NAME" > "${K}/user-model.conf"
    UM_SEEDS=0
    for i in 1 2 3; do
      eval "UM_SEED=\${USER_MODEL_SEED_${i}:-}"
      [ -z "$UM_SEED" ] && continue
      if /usr/bin/python3 "$UM_SCRIPT" add --statement "$UM_SEED" --scope global \
           --tags onboarding >/dev/null 2>&1; then
        UM_SEEDS=$((UM_SEEDS + 1))
      else
        degraded "user-model seed rule ${i} failed to store — add it by hand: python3 ${UM_SCRIPT} add --statement '...' --scope global"
      fi
    done
    echo "user model installed: ${UM_NAME}-model.py (store: ${K}/${UM_NAME}-model, ${UM_SEEDS} seed rule(s))"
  else
    echo "user model installed: user-model.py (unnamed — run ./onboard.sh to name it and seed your rules)"
  fi
else
  degraded "user-model.py missing from knowledge/scripts — the session briefing hook will silently do nothing"
fi
touch "${K}/claims/claims.jsonl"
touch "${K}/integrity/claims.jsonl" "${K}/predictions/predictions.jsonl" \
      "${K}/coverage/ledger.jsonl"
[ -f "${K}/INDEX.md" ] || render "knowledge/INDEX.template.md" "${K}/INDEX.md"

# dreams scaffold (dreamer + gossip bus)
D="${K}/dreams"
mkdir -p "${D}/bus" "${D}/proposals" "${D}/data" "${D}/visions"
mkdir -p "${KIT_HOME}/.claude/knowledge/cortex" "${KIT_HOME}/.claude/knowledge/regression-canon"
touch "${KIT_HOME}/.claude/knowledge/cortex/questions.jsonl" "${KIT_HOME}/.claude/knowledge/regression-canon/canon.jsonl"
for a in docs-watch brain-gardener workato-watchdog harness-dreamer estate-architect promotion-orchestrator cortex evidence librarian; do
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
finish_step knowledge+dreams

# --- step: mods + kb ----------------------------------------------------------
begin_step mods+kb
mkdir -p "${KIT_HOME}/mods"
# "mods/*" does not match dotfiles (e.g. mods/.claude-plugin, which holds
# marketplace.json), so the marketplace registration below would silently
# find nothing. "mods/." copies the directory's full contents, hidden or not.
if ! cp -R mods/. "${KIT_HOME}/mods/"; then
  fail_step "mod source copy failed: mods/ -> ${KIT_HOME}/mods/ (check the cp error above and directory permissions)"
fi

# Workato KB (RAG++ pipeline): the shareable KB ships as its OWN pack now
# (Workato-All/workato-dev-kb: curated content + sanitized pipeline + its own
# hardened installer). This kit no longer clones the pipeline repo for fresh
# installs — workato-kb.git is the author's private upstream (estate-entangled
# code) and was never the consumer path. Existing KB homes keep getting pulls;
# zip distributions still carry their bundled snapshot.
KB_HOME="${KIT_HOME}/Documents/workato-kb"
if [ -d "$KB_HOME/.git" ]; then
  echo "kb: exists — pulling latest"
  if ! with_retry "kb pull (git -C $KB_HOME pull --ff-only)" 3 git -C "$KB_HOME" pull --ff-only; then
    degraded "kb pull failed — the KB may be stale. Fix: git -C $KB_HOME stash && git -C $KB_HOME pull --ff-only (or investigate local changes)"
  fi
elif [ -d "$KIT_HOME/Documents/workato-dev-kb" ]; then
  echo "kb: dev-kb pack found — it manages the pipeline and its content"
  echo "     (update it with: git -C $KIT_HOME/Documents/workato-dev-kb pull && ./install.sh)"
elif [ -d kb-pipeline/kb ]; then
  echo "kb: using the snapshot bundled in this zip (kb-pipeline/kb)"
  mkdir -p "${KIT_HOME}/Documents"
  if ! cp -R kb-pipeline/kb "$KB_HOME"; then
    degraded "kb snapshot copy failed — manual fix: cp -R kb-pipeline/kb $KB_HOME"
  else
    echo "kb: note — snapshot may lag the live repo; update later with: git -C $KB_HOME pull (needs GitHub access)"
  fi
else
  echo "kb: not installed — the RAG++ KB ships as its own pack, separate from this kit."
  echo "     Install it (content + sanitized pipeline + hardened installer, ~10 min):"
  echo "       git clone git@github.com:Workato-All/workato-dev-kb.git ${KIT_HOME}/Documents/workato-dev-kb"
  echo "       cd ${KIT_HOME}/Documents/workato-dev-kb && ./install.sh"
  echo "     (This kit's mechanics work without it; the KB is the retrieval + playbook layer.)"
fi

# render hardcoded homes + per-install prod identity inside the hooks
for f in "${KIT_HOME}/mods/"*/hooks/register.js; do
  [ -e "$f" ] || continue
  sed -i '' -e "s|{{HOME}}|${KIT_HOME}|g" -e "s|{{WORKSPACE_PROD}}|${WORKSPACE_PROD:-}|g" -e "s|{{PROD_TOKEN_MARK}}|${WORKATO_PROD_TOKEN_MARK:-}|g" "$f" 2>/dev/null || \
  sed -i -e "s|{{HOME}}|${KIT_HOME}|g" -e "s|{{WORKSPACE_PROD}}|${WORKSPACE_PROD:-}|g" -e "s|{{PROD_TOKEN_MARK}}|${WORKATO_PROD_TOKEN_MARK:-}|g" "$f" || \
    degraded "hook sed failed for $f — '{{HOME}}'/'{{WORKSPACE_PROD}}' will be unresolved. Fix: re-run ./install.sh"
done
# Marketplace registration: `add` on an already-registered name repoints it at
# ${KIT_HOME}/mods and refreshes its plugin list. A STALE registration (added
# from an old kit copy or zip) is the #1 cause of "Plugin ... not found in
# marketplace" — and `marketplace update` does NOT repair it, because update
# re-validates whatever source the registration already points at. The
# remove + re-add below is the proven repair.
if [ "${KIT_SKIP_INSTALL:-0}" = "1" ]; then
  echo "mods: KIT_SKIP_INSTALL=1 — skipped claude plugin install"
else
  MOD_OUT="$(mktemp -t kitmod)"; TMPFILES+=("$MOD_OUT")
  if claude plugin marketplace add "${KIT_HOME}/mods" >"$MOD_OUT" 2>&1; then
    cat "$MOD_OUT"
  else
    cat "$MOD_OUT"
    degraded "plugin marketplace add failed — mods may not register. Fix: claude plugin marketplace remove agentic-kit && claude plugin marketplace add ${KIT_HOME}/mods"
  fi
  for m in workato-guardrails brain-guard; do
    MOD_OUT="$(mktemp -t kitmod)"; TMPFILES+=("$MOD_OUT")
    if claude plugin install "${m}@agentic-kit" >"$MOD_OUT" 2>&1; then
      echo "mod installed: ${m}"
    elif grep -q "not found in marketplace" "$MOD_OUT"; then
      # stale marketplace copy: force a full refresh and retry exactly once
      echo "  stale marketplace copy detected for ${m} — repairing (remove + re-add + retry)"
      claude plugin marketplace remove agentic-kit >/dev/null 2>&1 || true
      if claude plugin marketplace add "${KIT_HOME}/mods" >"$MOD_OUT" 2>&1 \
         && claude plugin install "${m}@agentic-kit" >"$MOD_OUT" 2>&1; then
        echo "mod installed after marketplace repair: ${m}"
      else
        cat "$MOD_OUT"
        degraded "mod ${m} still not installed after marketplace repair — fix: claude plugin marketplace remove agentic-kit && claude plugin marketplace add ${KIT_HOME}/mods && claude plugin install ${m}@agentic-kit, then /reload-plugins"
      fi
    else
      cat "$MOD_OUT"
      degraded "mod ${m} not installed (claude CLI error above) — fix: claude plugin install ${m}@agentic-kit, then /reload-plugins"
    fi
  done
  # read-back: "install succeeded" claims are verified against the CLI itself
  PL="$(claude plugin list 2>/dev/null || true)"
  for m in workato-guardrails brain-guard; do
    echo "$PL" | grep -q "${m}@agentic-kit" || \
      degraded "mod ${m} not present in 'claude plugin list' after install — run /reload-plugins (or re-run ./install.sh) and check again"
  done
fi
finish_step mods+kb

# --- step: skills (playbooks + conventions) ----------------------------------
begin_step skills
mkdir -p "${KIT_HOME}/.claude/skills"
# render skill files too (they reference home paths). Process substitution
# keeps the loop in the main shell so a render failure is loud and fatal.
[ -d skills ] || fail_step "skills/ directory missing from the kit checkout — the kit is incomplete; re-clone or re-unzip"
while IFS= read -r f; do
  [ -n "$f" ] || continue
  dest="${KIT_HOME}/.claude/skills/${f#skills/}"
  render "$f" "$dest"
done < <(find skills -type f \( -name "*.md" -o -name "*.yaml" \))
echo "skills installed: $(ls skills/ | wc -l | tr -d " ") skill SOPs (playbooks, governance, estate ops)"
finish_step skills

# --- step: cli tools (wt, prod wrappers, brain MCP) ---------------------------
begin_step cli-tools
mkdir -p "${KIT_HOME}/.local/bin"
cp bin/wt "${KIT_HOME}/.local/bin/wt"
chmod +x "${KIT_HOME}/.local/bin/wt"
for w in wt-prod workato-prod prod-bypass; do
  render "bin/$w" "${KIT_HOME}/.local/bin/$w"
  chmod +x "${KIT_HOME}/.local/bin/$w"
done
echo "prod wrappers installed: wt-prod, workato-prod, prod-bypass (keychain account: ${PROFILE_PROD:-prod})"
case ":$PATH:" in
  *":${KIT_HOME}/.local/bin:"*) echo "wt installed: ${KIT_HOME}/.local/bin/wt (on PATH)" ;;
  *) echo "wt installed: ${KIT_HOME}/.local/bin/wt — add ~/.local/bin to your PATH" ;;
esac
echo "wt auth: set WORKATO_API_TOKEN or store a token via workato-platform-cli (keychain)."

# keychain token check + fix: a missing entry is the #1 cause of verify.sh's
# "dev identity ... got 'none'" FAIL. Offer the fix here, not only in verify.
# Read-only probe; the token is pasted once and stored straight to the
# keychain, never written to a file.
ensure_kc_token() { # ensure_kc_token <profile> <label>
  local profile="$1" label="$2" reply
  if security find-generic-password -s workato-platform-cli -a "$profile" >/dev/null 2>&1; then
    echo "wt token: keychain entry present (${label}, account: ${profile})"
  elif $INTERACTIVE; then
    printf "  No Workato API token in the keychain for account '%s'.\n  Paste the %s API token to store it now (return to skip): " "$profile" "$label"
    read -rs reply || reply=""
    if [ -n "$reply" ]; then
      if security add-generic-password -s workato-platform-cli -a "$profile" -w "$reply" -U; then
        echo "  token stored in keychain (account: ${profile})"
      else
        degraded "keychain store failed for ${label} — fix: security add-generic-password -s workato-platform-cli -a ${profile} -w <token> -U"
      fi
      reply=""
    else
      degraded "no ${label} API token — identity checks fail until one is stored: security add-generic-password -s workato-platform-cli -a ${profile} -w <token> -U, then ./verify.sh"
    fi
  else
    degraded "no ${label} API token in keychain (headless — run this yourself): security add-generic-password -s workato-platform-cli -a ${profile} -w <token> -U, then ./verify.sh"
  fi
}
ensure_kc_token "${PROFILE_DEV:-dev}" "dev"
[ -n "${WORKSPACE_PROD:-}" ] && ensure_kc_token "${PROFILE_PROD:-prod}" "prod"

# backup repo: verify.sh warns when uninitialized — init it here when config
# points at a directory (the origin URL, if set, is wired up in the same step)
if [ -n "${BACKUP_REPO_LOCAL:-}" ] && [ ! -d "${BACKUP_REPO_LOCAL}/.git" ]; then
  if mkdir -p "$BACKUP_REPO_LOCAL" && git -C "$BACKUP_REPO_LOCAL" init -q; then
    if [ -n "${BACKUP_REPO_URL:-}" ]; then
      git -C "$BACKUP_REPO_LOCAL" remote add origin "$BACKUP_REPO_URL" 2>/dev/null || true
    fi
    echo "backup repo initialized: ${BACKUP_REPO_LOCAL} (run harness-backup once for the first commit)"
  else
    degraded "backup repo init failed at ${BACKUP_REPO_LOCAL} — fix: git init ${BACKUP_REPO_LOCAL}"
  fi
fi

# MCP registration check — NOT OAuth (the kit cannot authenticate for you).
# verify.sh reports "not connected" when a server is missing OR unauthenticated;
# here we catch only the never-registered case and hand over the exact command.
if [ "${KIT_SKIP_INSTALL:-0}" != "1" ]; then
  MCP_LIST="${MCP_LIST:-$(claude mcp list 2>/dev/null || true)}"
  for s in workato-airo-mcp-server workato-airo-mcp-prod workato-dependency-tracker; do
    if ! echo "$MCP_LIST" | grep -q "^${s}"; then
      degraded "mcp '${s}' not registered — register YOUR workspace's MCP URL (from your Workato admin): claude mcp add --transport http ${s} <url> --scope user, then /mcp authenticate"
    fi
  done
  echo "$MCP_LIST" | grep -q "^atlassian" || \
    degraded "mcp 'atlassian' not registered — fix: claude mcp add --transport sse atlassian https://mcp.atlassian.com/v1/sse --scope user, then /mcp authenticate"
fi

# harness-backup (knowledge/scripts/harness-backup.sh): verify.sh and the
# README both expect this on PATH, but nothing previously copied it there.
cp knowledge/scripts/harness-backup.sh "${KIT_HOME}/.local/bin/harness-backup"
chmod +x "${KIT_HOME}/.local/bin/harness-backup"
echo "harness-backup installed: ${KIT_HOME}/.local/bin/harness-backup (set BACKUP_REPO_LOCAL/BACKUP_REPO_URL in config.sh, then run it once)"

# brain MCP server (read-only knowledge access for any agent)
cp bin/brain-mcp "${KIT_HOME}/.local/bin/brain-mcp"
chmod +x "${KIT_HOME}/.local/bin/brain-mcp"
if [ "${KIT_SKIP_INSTALL:-0}" != "1" ]; then
  # add is not idempotent (errors when the name exists) — check first, add only
  # when missing; one list read serves this and the registration check below
  MCP_LIST="$(claude mcp list 2>/dev/null || true)"
  if echo "$MCP_LIST" | grep -q "^brain"; then
    echo "mcp registered: brain (already present)"
  else
    MCP_OUT="$(mktemp -t kitmcp)"; TMPFILES+=("$MCP_OUT")
    if claude mcp add brain --scope user -- "${KIT_HOME}/.local/bin/brain-mcp" >"$MCP_OUT" 2>&1; then
      echo "mcp registered: brain (read-only)"
    else
      cat "$MCP_OUT"
      degraded "mcp brain not registered (claude CLI error above) — fix: claude mcp add brain --scope user -- ${KIT_HOME}/.local/bin/brain-mcp"
    fi
  fi
fi
# frontier-nightly fleet job (zero-LLM loop: twin -> calibration -> radar ->
# skill fitness) + its launchd plist. Installed on-schedule but never runs
# silently: the log under ~/.local/state/fleet/ is the evidence trail.
if [ -f bin/fleet/jobs/frontier-nightly.sh ]; then
  mkdir -p "${KIT_HOME}/.local/bin/fleet/jobs" "${KIT_HOME}/.local/state/fleet"
  render "bin/fleet/jobs/frontier-nightly.sh" "${KIT_HOME}/.local/bin/fleet/jobs/frontier-nightly.sh"
  chmod +x "${KIT_HOME}/.local/bin/fleet/jobs/frontier-nightly.sh"
  FLEET_LABEL="com.${USER_NAME:-user}.fleet.frontier-nightly"
  PLIST="${KIT_HOME}/Library/LaunchAgents/${FLEET_LABEL}.plist"
  mkdir -p "${KIT_HOME}/Library/LaunchAgents"
  cat > "$PLIST" << PLISTEOF
<?xml version="1.0" encoding="UTF-8"?><?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0"><dict>
  <key>Label</key><string>${FLEET_LABEL}</string>
  <key>ProgramArguments</key>
  <array>
    <string>/bin/bash</string>
    <string>${KIT_HOME}/.local/bin/fleet/jobs/frontier-nightly.sh</string>
  </array>
  <key>StartCalendarInterval</key><dict><key>Hour</key><integer>4</integer><key>Minute</key><integer>43</integer></dict>
  <key>StandardOutputPath</key><string>${KIT_HOME}/.local/state/fleet/frontier-nightly.launchd.log</string>
  <key>StandardErrorPath</key><string>${KIT_HOME}/.local/state/fleet/frontier-nightly.launchd.log</string>
</dict></plist>
PLISTEOF
  if [ "${KIT_SKIP_LAUNCHD:-0}" = "1" ]; then
    echo "fleet job: KIT_SKIP_LAUNCHD=1 — plist written but not loaded (no launchctl)"
  elif launchctl unload "$PLIST" 2>/dev/null && launchctl load "$PLIST" 2>/dev/null; then
    echo "fleet job installed: frontier-nightly (04:43, zero-LLM: twin -> calibration -> radar -> skill fitness)"
  else
    degraded "frontier-nightly plist not loaded — fix: launchctl load $PLIST"
  fi
fi
finish_step cli-tools

# --- step: done ---------------------------------------------------------------
if [ "${#DEGRADED[@]}" -gt 0 ]; then
  echo
  echo "== installed with ${#DEGRADED[@]} degraded item(s) — NOT everything is working =="
  echo "Fix each item (the exact command is in the list), then re-run ./install.sh"
  echo "to retry just what is missing. Full output: $LOG"
  for d in "${DEGRADED[@]}"; do echo "  - $d"; done
else
  echo
  echo "== installed clean. Log: $LOG =="
fi

cat << NEXT

== Installed. Next steps: ==
1. Run ./getting-started.sh — the guided walkthrough (connect MCP servers,
   /reload-plugins, fill config.sh if you skipped it, verify, smoke tests).
2. Prod CLI access: store the prod API token in the keychain
   (security add-generic-password -s workato-platform-cli -a ${PROFILE_PROD:-prod}
   -w <token> -U), then workato-prod / wt-prod target production; every prod
   write is held for confirmation by guardrails hook 13.
3. Schedules (docs-watch 22:31 + launchd 22:15, brain gardener 22:43, watchdog
   23:13, harness backup 23:33, harness dreamer 23:43, corpus Mon 06:07, estate
   architect Mon 06:37) are per-project cron tasks — create them from your
   default work project; the prompts live in schedules/. Nightly order matters:
   docs-watch feeds the gossip bus first, the dreamer runs last.
NEXT
