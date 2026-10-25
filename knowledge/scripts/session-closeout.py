#!/usr/bin/env python3
"""session-closeout.py — auto-draft the mission-control closeout from the transcript.

The problem (Josh, 2026-10-23): 25 sessions in 48h ended without a mission-control
closeout — the ledger depends on every agent REMEMBERING to write one. The fix flips
the default: a SessionEnd hook extracts a DRAFT closeout from the session transcript,
and the human/agent corrects the draft instead of creating from nothing.

Modes:
  hook (default when stdin is not a TTY, or --hook)
      Reads the Claude Code SessionEnd hook JSON from stdin
      ({"session_id", "transcript_path", "cwd"}), parses the transcript JSONL, and
      writes knowledge/mission-control/drafts/<session_id>.json (status "pending",
      overwritten idempotently per session). SKIPS drafting (silent exit 0) when:
        - fewer than 3 real user turns, or
        - a draft with status adopted|discarded already exists (a consumed draft is
          never resurrected).
      HOOK LAW: ALWAYS exit 0, complete < 5s; any exception appends one line to
      drafts/_errors.log and exits 0. Never blocks session exit. No network, no LLM.

  CLI
      --transcript PATH [--session-id ID]   run the extraction manually against any
                                            transcript file (writes the draft too)
      --list                                list pending drafts (one line each)
      --adopt ID | --discard ID             set a draft's status (the ONLY mutations
                                            besides draft creation)

Extraction (heuristics are allowed to be crude — it is a DRAFT):
  duration_min      first -> last row timestamp
  turns             non-meta user rows (skips isMeta, <command-name>/<local-command>
                    rows, tool_result-only rows, and subagent isSidechain rows)
  files_touched     file_path/path/notebook_path from Write/Edit/NotebookEdit
                    tool_use, plus absolute paths under /Users/YOUR-USER pulled
                    from Bash commands; deduped, cap 20
  jira_keys         \\b[A-Z]{2,6}-\\d+\\b over user+assistant text, deduped
  workato_assets    recipes/<digits> -> recipe:<digits> (same for genies,
                    data_tables, lookup_tables), deduped
  first_ask         first real user message, trimmed to 300 chars
  last_assistant_text last assistant text item, trimmed to 300 chars
  suggested         {what: from first_ask, why: "", end: from last_assistant_text,
                     state: "done" if the session's last user message looks
                     terminal else "in-flight"}

Zero-LLM, stdlib only. --help. Exit 0 success, 1 on CLI validation error.
"""
import argparse
import datetime as dt
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
MC = os.path.join(HOME, ".claude", "knowledge", "mission-control")
DRAFTS = os.path.join(MC, "drafts")
ERRLOG = os.path.join(DRAFTS, "_errors.log")

TRIM = 300
MIN_TURNS = 3
FILE_CAP = 20
EDIT_TOOLS = {"Write", "Edit", "NotebookEdit"}
JIRA_RE = re.compile(r"\b[A-Z]{2,6}-\d+\b")
ASSET_RES = [
    ("recipe", re.compile(r"\brecipes/(\d+)\b")),
    ("genie", re.compile(r"\bgenies/(\d+)\b")),
    ("data_table", re.compile(r"\bdata_tables/(\d+)\b")),
    ("lookup_table", re.compile(r"\blookup_tables/(\d+)\b")),
]
# absolute paths under Josh's home, pulled out of Bash command strings
HOME_PATH_RE = re.compile(r"/Users/YOUR-USER[^\s\"'`);&|,]*")
# terminal-sounding last user message -> suggested state "done" (crude on purpose)
TERMINAL_RE = re.compile(
    r"^(thanks|thank you|thx|ty|done|perfect|great|good|nice|awesome|excellent|"
    r"lgtm|lgdm|ship it|looks good|that'?s all|that'?s it|all set|we'?re good|"
    r"close( it| this)?( out)?|works? for me|solid|amazing|fantastic|cheers|"
    r"yes(,)? (ship|close|merge|done)|\+1)[\s.!]*$", re.IGNORECASE)
MSG_TYPES_RE = re.compile(r'<(command-name|local-command-stdout|local-command-warning)>')


def trim(s, n=TRIM):
    s = re.sub(r"\s+", " ", (s or "").strip())
    return s[: n - 1] + "…" if len(s) > n else s


def user_text(content):
    """Human text from a user row's message.content, or '' if the row is not a
    real user turn (tool_result-only, command plumbing, meta)."""
    if isinstance(content, str):
        return "" if MSG_TYPES_RE.search(content) else content
    if not isinstance(content, list):
        return ""
    texts, results = [], 0
    for item in content:
        if not isinstance(item, dict):
            continue
        t = item.get("type")
        if t == "text":
            texts.append(item.get("text", ""))
        elif t == "tool_result":
            results += 1
    if results and not any(t.strip() for t in texts):
        return ""  # tool_result-only row: machinery, not a turn
    joined = " ".join(t for t in texts if t.strip())
    return "" if MSG_TYPES_RE.search(joined) else joined


