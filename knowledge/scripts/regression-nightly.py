#!/usr/bin/env python3
"""Nightly regression harness: run every recipe's test cases via the
Test Automation API and write a pass/fail report.

  1. Scan the workspace for recipes WITH test cases (GET test_cases per
     recipe — light calls; keeps a registry so unchanged recipes skip fast).
  2. POST one run request per recipe, poll to completion.
  3. Write garden-reports/regression-YYYY-MM-DD.md + regression-latest.md
     with per-case results and job IDs for autopsy.

Dev workspace by default (wt profile). Test runs execute real (is_test)
jobs against dev — cleared by standing policy; scope the profile if that
ever changes.

Usage: python3 regression-nightly.py [--max-recipes 300] [--skip-scan]
"""
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timezone

GARDEN = os.path.expanduser('~/.claude/knowledge/garden-reports')
CANON = os.path.expanduser('~/.claude/knowledge/regression-canon/canon.jsonl')


def load_canon():
    canon = {}
    try:
        for line in open(CANON):
            line = line.strip()
            if line:
                try:
                    e = json.loads(line)
                    canon.setdefault(str(e.get('recipe_id')), []).append(e)
                except Exception:
                    pass
    except OSError:
        pass
    return canon
REGISTRY = os.path.join(GARDEN, 'regression-registry.json')
WT = os.path.expanduser('~/.local/bin/wt')


def wt(*args):
    r = subprocess.run(['python3', WT, 'testcases', *args],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)  # [status, payload]
    except (json.JSONDecodeError, ValueError):
        return None, {'error': (r.stderr or r.stdout)[:200]}


def wt_api(path):
    r = subprocess.run(['python3', WT, 'api', 'GET', path],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        return None, {'error': (r.stderr or r.stdout)[:200]}


def scan_for_test_cases(max_recipes):
    """Return {recipe_id: (name, n_cases)} by walking the recipe list."""
    registry = {}
    if os.path.exists(REGISTRY):
        registry = json.load(open(REGISTRY))
    page = 1
    scanned = 0
    found = {}
    while page <= 10:
        r = wt_api(f'/api/recipes.json?per_page=100&page={page}')
        items = (r[1] if isinstance(r, (list, tuple)) else r).get('items', [])
        if not items:
            break
        for it in items:
            scanned += 1
            rid = str(it.get('id'))
            cached = registry.get(rid)
            if cached:  # known to have cases; still refresh count lazily
                found[rid] = (it.get('name', cached.get('name', '?')), None)
                continue
            tc = wt('cases', '--recipe', rid)
            body = tc[1] if isinstance(tc, (list, tuple)) else {}
            rows = body.get('data', []) if isinstance(body, dict) else []
            if rows:
                found[rid] = (it.get('name', '?'), len(rows))
            if scanned >= max_recipes:
                break
        page += 1
        if scanned >= max_recipes:
            break
    return found, scanned


def run_recipe_cases(rid):
    r = wt('run', '--recipe', rid)
    if not isinstance(r, (list, tuple)) or not r[1].get('data', {}).get('id'):
        return {'recipe_id': rid, 'error': 'could not start run', 'detail': str(r)[:150]}
    run_id = r[1]['data']['id']
    for _ in range(40):  # up to ~10 min
        time.sleep(15)
        s = wt('status', '--run-id', run_id)
        data = (s[1] if isinstance(s, (list, tuple)) else {}).get('data', {})
        if data.get('status') in ('completed', 'failed', 'error'):
            return {'recipe_id': rid, 'run_id': run_id, 'data': data}
    return {'recipe_id': rid, 'run_id': run_id, 'error': 'timed out polling'}


def main():
    max_recipes = 300
    if '--max-recipes' in sys.argv:
        max_recipes = int(sys.argv[sys.argv.index('--max-recipes') + 1])
    skip_scan = '--skip-scan' in sys.argv

    registry = {}
    if os.path.exists(REGISTRY):
        registry = json.load(open(REGISTRY))

    if not skip_scan:
        found, scanned = scan_for_test_cases(max_recipes)
        for rid, (name, n) in found.items():
            old = registry.get(rid, {})
            registry[rid] = {'name': name, 'cases': n or old.get('cases', '?')}
        json.dump(registry, open(REGISTRY, 'w'), indent=1)
        print(f'scan: {scanned} recipes, {len(registry)} with test cases')
    else:
        registry = {k: v for k, v in registry.items() if v.get('cases') not in (0, None)}
        print(f'skip-scan: {len(registry)} registered recipes with cases')

    results = []
    for rid, info in sorted(registry.items()):
        print(f'running: {rid} {info["name"]}...', flush=True)
        res = run_recipe_cases(rid)
        res['name'] = info['name']
        results.append(res)

    today = datetime.now(timezone.utc).date().isoformat()
    lines = [f'# Regression run — {today}', '']
    total_pass = total_fail = total_err = 0
    for res in results:
        if res.get('error'):
            total_err += 1
            lines.append(f"## {res['recipe_id']} {res.get('name','')} — ERROR: {res['error']}")
            continue
        data = res['data']
        cases = data.get('results', [])
        fails = [c for c in cases if c.get('status') == 'failed']
        lines.append(f"## [{res['recipe_id']}] {res['name']} — "
                     f"{len(cases) - len(fails)}/{len(cases)} passed "
                     f"(run {res['run_id']})")
        for c in cases:
            if c.get('status') == 'failed':
                total_fail += 1
                job = c.get('job', {}).get('id', '?')
                lines.append(f"- FAIL {c['test_case']['name']} — job {job}")
            else:
                total_pass += 1
    lines.insert(1, f'**{total_pass} passed, {total_fail} failed, {total_err} errors**')
    lines.append('')
    lines.append('_Dev-only test runs (is_test jobs). Failures carry job IDs for autopsy._')

    # canon auto-seed: a failure with no canon entry becomes one (status open).
    # Closes the intake lag — the canon grows itself instead of waiting for
    # the watchdog to rediscover failures.
    canon_path = CANON
    canon_now = load_canon()
    seeded = 0
    for res in results:
        if res.get('error'):
            continue
        data = res.get('data') or {}
        fails = [c for c in data.get('results', []) if c.get('status') == 'failed']
        rid = str(res['recipe_id'])
        if fails and rid not in canon_now:
            for c in fails:
                sig = ('regression-fail-' + re.sub(r'[^a-z0-9]+', '-',
                        c.get('test_case', {}).get('name', 'unknown').lower())[:48].strip('-'))
                canon_now.setdefault(rid, []).append({
                    'signature': sig, 'recipe_id': int(rid), 'kind': 'regression-failure',
                    'found_by': 'regression-nightly', 'found': today, 'status': 'open',
                    'test_case_id': c.get('test_case', {}).get('id'),
                    'line': f"Auto-seeded: test case '{c.get('test_case', {}).get('name', '?')}' failing (run {res.get('run_id')}, job {c.get('job', {}).get('id', '?')})"})
                seeded += 1
    if seeded:
        with open(canon_path, 'a') as fh:
            for entries in canon_now.values():
                for e in entries:
                    if e.get('found_by') == 'regression-nightly' and e.get('found') == today:
                        fh.write(json.dumps(e) + '\n')
        lines.insert(2, f'**canon auto-seeded {seeded} new failure(s)**')

    report = '\n'.join(lines) + '\n'
    for path in (os.path.join(GARDEN, f'regression-{today}.md'),
                 os.path.join(GARDEN, 'regression-latest.md')):
        open(path, 'w').write(report)
    print(report)


if __name__ == '__main__':
    main()
