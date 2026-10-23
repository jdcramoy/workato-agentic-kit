#!/usr/bin/env python3
"""build-start-register.py — PreToolUse hook: auto-register a claim row in
mission-control at build start.

Born 2026-10-22 (triage unregistered-session habit fix, Josh verdict "Fix
the habit"): the cortex kept filing "live session has no mission-control
row" (16 instances) because sessions start building without ever running
`mission-control.py add --event claim`. The claim is now automatic:

  * fires on the FIRST mutation this session makes to a knowledge file or a
    Workato-related surface (Write/Edit file_path, or a Bash command that
    touches ~/.claude/knowledge/ or drives Workato);
  * appends ONE claim row via mission-control.py add (event claim, state
    in-flight, by "josh (session)", session_id recorded), so the session is
    registered in the registry from its first real build action;
  * de-dup: a per-session state file plus an events.jsonl scan mean a
    session (or the same workstream slug) is never double-registered;
  * fail-open: every error path exits 0 with {} — a broken hook must never
    block a tool call.

Registered as a PreToolUse hook (matcher "Write|Edit|Bash") in
~/.claude/settings.json, pattern = manifest-guard / redteam-guard. Sessions
started BEFORE registration must restart to pick it up.

Env: MC_REGISTER_DRY_RUN=1 prints the would-be registration and writes
nothing (dry-run testing).
"""

import json
import os
import re
import sys
import time

HOME = os.path.expanduser("~")
STATE_PATH = os.path.join(HOME, ".claude", "knowledge", "mission-control",
                          "hook-claim-state.json")
EVENTS = os.path.join(HOME, ".claude", "knowledge", "mission-control",
                      "events.jsonl")
MC = os.path.join(HOME, ".claude", "knowledge", "scripts",
                  "mission-control.py")
STATE_TTL_S = 7 * 86400  # prune session state older than a week

TICKET_RE = re.compile(r"\b((?:BSYS|BTSUP|HROPS|PSM|MCP|AAI|CT)-\d+)\b",
                       re.IGNORECASE)
WORKATO_SIGNALS = ("workato", "wt ", "/recipes/", "app.workato.com",
                   "recipe_builder", "wt\t")


def emit():
    print("{}")


def slugify(text, sid):
    tickets = sorted({t.upper() for t in TICKET_RE.findall(text or "")})
    if tickets:
        return "-".join(tickets[:2]).lower()
    return f"session-{(sid or '')[:12]}"


def is_build_start_mutation(tool_name, tool_input):
    """True when THIS tool call mutates a knowledge file or a Workato
    surface. Cheap, string-level; no side effects."""
    if tool_name in ("Write", "Edit", "MultiEdit", "NotebookEdit"):
        fp = str((tool_input or {}).get("file_path", ""))
        return (HOME + "/.claude/knowledge/") in fp or \
            "workato" in fp.lower()
    if tool_name == "Bash":
        cmd = str((tool_input or {}).get("command", ""))
        low = cmd.lower()
        return (HOME + "/.claude/knowledge/") in cmd or \
            any(s in low for s in WORKATO_SIGNALS)
    return False


def load_state():
    try:
        with open(STATE_PATH) as fh:
            st = json.load(fh)
        if isinstance(st, dict):
            return st
    except Exception:
        pass
    return {}


def save_state(st):
    try:
        os.makedirs(os.path.dirname(STATE_PATH), exist_ok=True)
        tmp = STATE_PATH + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(st, fh)
        os.replace(tmp, STATE_PATH)
    except Exception:
        pass  # fail-open


def session_already_registered(sid):
    """Any prior claim/closeout row recorded for this session id — from
    this hook, a manual claim, or a closeout — means never register twice."""
    if not sid:
        return False
    try:
        with open(EVENTS, errors="replace") as fh:
            for line in fh:
                if '"session_id"' not in line:
                    continue
                try:
                    r = json.loads(line)
                except Exception:
                    continue
                if str(r.get("session_id", "")).startswith(sid[:12]) \
                        and r.get("event") in ("claim", "closeout",
                                               "absorb-note",
                                               "absorb-resolved"):
                    return True
    except FileNotFoundError:
        pass
    except Exception:
        return False  # unreadable ledger: fail open, dedup falls to state file
    return False


def main():
    try:
        data = json.load(sys.stdin)
    except Exception:
        emit()
        return
    try:
        sid = str(data.get("session_id", ""))
        tool_name = str(data.get("tool_name", ""))
        tool_input = data.get("tool_input") or {}
        if not sid or not tool_name:
            emit()
            return
        if not is_build_start_mutation(tool_name, tool_input):
            emit()
            return

        st = load_state()
        # prune dead sessions to keep the state file small
        now = time.time()
        st = {k: v for k, v in st.items()
              if isinstance(v, dict)
              and now - float(v.get("at", 0)) < STATE_TTL_S}
        me = st.get(sid)
        if me:
            emit()
            return  # this session already registered: de-dup by state file
        sample = json.dumps(tool_input, default=str)[:600]
        slug = slugify(sample, sid)
        if session_already_registered(sid):
            st[sid] = {"at": now, "workstream": slug,
                       "note": "already in events ledger"}
            save_state(st)
            emit()
            return

        what = (f"Auto-registered at build start: session {sid[:12]} began "
                f"mutating {tool_name} targets (first signal: "
                f"{sample[:200]}). Claim row written automatically by the "
                f"build-start hook so live work is never unregistered.")
        why = ("Josh verdict 'fix the habit' (2026-10-22): cortex filed 16 "
               "'live session has no mission-control row' findings; the "
               "claim now fires itself on first mutation.")
        cmd = ["python3", MC, "add", "--event", "claim",
               "--workstream", slug, "--project", "agent-harness",
               "--jira", "", "--jira-title", "", "--what", what,
               "--why", why, "--end", "", "--needs", "",
               "--state", "in-flight", "--by", "josh (session)",
               "--session-id", sid]
        if os.environ.get("MC_REGISTER_DRY_RUN") == "1":
            print(json.dumps({"dry_run": True, "would_run": cmd}))
            emit()
            return
        import subprocess
        r = subprocess.run(cmd, capture_output=True, timeout=25)
        if r.returncode in (0, 2):
            # 0 = row written; 2 = slug-conflict guard refused (Josh's guard
            # is respected, never force-bypassed) — either way the
            # workstream is already represented in the registry: de-dup
            # and move on.
            st[sid] = {"at": now, "workstream": slug,
                       "note": "claim row auto-registered (rc=%d)"
                               % r.returncode}
            save_state(st)
        # any other rc: state left unmarked so the next mutation retries
    except Exception:
        pass  # fail-open: a broken hook never blocks a tool call
    emit()


if __name__ == "__main__":
    main()