def extract(transcript_path):
    """Walk the transcript JSONL once; return the draft fields dict or None if
    the transcript yields fewer than MIN_TURNS real user turns."""
    first_ts = last_ts = None
    turns = 0
    first_ask = ""
    last_user_text = ""
    last_assistant_text = ""
    files_touched = []
    jira_keys = []
    workato_assets = []
    seen_files, seen_jira, seen_assets = set(), set(), set()

    def collect_text(text):
        for k in JIRA_RE.findall(text):
            if k not in seen_jira:
                seen_jira.add(k)
                jira_keys.append(k)
        for label, rx in ASSET_RES:
            for aid in rx.findall(text):
                key = f"{label}:{aid}"
                if key not in seen_assets:
                    seen_assets.add(key)
                    workato_assets.append(key)

    def add_file(p):
        p = (p or "").strip()
        if p and p not in seen_files and p.startswith("/"):
            seen_files.add(p)
            if len(files_touched) < FILE_CAP:
                files_touched.append(p)

    with open(transcript_path, errors="replace") as fh:
        for line in fh:
            if not line.strip():
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = row.get("timestamp")
            if ts:
                if first_ts is None:
                    first_ts = ts
                last_ts = ts
            rtype = row.get("type")
            if row.get("isMeta") or row.get("isSidechain"):
                continue
            msg = row.get("message") or {}
            content = msg.get("content")
            if rtype == "user":
                text = user_text(content)
                if not text:
                    continue
                turns += 1
                last_user_text = text
                if not first_ask:
                    first_ask = text
                collect_text(text)
            elif rtype == "assistant":
                if not isinstance(content, list):
                    continue
                for item in content:
                    if not isinstance(item, dict):
                        continue
                    it = item.get("type")
                    if it == "text":
                        text = item.get("text", "")
                        if text.strip():
                            last_assistant_text = text
                            collect_text(text)
                    elif it == "tool_use":
                        name = item.get("name", "")
                        inp = item.get("input") or {}
                        if name in EDIT_TOOLS:
                            add_file(inp.get("file_path") or inp.get("path")
                                     or inp.get("notebook_path"))
                        elif name == "Bash":
                            cmd = inp.get("command", "")
                            for p in HOME_PATH_RE.findall(cmd):
                                # drop trailing punctuation the regex may keep
                                add_file(p.rstrip(".,:;"))
                            collect_text(cmd)
    if turns < MIN_TURNS:
        return None
    duration_min = 0
    if first_ts and last_ts:
        try:
            delta = (dt.datetime.fromisoformat(last_ts.replace("Z", "+00:00"))
                     - dt.datetime.fromisoformat(first_ts.replace("Z", "+00:00")))
            duration_min = round(delta.total_seconds() / 60.0, 1)
        except ValueError:
            pass
    terminal = bool(last_user_text) and bool(TERMINAL_RE.match(last_user_text.strip()))
    return {
        "duration_min": duration_min,
        "turns": turns,
        "files_touched": files_touched,
        "jira_keys": jira_keys,
        "workato_assets": workato_assets,
        "first_ask": trim(first_ask),
        "last_assistant_text": trim(last_assistant_text),
        "suggested": {
            "what": trim(first_ask),
            "why": "",
            "end": trim(last_assistant_text),
            "state": "done" if terminal else "in-flight",
        },
        "ended_at": last_ts or "",
    }


def log_error(session_id, exc):
    """HOOK LAW: one line to _errors.log, never raise."""
    try:
        os.makedirs(DRAFTS, exist_ok=True)
        line = json.dumps({
            "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
            "session_id": session_id,
            "error": f"{type(exc).__name__}: {exc}",
        }, ensure_ascii=False)
        with open(ERRLOG, "a") as fh:
            fh.write(line + "\n")
    except Exception:
        pass


def load_atomic_io():
    try:
        sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
        from atomic_io import atomic_write
        return atomic_write
    except Exception:
        return lambda path, data: open(path, "w").write(data)


def write_draft(session_id, cwd, fields):
    """Write/overwrite the pending draft. A draft already consumed as
    adopted|discarded is NEVER resurrected (returns False, silent skip)."""
    path = os.path.join(DRAFTS, f"{session_id}.json")
    if os.path.exists(path):
        try:
            with open(path) as fh:
                prev = json.load(fh)
            if prev.get("status") in ("adopted", "discarded"):
                return False
        except Exception:
            pass  # unreadable draft: overwrite is the safe move
    draft = {
        "session_id": session_id,
        "ended_at": fields["ended_at"],
        "cwd": cwd or "",
        "duration_min": fields["duration_min"],
        "turns": fields["turns"],
        "files_touched": fields["files_touched"],
        "jira_keys": fields["jira_keys"],
        "workato_assets": fields["workato_assets"],
        "first_ask": fields["first_ask"],
        "last_assistant_text": fields["last_assistant_text"],
        "suggested": fields["suggested"],
        "status": "pending",
    }
    os.makedirs(DRAFTS, exist_ok=True)
    load_atomic_io()(path, json.dumps(draft, indent=1, ensure_ascii=False) + "\n")
    return path


