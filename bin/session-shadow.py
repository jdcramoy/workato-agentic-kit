#!/usr/bin/env python3
"""session-shadow — real-time cross-session visibility for Josh's harness.

Tails the ACTIVE Claude session transcript (~/.claude/projects/*/<uuid>.jsonl,
appended live every turn) and maintains knowledge/now/josh-now.{json,md} so
any parallel session/agent starts knowing what Josh is working on RIGHT NOW
without a handoff file. Mechanical only: zero LLM tokens. Context shifts
(new ticket, new focus files, gap-then-activity) post one gossip-bus line.

launchd: com.josh.session-shadow, StartInterval 60. Read-only observer:
never posts to Slack, never acts.
"""
import json
import os
import re
import glob
import time
from datetime import datetime, timezone

PROJECTS_GLOB = os.path.expanduser('~/.claude/projects/*/*.jsonl')
NOW_DIR = os.path.expanduser('~/.claude/knowledge/now')
STATE_PATH = os.path.join(NOW_DIR, 'shadow-state.json')
BUS_OUT = os.path.expanduser('~/.claude/knowledge/dreams/bus/session-shadow.jsonl')
HEARTBEAT = os.path.expanduser('~/.claude/knowledge/garden-reports/heartbeat.jsonl')
STALE_SESSION_SECONDS = 600      # newest file must have been touched in 10 min
GAP_SHIFT_SECONDS = 1800         # activity after a 30-min gap = a shift
TICKET_RE = re.compile(r'\b((?:BSYS|BTSUP|HROPS|PSM|MCP|AAI|CT)-\d+)\b')
JOB_RE = re.compile(r'\bj-[A-Za-z0-9]{6,}(-[A-Za-z0-9]{4,})?-CD\b|\bj-[A-Za-z0-9-]{8,}\b')


def now_iso():
    return datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')


def load_state():
    if os.path.exists(STATE_PATH):
        try:
            return json.load(open(STATE_PATH))
        except json.JSONDecodeError:
            pass
    return {'offsets': {}, 'topic_sig': None, 'last_ts': 0}


def save_state(s):
    json.dump(s, open(STATE_PATH, 'w'), indent=1)


def active_sessions():
    """Session files touched recently, newest first, with mtime."""
    out = []
    for f in glob.glob(PROJECTS_GLOB):
        base = os.path.basename(f)
        # only real session transcripts: <uuid>.jsonl
        if not re.match(r'^[0-9a-f-]{36}\.jsonl$', base):
            continue
        try:
            mt = os.path.getmtime(f)
        except OSError:
            continue
        if time.time() - mt <= STALE_SESSION_SECONDS:
            out.append((mt, f))
    out.sort(reverse=True)
    return out


def text_of_content(content):
    """Extract text + tool signals from a transcript message content field."""
    text, tools, files = [], [], []
    if isinstance(content, str):
        text.append(content)
        return text, tools, files
    if isinstance(content, list):
        for c in content:
            if not isinstance(c, dict):
                continue
            if c.get('type') == 'text' and c.get('text'):
                text.append(c['text'])
            elif c.get('type') == 'tool_use':
                name = c.get('name', '')
                inp = c.get('input') or {}
                sig = name
                for k in ('file_path', 'url', 'query', 'issueIdOrKey'):
                    if inp.get(k):
                        sig += f" {str(inp[k])[:80]}"
                        if k == 'file_path':
                            files.append(str(inp[k]))
                if name == 'Bash' and inp.get('command'):
                    cmd = str(inp['command'])
                    sig += ' ' + cmd[:80]
                    for fp in re.findall(r'/Users/joshcramoy/[^\s"\';&|]+', cmd):
                        files.append(fp)
                tools.append(sig)
    return text, tools, files


def scan_new_lines(path, offset):
    """Read new bytes; return (new_offset, user_texts, tool_sigs, files,
    last_event_ts)."""
    size = os.path.getsize(path)
    if size <= offset:
        return offset, [], [], [], None
    new_user, new_tools, files, last_ts = [], [], [], None
    with open(path, 'r', errors='replace') as f:
        f.seek(offset)
        raw = f.read()
    new_offset = offset + len(raw.encode('utf-8', errors='replace'))
    for line in raw.splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            ev = json.loads(line)
        except json.JSONDecodeError:
            continue
        if ev.get('isSidechain'):
            continue  # subagent noise; the shadow watches the MAIN thread
        ts = ev.get('timestamp')
        if ts:
            last_ts = ts
        etype = ev.get('type')
        msg = ev.get('message') or {}
        content = msg.get('content') if isinstance(msg, dict) else None
        if etype == 'user':
            t, _, _ = text_of_content(content)
            # tool RESULTS also come back as type:user; keep only real text
            real = [x for x in t if not x.startswith('<system-reminder')]
            if real:
                new_user.append(' '.join(real)[:400])
        elif etype == 'assistant':
            _, tools, fs = text_of_content(content)
            new_tools.extend(tools)
            files.extend(fs)
    return new_offset, new_user, new_tools, files, last_ts


