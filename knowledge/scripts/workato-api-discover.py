#!/usr/bin/env python3
"""Workato Developer API self-discovery — the local API dictionary.

Harvests the Developer API endpoint reference (docs.workato.com serves the
page as clean markdown with .md variants) into a local index:
  ~/.claude/knowledge/workato-api/api-index.jsonl
  one line per endpoint: {group, method, path, description, doc_url}

Then diffs against the previous index: new endpoints, removed endpoints,
per-group counts. `wt discover` shells out to this and prints the coverage
report. The gardener folds new endpoints into the playbook and proposes new
wt subcommands (self-improvement loop).

Usage:
  python3 workato-api-discover.py [--refresh]   # harvest (default if index missing)
  python3 workato-api-discover.py --report      # coverage + gap report vs wt
"""
import json
import os
import re
import sys
import urllib.request

DOC_URL = 'https://docs.workato.com/en/workato-api/resources.md'
OUT_DIR = os.path.expanduser('~/.claude/knowledge/workato-api')
INDEX = os.path.join(OUT_DIR, 'api-index.jsonl')
PREV = os.path.join(OUT_DIR, 'api-index.prev.jsonl')
WT = os.path.expanduser('~/.local/bin/wt')

ROW = re.compile(r'^\|\s*([A-Z][A-Z/]+)\s*\|\s*\[?`?(/api/[^\s\]`|)]+)`?(?:\]\([^)]*\))?\s*\|\s*(.*?)\s*\|?\s*$')
SECTION = re.compile(r'^##\s+(.+?)\s*(?:\{:.*:\})?\s*$')


def fetch():
    req = urllib.request.Request(DOC_URL, headers={'User-Agent': 'wt-discover/1.0'})
    with urllib.request.urlopen(req, timeout=30) as r:
        return r.read().decode('utf-8', errors='replace')


def parse(md_text):
    endpoints = []
    group = 'General'
    for line in md_text.splitlines():
        sec = SECTION.match(line)
        if sec:
            group = sec.group(1).strip()
            continue
        row = ROW.match(line)
        if row:
            method, path, desc = row.group(1), row.group(2), row.group(3)
            path = path.replace('\\_', '_')
            desc = desc.replace('\\_', '_').strip()
            endpoints.append({
                'group': group,
                'method': method.strip(),
                'path': path,
                'description': desc,
                'doc_url': DOC_URL,
            })
    return endpoints



# --- scope-gap probe: for API groups with no dedicated wt subcommand, hit
# one endpoint; a login page or 401 missing_privilege = API client scope gap.
def probe_scope_gaps(profile=None):
    from importlib.machinery import SourceFileLoader
    if not os.path.exists(WT):
        return
    try:
        wt = SourceFileLoader('wtmod', WT).load_module()
        host, token = wt.client(type('A', (), {'profile': profile})())
    except Exception:
        print('(scope probe unavailable: could not resolve wt client)')
        return
    eps = [json.loads(l) for l in open(INDEX) if l.strip()]
    seen = {}
    for ep in eps:
        seen.setdefault(ep['group'], ep)
    impl = set(re.findall(r'add_parser\("([a-z_]+)"', open(WT).read()))
    gaps = []
    for g, ep in sorted(seen.items()):
        if any(i in g.lower().replace(' ', '') or g.lower().split()[0] in i
               for i in impl):
            continue
        try:
            rr = wt.request(host, token, 'GET', ep['path'])
            body = rr if isinstance(rr, str) else json.dumps(rr)
            if 'sign_in' in body or '<html' in body[:400]:
                gaps.append((g, ep['path'], 'login-page (scope not granted)'))
        except BaseException as ex:  # wt dies with SystemExit on 401s
            msg = str(ex)
            if '401' in msg or 'missing_privilege' in msg:
                gaps.append((g, ep['path'], '401 missing_privilege'))
            # other errors (404 on GET-only paths etc.) are not scope signals
    if gaps:
        print('SCOPE GAPS (grant these to your API client in Workspace admin):')
        for g, path, why in gaps:
            print(f'  {g}: {path} — {why}')
    else:
        print('scope probe: no gaps across unimplemented groups.')

def key(ep):
    return ep['method'] + ' ' + ep['path']


def wt_coverage():
    # Which API resource groups wt implements dedicated subcommands for.
    # The raw `wt api` passthrough reaches everything; gaps are ergonomics,
    # not capability.
    src = open(WT).read() if os.path.exists(WT) else ''
    groups = []
    for m in re.finditer(r'add_parser\("([a-z_]+)"', src):
        groups.append(m.group(1))
    return set(groups)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    mode = sys.argv[1] if len(sys.argv) > 1 else ''
    have_index = os.path.exists(INDEX)

    if mode in ('--refresh',) or not have_index:
        eps = parse(fetch())
        with open(INDEX, 'w') as f:
            for ep in eps:
                f.write(json.dumps(ep) + '\n')
        print(f'harvested {len(eps)} endpoints -> {INDEX}')

    eps = [json.loads(l) for l in open(INDEX) if l.strip()]
    by_group = {}
    for ep in eps:
        by_group.setdefault(ep['group'], []).append(ep)

    if mode != '--refresh':  # bare run and --report both print the report
        # diff vs previous
        prev = {}
        if os.path.exists(PREV):
            for l in open(PREV):
                if l.strip():
                    ep = json.loads(l)
                    prev[key(ep)] = ep
        cur = {key(ep): ep for ep in eps}
        added = [k for k in cur if k not in prev]
        removed = [k for k in prev if k not in cur]
        if added:
            print('NEW endpoints since last discovery:')
            for k in sorted(added)[:20]:
                print('  +', k, '-', cur[k]['description'][:70])
        if removed:
            print('REMOVED endpoints:')
            for k in sorted(removed)[:20]:
                print('  -', k)
        if not added and not removed:
            print('API surface unchanged since last discovery.')

        # gap report vs wt
        cov = wt_coverage()
        print(f"\nwt coverage: {len(cov)} dedicated groups: {', '.join(sorted(cov))}")
        print(f"API groups: {len(by_group)} — {', '.join(sorted(by_group))}")
        print("everything is reachable via `wt api METHOD <path>`; dedicated")
        print("subcommands are an ergonomics upgrade the gardener proposes.")
        probe_scope_gaps(os.environ.get('WT_PROFILE'))

    # rotate current -> previous for next diff
    if os.path.exists(INDEX):
        with open(INDEX) as f, open(PREV, 'w') as g:
            g.write(f.read())


if __name__ == '__main__':
    main()
