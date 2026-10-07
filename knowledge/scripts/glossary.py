#!/usr/bin/env python3
"""Workato terminology dictionary — ever-expanding, locally stored.

    glossary.py lookup <term>       definition + example
    glossary.py search <keyword>    terms mentioning keyword
    glossary.py add <term> <definition> [--source URL] [--tags a,b]

Store: ~/.claude/knowledge/workato-terms/terms.jsonl
{term, definition, example?, source?, tags?, added_at, updated_at}

The brain gardener grows this file from platform deltas, session
transcripts, and docs crawls (its SOP has the phase). Humans and sessions
add terms the same way — append, supersede on redefinition.
"""
import argparse
import json
import os
import sys
from datetime import datetime, timezone

STORE = os.path.expanduser('~/.claude/knowledge/workato-terms/terms.jsonl')  # overridden by --store


def load():
    if not os.path.exists(STORE):
        return []
    return [json.loads(l) for l in open(STORE, encoding='utf-8', errors='replace') if l.strip()]


def save(rows):
    os.makedirs(os.path.dirname(STORE), exist_ok=True)
    with open(STORE, 'w') as f:
        for r in rows:
            f.write(json.dumps(r) + '\n')


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('op', choices=['lookup', 'search', 'add', 'count'])
    ap.add_argument('term', nargs='?', default=None)
    ap.add_argument('definition', nargs='?', default=None)
    ap.add_argument('--source', default=None)
    ap.add_argument('--tags', default='')
    ap.add_argument('--store', default=None, help='alternate store, e.g. formulas.jsonl')
    args = ap.parse_args()

    if args.store:
        globals()['STORE'] = os.path.expanduser(args.store)
    rows = load()
    now = datetime.now(timezone.utc).date().isoformat()

    if args.op == 'count':
        print(f'{len(rows)} terms'); return
    if args.op == 'add':
        if not args.term or not args.definition:
            sys.exit('add requires <term> <definition>')
        new = {'term': args.term.lower(), 'definition': args.definition,
               'source': args.source, 'tags': [t for t in args.tags.split(',') if t],
               'added_at': now, 'updated_at': now}
        rows = [r for r in rows if r['term'] != args.term.lower()] + [new]
        save(rows); print(f"added: {new['term']} ({len(rows)} terms)"); return
    q = (args.term or '').lower()
    if args.op == 'lookup':
        for r in rows:
            if (r.get('term') or r.get('name', '')).lower() == q:
                print(json.dumps(r, indent=1)); return
        partial = [r for r in rows if q and q in (r.get('term') or r.get('name', ''))]
        if partial:
            print('exact term not found; partial matches:', ', '.join((r.get('term') or r.get('name','')) for r in partial))
        else:
            print(f"not in glossary: {q!r} — add it: glossary.py add '{q}' '<definition>'")
        return
    # search
    hits = [r for r in rows if q in json.dumps(r).lower()]
    for r in hits:
        name = r.get('term') or r.get('name', '')
        print(f"{name}: {(r.get('definition') or '')[:140]}")
    if not hits:
        print(f"no terms mention {q!r}")


if __name__ == '__main__':
    main()
