#!/usr/bin/env python3
"""Semantic-dedup shortlister for the knowledge tree (brain gardener, phase 2.5).

Zero-dependency: token-set (Jaccard) similarity between memory/knowledge files
shortlists *candidate* duplicate/near-duplicate pairs — the class grep cannot
catch ("same fact, different words"). The gardener's LLM adjudicates the
shortlist; this script's only job is to shrink hundreds of pairs to the few
worth reading.

Usage: python3 dedup-shortlist.py [--min 0.55] [--json]
"""
import json
import os
import re
import sys

KROOT = os.path.expanduser('~/.claude/knowledge')
MEMROOT = os.path.expanduser('~/.claude/projects/-Users-YOUR-USER-Documents-workbench/memory')

STOP = set('the a an and or of to in for on with by at from as is are was were be been it its this that these those not no'.split())

def tokens(path):
    try:
        text = open(path, encoding='utf-8', errors='replace').read()
    except OSError:
        return set()
    words = re.findall(r'[a-z][a-z0-9_-]{3,}', text.lower())
    return {w for w in words if w not in STOP}

def harvest(root):
    out = {}
    for dirpath, _dirs, files in os.walk(root):
        # Machine-generated dirs (estate sweeps, telemetry, append-ledgers)
        # produce thousands of 1.00-identical pairs that drown real
        # knowledge dupes — never candidates (2026-10-17).
        if any(part in dirpath.split(os.sep) for part in (
                'garden-reports', 'claims', 'scripts', 'workato-health',
                'sweeps', 'skills-telemetry', 'ops-visibility',
                'instruction-patches')):
            continue
        for f in files:
            if f.endswith('.md') or f.endswith('.jsonl'):
                p = os.path.join(dirpath, f)
                t = tokens(p)
                if len(t) >= 20:  # too small to compare meaningfully
                    out[p] = t
    return out

def main():
    minsim = 0.55
    as_json = '--json' in sys.argv
    if '--min' in sys.argv:
        minsim = float(sys.argv[sys.argv.index('--min') + 1])

    files = {}
    for root in (KROOT, MEMROOT):
        if os.path.isdir(root):
            files.update(harvest(root))
    # INDEX.md is a router, exclude from dup detection
    files.pop(os.path.join(KROOT, 'INDEX.md'), None)
    files.pop(os.path.join(MEMROOT, 'MEMORY.md'), None)

    paths = sorted(files)
    pairs = []
    for i in range(len(paths)):
        for j in range(i + 1, len(paths)):
            a, b = files[paths[i]], files[paths[j]]
            inter = len(a & b)
            if not inter:
                continue
            sim = inter / len(a | b)
            if sim >= minsim:
                pairs.append((round(sim, 3), paths[i], paths[j]))
    pairs.sort(reverse=True)

    if as_json:
        print(json.dumps([{'sim': s, 'a': a, 'b': b} for s, a, b in pairs], indent=1))
        return
    if not pairs:
        print(f'No pairs at similarity >= {minsim} across {len(paths)} files.')
        return
    print(f'{len(pairs)} candidate pair(s) at similarity >= {minsim} across {len(paths)} files:')
    for sim, a, b in pairs:
        print(f'  {sim:.2f}  {os.path.basename(a)}  <>  {os.path.basename(b)}')
        print(f'        {a}')
        print(f'        {b}')

if __name__ == '__main__':
    main()
