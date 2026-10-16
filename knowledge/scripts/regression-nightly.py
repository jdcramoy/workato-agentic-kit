#!/usr/bin/env python3
"""Nightly regression harness: run every recipe's test cases via the
Test Automation API and write a pass/fail report.

  1. Scan the workspace for recipes WITH test cases (GET test_cases per
     recipe; the registry caches names/counts as a fallback, but every
     recipe's case list is re-verified live each run so deleted-case
     recipes fall out instead of erroring forever).
  2. POST one run request per recipe, poll to completion.
  3. Write garden-reports/regression-YYYY-MM-DD.md + regression-latest.md
     with per-case results and job IDs for autopsy.

Dev workspace by default (wt profile). Test runs execute real (is_test)
jobs against dev — cleared by standing policy; scope the profile if that
ever changes.

Usage: python3 regression-nightly.py [--max-recipes 1000] [--skip-scan]
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
FIXTURE_DIR = os.path.expanduser('~/.claude/knowledge/fixtures')
MAX_SCAN_PAGES = 50  # 50x100 = 5000 recipes; dev crossed 1000 on 2026-10-09,
                     # so the old 10-page cap silently ended the re-verify walk
                     # mid-estate (BSYS-29459)


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
    """Return ({recipe_id: (name, n_cases)}, scanned, stale, unclear) by
    walking the recipe list. Every recipe's case list is re-verified against
    the live Test Automation API each run — cached counts are only a
    fallback for transient API errors, so recipes whose test cases were
    deliberately deleted drop out of the registry instead of erroring
    nightly forever. `stale` lists 'rid name' strings that the cache
    claimed had cases but the live API shows zero (dropped by main);
    `unclear` lists ones where the API errored (cache kept as fallback)."""
    registry = {}
    if os.path.exists(REGISTRY):
        registry = json.load(open(REGISTRY))
    page = 1
    scanned = 0
    found = {}
    stale = []
    unclear = []
    capped = False
    while page <= MAX_SCAN_PAGES:
        r = wt_api(f'/api/recipes.json?per_page=100&page={page}')
        items = (r[1] if isinstance(r, (list, tuple)) else r).get('items', [])
        if not items:
            break
        if page == MAX_SCAN_PAGES:
            capped = True  # estate larger than the walk; raise MAX_SCAN_PAGES
        for it in items:
            scanned += 1
            rid = str(it.get('id'))
            cached = registry.get(rid)
            tc = wt('cases', '--recipe', rid)  # re-verify live, cached or not
            if isinstance(tc, (list, tuple)) and isinstance(tc[1], dict):
                rows = tc[1].get('data', [])
            else:
                rows = None  # API error — ambiguous, don't trust either way
            label = it.get('name', (cached or {}).get('name', '?'))
            if rows:
                found[rid] = (label, len(rows))
            elif rows == [] and cached:
                stale.append(f'{rid} {label}')  # cache stale: cases are gone
            elif rows is None and cached:
                unclear.append(f'{rid} {label}')
                found[rid] = (label, None)  # keep cached count as fallback
            if scanned >= max_recipes:
                break
        page += 1
        if scanned >= max_recipes:
            break
    return found, scanned, stale, unclear, capped


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


def run_fixture_phase():
    """Fixture regression phase: every fixture with a non-empty expect list
    runs via `wt fixture run` (webhook/force-run invoke -> catch job ->
    assert output). A fixture failure IS a regression failure. Fixtures with
    empty expects (unfilled scaffolds) are skipped, not counted."""
    results = []
    if not os.path.isdir(FIXTURE_DIR):
        return results
    for fn in sorted(os.listdir(FIXTURE_DIR)):
        if not fn.endswith('.json'):
            continue
        path = os.path.join(FIXTURE_DIR, fn)
        try:
            fx = json.load(open(path))
        except (json.JSONDecodeError, OSError) as e:
            results.append({'file': fn, 'verdict': 'error', 'failures': [f'unreadable fixture: {e}']})
            continue
        if not fx.get('expect'):
            results.append({'file': fn, 'recipe_id': fx.get('recipe_id'),
                            'verdict': 'skipped', 'note': 'no expects (unfilled scaffold)'})
            continue
        rid = fx.get('recipe_id')
        print(f'fixture: running {fn} (recipe {rid})...', flush=True)
        r = subprocess.run(['python3', WT, 'fixture', 'run', '--recipe', str(rid)],
                           capture_output=True, text=True)
        try:
            res = json.loads(r.stdout)
        except (json.JSONDecodeError, ValueError):
            res = {'verdict': 'error', 'failures': [(r.stderr or r.stdout)[:200]]}
        res['file'] = fn
        res['recipe_id'] = rid
        results.append(res)
    return results


def main():
    max_recipes = 1000  # cover the whole estate (page walk caps at 10x100) —
                        # a deleted-case recipe past the cutoff would never
                        # get its stale cache entry re-verified
    if '--max-recipes' in sys.argv:
        max_recipes = int(sys.argv[sys.argv.index('--max-recipes') + 1])
    skip_scan = '--skip-scan' in sys.argv

    registry = {}
    if os.path.exists(REGISTRY):
        registry = json.load(open(REGISTRY))

    stale, unclear = [], []
    if not skip_scan:
        found, scanned, stale, unclear, capped = scan_for_test_cases(max_recipes)
        for rid, (name, n) in found.items():
            old = registry.get(rid, {})
            registry[rid] = {'name': name, 'cases': n if n is not None else old.get('cases', '?')}
        for entry in stale:  # cached cases no longer exist live — refresh away
            registry.pop(entry.split(' ', 1)[0], None)
        json.dump(registry, open(REGISTRY, 'w'), indent=1)
        capnote = ' — PAGE CAP HIT, raise MAX_SCAN_PAGES' if capped else ''
        print(f'scan: {scanned} recipes, {len(registry)} with test cases '
              f'({len(stale)} stale cache entries dropped, '
              f'{len(unclear)} kept on API error){capnote}')
    else:
        registry = {k: v for k, v in registry.items() if v.get('cases') not in (0, None)}
        print(f'skip-scan: {len(registry)} registered recipes with cases')

    results = []
    for rid, info in sorted(registry.items()):
        print(f'running: {rid} {info["name"]}...', flush=True)
        res = run_recipe_cases(rid)
        res['name'] = info['name']
        results.append(res)

    # fixture phase: run every fixture with non-empty expects
    print(f'fixture phase: scanning {FIXTURE_DIR}...', flush=True)
    fixtures = run_fixture_phase()

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

    fx_pass = fx_fail = fx_skip = 0
    lines.append('')
    lines.append('## Fixture phase')
    for f in fixtures:
        verdict = f.get('verdict', 'error')
        if verdict == 'pass':
            fx_pass += 1
            n_checks = len(f.get('checks', []))
            lines.append(f"- PASS {f['file']} recipe {f.get('recipe_id')} — "
                         f"job {f.get('job_id', '?')} ({n_checks} checks)")
        elif verdict == 'skipped':
            fx_skip += 1
            lines.append(f"- SKIP {f['file']} — {f.get('note', 'no expects')}")
        else:  # fail / timeout / error — a fixture failure IS a regression failure
            fx_fail += 1
            job = f.get('job_id', '?')
            detail = '; '.join(f.get('failures', [])[:3]) or verdict
            lines.append(f"- FAIL {f['file']} recipe {f.get('recipe_id', '?')} — "
                         f"job {job} — {detail}")

    fx_head = (f' — fixtures: {fx_pass} pass / {fx_fail} fail'
               f' / {fx_skip} skipped') if fixtures else ''
    lines.insert(1, f'**{total_pass} passed, {total_fail} failed, '
                    f'{total_err} errors**{fx_head}')
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

    # registry refresh detail: surface what the re-verify pass changed so a
    # silently-deleted test case shows up in the report, not just the errors.
    if not skip_scan and (stale or unclear):
        detail = []
        if stale:
            detail.append('refreshed out — cached cases no longer exist live: '
                          + ', '.join(stale))
        if unclear:
            detail.append('kept on cached counts (API error during re-verify): '
                          + ', '.join(unclear))
        lines.insert(2, '**registry cache re-verified: ' + '; '.join(detail) + '**')
    if not skip_scan and capped:
        lines.insert(2, '**registry scan hit the page cap before covering the '
                        'estate — some recipes not re-verified this run**')

    report = '\n'.join(lines) + '\n'
    for path in (os.path.join(GARDEN, f'regression-{today}.md'),
                 os.path.join(GARDEN, 'regression-latest.md')):
        open(path, 'w').write(report)
    print(report)


if __name__ == '__main__':
    main()