def topic_signature(user_texts, files):
    m = ' '.join(user_texts)
    tickets = sorted(set(TICKET_RE.findall(m)))
    focus_files = sorted(set(f for f in files if '/knowledge/' not in f))[:4]
    return tickets, focus_files


def write_now(session_id, last_user, tool_sigs, tickets, focus_files,
              last_activity_iso):
    os.makedirs(NOW_DIR, exist_ok=True)
    jobs = sorted(set(JOB_RE.findall(' '.join(tool_sigs) + ' ' + last_user)))[:5]
    jobs = [j[0] if isinstance(j, tuple) else j for j in jobs]
    payload = {
        'updated_at': now_iso(),
        'session_id': session_id,
        'last_activity': last_activity_iso,
        'last_user_message': last_user[:300],
        'tickets': tickets,
        'focus_files': focus_files,
        'recent_jobs': jobs,
        'recent_tools': [t[:120] for t in tool_sigs[-6:]],
    }
    json.dump(payload, open(os.path.join(NOW_DIR, 'josh-now.json'), 'w'),
              indent=1)
    md = ['# Josh now (auto-updated by session-shadow)', '',
          f"Updated: {payload['updated_at']} | session {session_id[:8]} | "
          f"last activity {last_activity_iso}", '']
    if last_user:
        md.append(f"Last said: \"{last_user[:280]}\"")
        md.append('')
    if tickets:
        md.append(f"Tickets in play: {', '.join(tickets)}")
    if focus_files:
        md.append('Files in play:')
        for f in focus_files:
            md.append(f"- {f}")
    if jobs:
        md.append(f"Job IDs seen: {', '.join(jobs)}")
    if tool_sigs:
        md.append('')
        md.append('Latest tool activity:')
        for t in tool_sigs[-3:]:
            md.append(f"- {t[:140]}")
    open(os.path.join(NOW_DIR, 'josh-now.md'), 'w').write('\n'.join(md) + '\n')
    return payload


def bus_post(kind, note, refs):
    os.makedirs(os.path.dirname(BUS_OUT), exist_ok=True)
    line = json.dumps({'ts': now_iso(), 'agent': 'session-shadow',
                       'kind': kind, 'note': note, 'refs': refs})
    open(BUS_OUT, 'a').write(line + '\n')


def heartbeat():
    os.makedirs(os.path.dirname(HEARTBEAT), exist_ok=True)
    open(HEARTBEAT, 'a').write(
        json.dumps({'ts': now_iso(), 'job': 'session-shadow'}) + '\n')


def main():
    os.makedirs(NOW_DIR, exist_ok=True)
    state = load_state()
    sessions = active_sessions()
    if not sessions:
        return  # nothing live; keep last known state
    mt, active = sessions[0]
    session_id = os.path.basename(active)[:-6]
    offset = state['offsets'].get(session_id, 0)
    new_offset, users, tools, files, last_ts = scan_new_lines(active, offset)

    if new_offset != offset:
        state['offsets'][session_id] = new_offset
        # prune offsets for old sessions (keep 3 newest)
        newest = {os.path.basename(f)[:-6] for _, f in sessions[:3]}
        state['offsets'] = {k: v for k, v in state['offsets'].items()
                            if k in newest}
    # full-file scan on first sight of an active session (bootstrap)
    if not users and offset == 0:
        return  # nothing new yet this poll
    last_user = users[-1] if users else state.get('last_user', '')
    all_tools = state.get('tool_buffer', []) + tools
    state['tool_buffer'] = all_tools[-18:]
    state['last_user'] = last_user if last_user else state.get('last_user', '')
    tickets, focus_files = topic_signature(
        [last_user] if last_user else [], files or state.get('last_files', []))
    if files:
        state['last_files'] = list(set(files + state.get('last_files', [])))[-8:]

    sig = '|'.join(tickets) + '#' + ','.join(focus_files[:2])
    prev_sig = state.get('topic_sig')
    prev_ts = state.get('last_ts', 0)
    try:
        this_ts = time.mktime(time.strptime(
            last_ts, '%Y-%m-%dT%H:%M:%S.%fZ')) if last_ts else time.time()
    except (ValueError, TypeError):
        this_ts = time.time()
    gap_shift = prev_ts and (this_ts - prev_ts) > GAP_SHIFT_SECONDS

    if sig != prev_sig or gap_shift:
        if prev_sig is not None:  # don't announce the shadow's own bootstrap
            bus_post('focus',
                     f"Josh's focus shifted: tickets {tickets or ['none']} — "
                     f"last said: {last_user[:140]}",
                     {'session': session_id, 'now': 'knowledge/now/josh-now.md'})
            heartbeat()
        state['topic_sig'] = sig

    state['last_ts'] = this_ts or prev_ts
    save_state(state)
    write_now(session_id, state.get('last_user', ''), state.get('tool_buffer', []),
              tickets, state.get('last_files', [])[:4],
              last_ts or datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'))


if __name__ == '__main__':
    main()
