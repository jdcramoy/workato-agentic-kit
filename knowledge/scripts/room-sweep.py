#!/usr/bin/env python3
"""room-sweep.py — poll #josh-slack-triage via headless claude (MCP-backed),
queue unseen Josh directives as command-watcher rows.

Why: the Slack event subscription delivered 1 of 6 commands (2026-10-08) and
bot history needs groups:history (pending admin approval). A fleet job runs
headless claude WITH the slack-workato MCP connected, so IT can read the
room; this script turns its JSON output into queue rows via the watcher's
own api() (same token machinery, no duplication). The watcher (60s launchd)
does the executing + bot ack.

Usage: room-sweep.py            (called by the fleet room-sweep job)
       room-sweep.py '<json>'   (direct, for testing)
State: command-sweep-state.json (last seen message ts) — separate from the
watcher's state file so the two never race on one file.
"""
import json
import os
import subprocess
import sys

STATE = os.path.expanduser('~/.claude/knowledge/garden-reports/command-sweep-state.json')
WATCHER = os.path.expanduser('~/.local/bin/agent-command-watcher.py')
AUTHOR_ID = 'U0A3R9AVAMA'


def load_last():
    if os.path.exists(STATE):
        return json.load(open(STATE)).get('last_ts', 0)
    return 0


def save_last(ts):
    json.dump({'last_ts': ts}, open(STATE, 'w'))


def watcher_api(method, path, data):
    """Reuse the watcher's data-tables api() directly."""
    import importlib.util
    spec = importlib.util.spec_from_file_location('w', WATCHER)
    w = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(w)
    return w.api(method, path, data)


def is_directive(text):
    """Word-boundary grammar check: selfcheck | go|skip|plan|work <KEY>.
    Substring checks here would match 'elfcheck' inside 'selfcheck' (bug
    hit live 2026-10-08 — rejected 8 good rows)."""
    first = text.strip().lower().split(' ')[0].rstrip(':') if text.strip() else ''
    return first in ('selfcheck', 'go', 'skip', 'plan', 'work')


def sweep(raw_json):
    msgs = json.loads(raw_json)
    last = load_last()
    new = [m for m in msgs
           if str(m.get('user', '')) == AUTHOR_ID and float(m['ts']) > last]
    new.sort(key=lambda m: float(m['ts']))  # oldest first
    for m in new:
        directive = (m.get('text') or '').strip()
        last = max(last, float(m['ts']))  # advance past EVERY message, junk included
        if not is_directive(directive):
            print(f"skipped non-directive: {directive[:50]}")
            continue
        status, resp = watcher_api('POST', '/records', {'document': {
            'directive': directive, 'author_slack_id': AUTHOR_ID,
            'status': 'pending', 'source_ref': f"slack-sweep:{m['ts']}"}})
        # create returns HTTP 201 + {'data': {'created_at':..., 'document':[...]}}
        # — no record id in the response; status code is the success signal
        ok = (status == 201) and isinstance(resp, dict) and bool(resp.get('data'))
        print(f"queued: {directive[:40]} row={'ok' if ok else 'FAIL: ' + str(resp)[:80]}")
    if new:
        save_last(last)
    print(f"sweep done: {len(new)} seen, last_ts={last}")


if __name__ == '__main__':
    if len(sys.argv) > 1:
        sweep(sys.argv[1])
    else:
        # read the JSON from the headless claude sweep on stdin
        sweep(sys.stdin.read())
