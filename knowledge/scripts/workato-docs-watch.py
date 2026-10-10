#!/usr/bin/env python3
"""Workato docs/announcements crawler — the gardener's platform-change feed.

Fetches a list of Workato doc/changelog/status sources, normalizes the text,
and diffs against the last snapshot. Deltas are appended to
garden-reports/platform-delta.jsonl; the brain-gardener folds them into its
weekly report as proposed playbook/skill/terminology updates.

Zero-dependency (stdlib urllib + difflib). Sources live in sources.json beside
this script — add/remove sources there without touching code.

Usage: python3 workato-docs-watch.py            # normal run (diffs + logs)
       python3 workato-docs-watch.py --report   # print delta summary, write nothing
"""
import difflib
import hashlib
import json
import os
import re
import sys
import urllib.request
from datetime import datetime, timezone

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_append

HERE = os.path.dirname(os.path.abspath(__file__))
SNAP_DIR = os.path.expanduser('~/.claude/knowledge/garden-reports/docs-watch')
DELTA_LOG = os.path.expanduser('~/.claude/knowledge/garden-reports/platform-delta.jsonl')
UA = {'User-Agent': 'workato-docs-watch/1.0 (knowledge gardener)'}

HTML_TAG = re.compile(r'<[^>]+>')
WS = re.compile(r'\s+')


SCRIPT_BODY = re.compile(r'(?is)<(script|style)\b.*?</\1>')

def normalize(text):
    # strip script/style BODIES first (dynamic JS churns per fetch), then
    # tags, then collapse whitespace so layout churn doesn't count as change
    text = SCRIPT_BODY.sub(' ', text)
    text = HTML_TAG.sub(' ', text)
    return WS.sub(' ', text).strip()


def snap_name(url):
    return hashlib.sha256(url.encode()).hexdigest()[:16] + '.txt'


def fetch(url):
    req = urllib.request.Request(url, headers=UA)
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')


def main():
    report_only = '--report' in sys.argv
    sources = json.load(open(os.path.join(HERE, 'docs-watch-sources.json')))
    os.makedirs(SNAP_DIR, exist_ok=True)
    today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

    events = []
    for src in sources:
        url, label = src['url'], src['label']
        snap = os.path.join(SNAP_DIR, snap_name(url))
        try:
            text = normalize(fetch(url))
        except Exception as ex:
            events.append({'ts': today, 'url': url, 'label': label, 'kind': 'error',
                           'detail': str(ex)[:200]})
            continue
        digest = hashlib.sha256(text.encode()).hexdigest()[:12]
        if not os.path.exists(snap):
            open(snap, 'w').write(text)
            events.append({'ts': today, 'url': url, 'label': label, 'kind': 'baseline',
                           'chars': len(text), 'hash': digest})
            continue
        old = open(snap).read()
        if old == text:
            continue
        # changed: record a compact diff excerpt
        diff = list(difflib.unified_diff(old.split('. '), text.split('. '),
                                         lineterm='', n=1))
        added = [d[1:].strip() for d in diff if d.startswith('+') and not d.startswith('++')]
        excerpt = ' | '.join(added[:6])[:600]
        events.append({'ts': today, 'url': url, 'label': label, 'kind': 'changed',
                       'old_hash': hashlib.sha256(old.encode()).hexdigest()[:12],
                       'new_hash': digest, 'added_excerpt': excerpt})
        open(snap, 'w').write(text)

    if report_only:
        for e in events:
            print(json.dumps(e))
        return
    if events:
        atomic_append(DELTA_LOG, events)
        # gossip bus: docs-watch is the network's first poster each night;
        # the gardener (22:43) reads these deltas off the bus.
        post_to_gossip(events)
    baselines = sum(1 for e in events if e['kind'] == 'baseline')
    changed = sum(1 for e in events if e['kind'] == 'changed')
    errors = sum(1 for e in events if e['kind'] == 'error')
    print(f'docs-watch: {len(sources)} sources — {changed} changed, {baselines} new baseline, {errors} error(s)')


GOSSIP_OUTBOX = os.path.expanduser(
    '~/.claude/knowledge/dreams/bus/docs-watch.jsonl')


def post_to_gossip(events):
    """Append platform deltas to the docs-watch gossip outbox.

    Single-writer file (maildir pattern); append-only, one event per line,
    written atomically (temp + rename via atomic_io.atomic_append).
    Timestamps are REAL UTC now — the old code stamped a hardcoded
    T22:15:00Z "nightly slot" as if it were UTC, future-dating entries
    written at any other time and corrupting bus --since windows.
    Never throws: bus failure must not break the docs-watch run.
    """
    try:
        now = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
        rows = []
        for e in events:
            if e.get('kind') == 'error':
                continue  # transient fetch errors are not network findings
            slug = 'platform-delta-' + re.sub(
                r'[^a-z0-9]+', '-', e.get('label', 'source').lower()).strip('-')
            rows.append({
                'ts': now,
                'agent': 'docs-watch',
                'kind': 'finding',
                'subject': slug,
                'line': f"Workato platform docs changed: {e.get('label')} — {e.get('added_excerpt', '')[:120]}",
                'refs': [e.get('url', '')],
                'thread_id': slug,
                'corroborations': 0,
                'ttl_days': 14,
            })
        if rows:
            atomic_append(GOSSIP_OUTBOX, rows)
    except Exception as ex:
        print(f'docs-watch: gossip post failed (non-fatal): {ex}')


if __name__ == '__main__':
    main()