def run_extraction(transcript_path, session_id=None, cwd="", quiet=False):
    """Shared extraction path for hook and CLI modes. Returns (path_or_None,
    skipped_reason)."""
    if not session_id:
        base = os.path.basename(transcript_path or "")
        session_id = os.path.splitext(base)[0] or "unknown-session"
    fields = extract(transcript_path)
    if fields is None:
        return None, "turns<%d" % MIN_TURNS
    path = write_draft(session_id, cwd, fields)
    if path is None:
        return None, "draft already adopted/discarded"
    return path, None


def hook_mode():
    """SessionEnd hook: read stdin JSON, draft, ALWAYS exit 0."""
    session_id = ""
    try:
        raw = sys.stdin.read() if not sys.stdin.isatty() else ""
        payload = json.loads(raw) if raw.strip() else {}
        session_id = payload.get("session_id", "")
        transcript_path = payload.get("transcript_path", "")
        cwd = payload.get("cwd", "")
        if transcript_path and os.path.exists(transcript_path):
            run_extraction(transcript_path, session_id, cwd, quiet=True)
        # missing transcript: nothing to extract, still a clean exit 0
    except Exception as exc:  # HOOK LAW: log one line, exit 0, never block exit
        log_error(session_id, exc)
    sys.exit(0)


def list_drafts():
    if not os.path.isdir(DRAFTS):
        return
    rows = []
    for name in os.listdir(DRAFTS):
        if not name.endswith(".json"):
            continue
        try:
            with open(os.path.join(DRAFTS, name)) as fh:
                d = json.load(fh)
        except Exception:
            continue
        if d.get("status") != "pending":
            continue
        rows.append(d)
    rows.sort(key=lambda d: d.get("ended_at", ""))
    if not rows:
        print("no pending draft closeouts")
        return
    print(f"{len(rows)} pending draft closeout(s):")
    for d in rows:
        when = (d.get("ended_at") or "")[:16].replace("T", " ")
        cwd = os.path.basename((d.get("cwd") or "").rstrip("/")) or "?"
        print(f"- {d.get('session_id','?')} | {when} | {cwd} | "
              f"{trim(d.get('first_ask',''), 90)}")


def set_status(draft_id, status):
    path = os.path.join(DRAFTS, f"{draft_id}.json")
    if not os.path.exists(path):
        print(f"no draft for session {draft_id}: {path}")
        return 1
    try:
        with open(path) as fh:
            d = json.load(fh)
    except Exception as exc:
        print(f"unreadable draft {path}: {exc}")
        return 1
    d["status"] = status
    load_atomic_io()(path, json.dumps(d, indent=1, ensure_ascii=False) + "\n")
    print(f"{draft_id} -> {status}")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Auto-draft mission-control closeouts from session transcripts "
                    "(SessionEnd hook + manual CLI).",
        epilog="Hook mode runs automatically when stdin is piped. "
               "Drafts land in ~/.claude/knowledge/mission-control/drafts/.")
    ap.add_argument("--hook", action="store_true",
                    help="force hook mode (read SessionEnd JSON from stdin)")
    ap.add_argument("--transcript", metavar="PATH",
                    help="CLI: extract from this transcript JSONL")
    ap.add_argument("--session-id", metavar="ID",
                    help="CLI: session id for the draft (default: transcript filename)")
    ap.add_argument("--cwd", default="", help="CLI: cwd to stamp on the draft")
    ap.add_argument("--list", action="store_true",
                    help="list pending draft closeouts")
    ap.add_argument("--adopt", metavar="ID",
                    help="mark draft ID adopted (consumed)")
    ap.add_argument("--discard", metavar="ID",
                    help="mark draft ID discarded (consumed; never resurrected)")
    a = ap.parse_args()

    mutations = sum(1 for v in (a.transcript, a.list, a.adopt, a.discard) if v)
    if mutations > 1:
        ap.error("--transcript, --list, --adopt, --discard are mutually exclusive")
        return 1
    if a.hook:
        hook_mode()  # always exits
    if not sys.stdin.isatty() and mutations == 0:
        hook_mode()  # piped stdin with no CLI action = hook invocation
    if a.list:
        list_drafts()
        return 0
    if a.adopt:
        return set_status(a.adopt, "adopted")
    if a.discard:
        return set_status(a.discard, "discarded")
    if a.transcript:
        if not os.path.exists(a.transcript):
            print(f"transcript not found: {a.transcript}")
            return 1
        path, skipped = run_extraction(a.transcript, a.session_id, a.cwd)
        if path is None:
            print(f"skipped ({skipped})")
            return 0
        with open(path) as fh:
            print(fh.read().strip())
        return 0
    ap.print_help()
    return 0


if __name__ == "__main__":
    if len(sys.argv) == 1 and not sys.stdin.isatty():
        hook_mode()
    try:
        sys.exit(main())
    except BrokenPipeError:
        os._exit(0)
