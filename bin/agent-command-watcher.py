#!/usr/bin/env python3
"""agent-command-watcher — executes Slack directives queued by the
agent_command_queue data table (uuid 88affdf3-e432-4449-9d14-bbafbcd9c7db,
dev ws 3535597, data-tables.workato.com REST).

Flow: Slack message by Josh in #josh-slack-triage -> Workato recipe writes a
queue row {directive, author_slack_id, status=pending} -> THIS watcher (every
60s via launchd) picks it up, verifies the author is Josh's Slack ID, executes
each directive via `claude -p`, marks the row done/rejected.

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
import json
import os
import subprocess
import sys
import urllib.request
import urllib.error
from datetime import datetime, timezone

TABLE = '88affdf3-e432-4449-9d14-bbafbcd9c7db'
BASE = 'https://data-tables.workato.com/api/v1/tables/' + TABLE
AUTHOR_ID = 'U0A3R9AVAMA'
STATE = os.path.expanduser('~/.claude/knowledge/garden-reports/command-watcher-state.json')


def api(method, path, data=None):
    token = subprocess.run(
        ['python3', '-c',
         'from importlib.machinery import SourceFileLoader;'
         'wt=SourceFileLoader("wtmod","{{HOME}}/.local/bin/wt").load_module();'
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


def main():
    dry = '--dry-run' in sys.argv
    state = load_state()
    status, resp = api('POST', '/query', {'where': {'status': {'$eq': 'pending'}}})
    if not isinstance(resp, dict) or not resp.get('data'):
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

        if directive.lower() == 'selfcheck':
            note = 'selfcheck ok at ' + datetime.now(timezone.utc).isoformat()
            update_row(rid, {'status': 'done', 'result_note': note})
            state['processed'].append(rid)
            save_state(state)
            print(note)
            continue

        # execute via headless claude; prod writes fail there naturally
        # (no permission prompt can be answered in -p mode)
        r = subprocess.run(['claude', '-p', f'Execute this directive from Josh '
                            f'(received via Slack, author verified): {directive}. '
                            f'Follow the jira-autotriage skill matrix.'],
                            capture_output=True, text=True, timeout=1800)
        note = (r.stdout or r.stderr or 'no output')[:300]
        status = 'done' if r.returncode == 0 else 'rejected'
        update_row(rid, {'status': status, 'result_note': note})
        state['processed'].append(rid)
        save_state(state)
        print(f'{status}: {directive} -> {note[:80]}')


if __name__ == '__main__':
    main()
