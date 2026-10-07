#!/usr/bin/env python3
"""Workato formula-function library harvester.

Pulls all five formula reference pages (docs.workato.com serves clean .md)
into knowledge/workato-terms/formulas.jsonl:
  {category, section, name, syntax, description, example, source}

Then `glossary.py --store formulas.jsonl lookup <fn>` answers "what does
.blank? do" instantly, offline. The gardener re-runs --refresh weekly;
new functions are diffed like API endpoints.

Usage: python3 workato-formulas-harvest.py [--refresh] [--report]
"""
import json
import os
import re
import sys
import urllib.request

PAGES = [
    ('string', 'https://docs.workato.com/en/formulas/string-formulas.md'),
    ('number', 'https://docs.workato.com/en/formulas/number-formulas.md'),
    ('date', 'https://docs.workato.com/en/formulas/date-formulas.md'),
    ('list', 'https://docs.workato.com/en/formulas/array-list-formulas.md'),
    ('complex', 'https://docs.workato.com/en/formulas/complex-data-types.md'),
]
OUT_DIR = os.path.expanduser('~/.claude/knowledge/workato-terms')
OUT = os.path.join(OUT_DIR, 'formulas.jsonl')

FUNC_HEAD = re.compile(r'^###\s+`?([^`{:]+?)`?\s*(?:\{:.*:\})?\s*$')
SECTION_HEAD = re.compile(r'^##\s+(.+?)\s*(?:\{:.*:\})?\s*$')
SAMPLE_ROW = re.compile(r'^\|\s*[<`]?\s*[kK]bd')


def fetch(url):
    req = urllib.request.Request(url, headers={'User-Agent': 'wt-formulas/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')


SPAN = re.compile(r'</?span[^>]*>')

def clean(s):
    s = SPAN.sub('', s)
    return re.sub(r'\s+', ' ', s.replace('<kbd>', '').replace('</kbd>', '')
                  .replace('`', '').replace('\\_', '_')).strip()


def parse_page(category, url, text):
    out = []
    section = ''
    cur = None
    in_samples = False
    for line in text.splitlines():
        m = SECTION_HEAD.match(line)
        if m:
            section = clean(m.group(1))
            cur = None
            continue
        m = FUNC_HEAD.match(line)
        if m and m.group(1).lower() not in ('syntax', 'see also', 'how it works',
                                            'sample usage', 'exceptions'):
            cur = {'category': category, 'section': section,
                   'name': m.group(1).strip(), 'syntax': '',
                   'description': '', 'example': '', 'source': url}
            out.append(cur)
            in_samples = False
            continue
        if cur is None:
            continue
        if line.startswith('#### Syntax'):
            in_samples = 'syntax'; continue
        if line.startswith('#### Sample usage'):
            in_samples = 'usage'; continue
        if line.startswith('#### How it works'):
            in_samples = 'how'; continue
        if line.startswith('####'):
            in_samples = False; continue
        if not cur['description'] and line.strip() and not line.startswith('|') \
                and not line.startswith('#') and not line.startswith('*'):
            cur['description'] = clean(line)
        if in_samples == 'syntax' and line.strip() and not line.startswith('#'):
            cur['syntax'] += clean(line) + ' '
        if in_samples == 'usage' and line.startswith('|') and SAMPLE_ROW.match(line) is None \
                and 'Formula' not in line and 'Result' not in line \
                and not re.match(r'^\|[\s\-|]+$', line):
            if not cur['example']:
                cur['example'] = ' | '.join(
                    c.strip() for c in line.strip().strip('|').split('|'))[:200]
    return [f for f in out if f['name']]


def main():
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    have = os.path.exists(OUT)
    if mode == '--refresh' or not have:
        all_fns = []
        for cat, url in PAGES:
            fns = parse_page(cat, url, fetch(url))
            print(f'{cat}: {len(fns)} functions')
            all_fns.extend(fns)
        os.makedirs(OUT_DIR, exist_ok=True)
        with open(OUT, 'w') as f:
            for fn in all_fns:
                f.write(json.dumps(fn) + '\n')
        print(f'total {len(all_fns)} formulas -> {OUT}')
        return
    # report mode: counts
    rows = [json.loads(l) for l in open(OUT) if l.strip()]
    from collections import Counter
    c = Counter(r['category'] for r in rows)
    print(f'{len(rows)} formulas: ' + ', '.join(f'{k}={v}' for k, v in c.items()))


if __name__ == '__main__':
    main()
