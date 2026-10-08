#!/usr/bin/env python3
"""agent-command-watcher — executes Slack directives queued by the
agent_command_queue data table (uuid 88affdf3-e432-4449-9d14-bbafbcd9c7db,
dev ws 3535597, data-tables.workato.com REST).

Flow (primary, 2026-10-08): THIS watcher polls #josh-slack-triage directly
with the josh-triage-bridge bot token (event subscription delivered 1 of 6
commands — see knowledge/domains/workato-platform.md), writes each unseen
Josh directive as a queue row, executes it via `claude -p`, marks the row
done/rejected, and posts the ack AS THE BOT (the old loop completed
silently — Josh never saw the result).
Flow (legacy): Workato recipe writes queue rows -> same processing. The
bridge recipe runs with a trigger guard since 2026-10-08 (channel+author
filter drops non-matching events before job creation), so both paths are
live; the poll leg is the reliability backstop either way.

API notes (learned live 2026-10-08):
  - host: https://data-tables.workato.com (NOT www/app — those 404 /api/v1)
  - table id: the UUID, not the numeric id
  - create/update payload: {"document": {field_name: value}} (no colons)
  - query: POST .../query {"where": {...}}; row id lives in $record_id

Directive grammar: go|skip|plan|work <KEY>; 'selfcheck' is a no-op probe.
Rows with author_slack_id != U0A3R9AVAMA are rejected. claude runs headless
(-p), so prod-write directives fail there naturally (no prompt to answer).

Usage: agent-command-watcher.py [--once] [--dry-run]
launchd: com.josh.agent-command-watcher, StartInterval 60.
"""
import fcntl
import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
import urllib.parse
from datetime import datetime, timezone

TABLE = '88affdf3-e432-4449-9d14-bbafbcd9c7db'
BASE = 'https://data-tables.workato.com/api/v1/tables/' + TABLE
AUTHOR_ID = 'U0A3R9AVAMA'
STATE = os.path.expanduser('~/.claude/knowledge/garden-reports/command-watcher-state.json')
# absolute path: launchd PATH (~minmal) cannot resolve bare 'claude'
CLAUDE = shutil.which('claude') or os.path.expanduser('~/.local/bin/claude')
ROOM = 'C0C7JHJKHRU'  # josh-slack-triage (private) — poll for directives, ack as bot

# Slack legs (bot: josh-triage-bridge, dedicated app). Ingestion polls the
# room directly because the event-subscription path delivered 1 of 6 commands
# (2026-10-08); acks exist because completed rows were invisible to Josh.
def _bot_token():
    r = subprocess.run(['security', 'find-generic-password', '-s',
                        'slack-harness-command-bot', '-w'],
                       capture_output=True, text=True)
    return r.stdout.strip()


