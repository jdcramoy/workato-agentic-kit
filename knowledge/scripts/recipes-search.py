#!/usr/bin/env python3
"""Search the local recipe corpus index (brain gardener / corpus indexer).

The index is ~/.claude/knowledge/garden-reports/recipes-index.jsonl, built by
the weekly corpus-indexer task (an agent pages AIRO recipe_list + the
dependency tracker and writes one JSON line per recipe). This script answers
"have we built something like X before?" in milliseconds, offline.

Usage: python3 recipes-search.py "payment elections"
       python3 recipes-search.py --folder 30326966
       python3 recipes-search.py --similar-to 74912047
"""
import argparse
import json
import os
import re

INDEX = os.path.expanduser('~/.claude/knowledge/garden-reports/recipes-index.jsonl')
STOP = set('the a an and or of to in for on with by at from as is are was were'.split())


def load():
    rows = []
    if not os.path.exists(INDEX):
        print('No index at', INDEX, '— run the corpus-indexer task first.')
        raise SystemExit(1)
    for line in open(INDEX, encoding='utf-8', errors='replace'):
        line = line.strip()
        if line:
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def words(s):
    return {w for w in re.findall(r'[a-z][a-z0-9_-]{2,}', (s or '').lower()) if w not in STOP}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('query', nargs='?', default=None)
    ap.add_argument('--folder', default=None)
    ap.add_argument('--similar-to', default=None)
    ap.add_argument('--limit', type=int, default=10)
    args = ap.parse_args()

    rows = load()
    print(f'{len(rows)} recipes in index')

    if args.similar_to:
        base = next((r for r in rows if str(r.get('recipe_id')) == str(args.similar_to)), None)
        if not base:
            print('recipe', args.similar_to, 'not in index')
            raise SystemExit(1)
        bw = words(str(base.get('name', '')) + ' ' + str(base.get('description', '')))
        scored = []
        for r in rows:
            if r is base:
                continue
            rw = words(str(r.get('name', '')) + ' ' + str(r.get('description', '')))
            sim = len(bw & rw) / max(1, len(bw | rw))
            if sim > 0.15:
                scored.append((sim, r))
        scored.sort(key=lambda x: -x[0])
        for sim, r in scored[: args.limit]:
            print(f'  {sim:.2f}  {r.get("recipe_id")}  {r.get("name")}')
            print(f'         https://app.workato.com/recipes/{r.get("recipe_id")}')
        return

    if args.folder:
        rows = [r for r in rows if str(r.get('folder_id')) == str(args.folder)]
        print(f'{len(rows)} in folder {args.folder}')

    if args.query:
        qw = words(args.query)
        scored = []
        for r in rows:
            blob = str(r.get('name', '')) + ' ' + str(r.get('description', ''))
            rw = words(blob)
            hits = len(qw & rw)
            if hits:
                scored.append((hits, r))
        scored.sort(key=lambda x: -x[0])
        rows = [r for _, r in scored[: args.limit]]

    for r in rows:
        print(f"  {r.get('recipe_id')}  {r.get('name')}  (folder {r.get('folder_id')}, running={r.get('running')})")
        print(f'         https://app.workato.com/recipes/{r.get("recipe_id")}')


if __name__ == '__main__':
    main()