def slack(method, data=None, params=None):
    token = _bot_token()
    if not token:
        return None
    url = f'https://slack.com/api/{method}'
    qs = '&'.join(f'{k}={urllib.parse.quote(str(v))}' for k, v in (params or {}).items())
    if qs:
        url += '?' + qs
    req = urllib.request.Request(url, method='POST' if data else 'GET',
                                 headers={'Authorization': f'Bearer {token}',
                                          'Content-Type': 'application/json'},
                                 data=json.dumps(data).encode() if data else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return json.loads(resp.read())
    except (urllib.error.URLError, json.JSONDecodeError) as e:
        print(f'slack {method} failed: {e}')
        return None


def our_post_ts():
    """ts values of posts WE made as Josh (slack-workato VUA posts carry
    Josh's user id, so the author filter cannot see them) — from the
    follow-up ledger the Slack presence rule maintains."""
    path = os.path.expanduser('~/.claude/knowledge/slack-posts.jsonl')
    ours = set()
    if os.path.exists(path):
        for line in open(path):
            try:
                rec = json.loads(line)
                if rec.get('channel_id') == ROOM:
                    ours.add(str(rec.get('message_ts', '')))
            except json.JSONDecodeError:
                continue
    return ours


def poll_room(state):
    """Ingest Josh's directives straight from the room (oldest first).

    Returns directives not yet seen; each becomes a queue row (ledger) and is
    executed inline. Falls through silently when scopes/tokens aren't live."""
    r = slack('conversations.history', params={'channel': ROOM, 'limit': 20})
    if not r or not r.get('ok'):
        return []
    ours = our_post_ts()
    out = []
    for m in reversed(r.get('messages', [])):  # oldest first
        ts = m.get('ts', '')
        if m.get('user') != AUTHOR_ID or not ts:
            continue
        if m.get('subtype'):  # channel_join and other system notices
            continue
        if ts in ours:  # our own digest posts, indistinguishable by author
            continue
        if float(ts) <= state.get('last_ts', 0) or ts in state.get('seen_ts', []):
            continue
        out.append(m)
    return out


def ack(text):
    r = slack('chat.postMessage', data={'channel': ROOM, 'text': text})
    if not r or not r.get('ok'):
        print(f'ack failed: {r.get("error") if r else "no token"}')


def api(method, path, data=None):
    token = subprocess.run(
        ['python3', '-c',
         'from importlib.machinery import SourceFileLoader;'
         'wt=SourceFileLoader("wtmod","/Users/joshcramoy/.local/bin/wt").load_module();'
         'print(wt.client(type("A",(),{"profile":None})())[1].strip())'],
        capture_output=True, text=True).stdout.strip()
    req = urllib.request.Request(BASE + path, method=method, headers={
        'Authorization': f'Bearer {token}',
        'Content-Type': 'application/json',
        'User-Agent': 'agent-command-watcher/1.0',
        'Accept': 'application/json',
    }, data=json.dumps(data).encode() if data is not None else None)
    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            return resp.status, json.loads(resp.read() or b'{}')
    except urllib.error.HTTPError as e:
        return e.code, e.read().decode(errors='replace')[:200]


def load_state():
    if os.path.exists(STATE):
        return json.load(open(STATE))
    return {'processed': []}


def save_state(s):
    json.dump(s, open(STATE, 'w'), indent=1)


def update_row(record_id, fields):
    return api('PUT', f'/records/{record_id}', {'document': fields})


def execute(directive, dry):
    """Run one directive; returns (status, note)."""
    directive = (directive or '').strip()
    if directive.lower() == 'selfcheck':
        return 'done', 'selfcheck ok at ' + datetime.now(timezone.utc).isoformat()
    r = subprocess.run([CLAUDE, '-p', f'Execute this directive from Josh '
                        f'(received via Slack, author verified): {directive}. '
                        f'Follow the jira-autotriage skill matrix.'],
                        capture_output=True, text=True, timeout=1800)
    note = (r.stdout or r.stderr or 'no output')[:300]
    return ('done' if r.returncode == 0 else 'rejected'), note


def main():
    # single-flight: launchd ticks every 60s but a drain (claude -p per
    # directive) can run for many minutes — later ticks exit quietly
    lock_fd = open(os.path.expanduser(
        '~/.claude/knowledge/garden-reports/command-watcher.lock'), 'w')
    try:
        fcntl.flock(lock_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except OSError:
        print('another watcher holds the lock; exiting quietly')
        return 0
    dry = '--dry-run' in sys.argv
    state = load_state()
    status, resp = api('POST', '/query', {'where': {'status': {'$eq': 'pending'}}})
    if not isinstance(resp, dict) or not resp.get('data'):
        # no pending table rows — still poll the room before the quiet return
        msgs = poll_room(state)
        for m in msgs:
            directive = (m.get('text') or '').strip()
            state.setdefault('seen_ts', []).append(m['ts'])
            state['last_ts'] = max(state.get('last_ts', 0), float(m['ts']))
            try:
                if dry:
                    print(f'[dry] room directive: {directive}')
                    continue
                _, resp2 = api('POST', '/records', {'document': {
                    'directive': directive, 'author_slack_id': AUTHOR_ID,
                    'status': 'pending', 'source_ref': f"slack-poll:{m['ts']}"}})
                rid = (resp2.get('id') if isinstance(resp2, dict) else None) or \
                      (resp2.get('$record_id') if isinstance(resp2, dict) else None)
                st, note = execute(directive, dry)
                if rid:
                    update_row(rid, {'status': st, 'result_note': note})
                state['processed'].append(rid or f"ts-{m['ts']}")
                ack(note if directive.lower() == 'selfcheck'
                    else f'{st}: {directive} -> {note[:120]}')
                print(f'{st}: {directive} -> {note[:80]}')
            except Exception as e:
                # a poison row must be rejected, never crash-loop the tick
                note = f'execution failed: {e}'
                if rid:
                    try:
                        update_row(rid, {'status': 'rejected', 'result_note': note})
                    except Exception:
                        pass
                ack(f'rejected: {directive[:60]} -> {note[:80]}')
                print(note)
        if msgs:
            state['seen_ts'] = state.get('seen_ts', [])[-100:]  # prune
            save_state(state)
        return  # quiet tick

    # data rows are [system_triple, user_values_list]; decode each part
    # against its schema group (live-verified format)
    schema_groups = resp.get('schema', [])
    user_names = [c.get('name') or c.get('id')
                  for c in (schema_groups[1] if len(schema_groups) > 1 else [])]

    rows = []
    for v in resp['data']:
        sys_part = v[0] if isinstance(v[0], list) else [v[0]]
        user_vals = v[1] if isinstance(v[1], list) else v[1:]
        d = dict(zip(user_names, user_vals))
        d['$record_id'] = sys_part[0]
        rows.append(d)
    if not rows:
        return  # quiet tick

    for row in rows:
        rid = row.get('$record_id')
        if not rid or rid in state['processed']:
            continue
        directive = (row.get('directive') or '').strip()
        author = (row.get('author_slack_id') or '').strip()

        if author != AUTHOR_ID:
            note = f'rejected: author {author or "unknown"} is not the authority ({AUTHOR_ID})'
            update_row(rid, {'status': 'rejected', 'result_note': note})
            print(note)
            continue

        if dry:
            print(f'[dry] would execute: {directive}')
            continue

        status, note = execute(directive, dry)
        update_row(rid, {'status': status, 'result_note': note})
        state['processed'].append(rid)
        save_state(state)
        ack(note if directive.lower() == 'selfcheck'
            else f'{status}: {directive} -> {note[:120]}')
        print(f'{status}: {directive} -> {note[:80]}')


if __name__ == '__main__':
    main()
