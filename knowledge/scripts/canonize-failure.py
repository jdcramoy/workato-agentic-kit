#!/usr/bin/env python3
"""canonize-failure.py — the failure-to-canon weld for Josh's agentic harness.

One command takes a dev job failure to full canonization (the four artifacts):
  1. autopsy-support md  -> ~/.claude/knowledge/regression-canon/<slug>.md
  2. canon entry         -> appended to regression-canon/canon.jsonl
  3. fixture scaffold    -> ~/.claude/knowledge/fixtures/<recipe>.json (via wt
                            fixture init; fill input + expects, then
                            `wt fixture run --recipe <id>`)
  4. nightly slot        -> the fixture's non-empty expect list is what the
                            regression-nightly fixture phase runs; filling the
                            scaffold IS the nightly registration

Usage:
  canonize-failure.py --recipe 82794233 --job j-AbrfmCLn-cFCLFM-CD \
                      --slug resolver-v2-catalog-snapshot [--skip-fixture]

The classification written here is PROVISIONAL (trace-heuristic). Run the
workato-autopsy skill on the same job to refine class, origin step, and the
proposed diff; the canon entry stays open until the fix closes it.
"""
import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timezone
from atomic_io import atomic_append

KNOW = os.path.expanduser('~/.claude/knowledge')
CANON = os.path.join(KNOW, 'regression-canon', 'canon.jsonl')
CANON_DIR = os.path.join(KNOW, 'regression-canon')
FIXTURE_DIR = os.path.join(KNOW, 'fixtures')
WT = os.path.expanduser('~/.local/bin/wt')


def kebab(s, maxlen=56):
    s = re.sub(r'[^a-z0-9]+', '-', (s or '').lower()).strip('-')
    return s[:maxlen].rstrip('-')


def wt_jobs_get(recipe, job):
    r = subprocess.run(['python3', WT, 'jobs', 'get', str(recipe), job, '--raw'],
                       capture_output=True, text=True)
    try:
        return json.loads(r.stdout)
    except (json.JSONDecodeError, ValueError):
        sys.exit(f'ERROR: wt jobs get returned unparseable output:\n'
                 f'{(r.stderr or r.stdout)[:500]}')


def line_err(l):
    """An error record on a trace line, or None."""
    for key in ('error_details', 'error'):
        v = l.get(key)
        if v and isinstance(v, dict):
            return v
    return None


def classify(job, err_msg):
    """Provisional class from the trace; autopsy refines. Buckets mirror the
    workato-autopsy skill, plus regression-failure for test-assertion deaths."""
    blob = ' '.join(filter(None, [
        (job.get('error_parts') or {}).get('error_type', ''),
        (job.get('error_parts') or {}).get('message', ''),
        err_msg or ''])).lower()
    if 'test automation' in blob or 'output check failed' in blob:
        return 'regression-failure'
    if any(k in blob for k in ('connection', 'unauthorized', 'auth', '401',
                               'invalid_client', 'oauth')):
        return 'connection-auth'
    if any(k in blob for k in ('timeout', 'timed out', 'poll')):
        return 'platform-change'
    if any(k in blob for k in ('unexpected token', 'undefined method',
                               'nomethoderror', 'no method', 'nil')):
        return 'input-contract-violation'
    return 'code-bug'


def signature_for(job, err_msg, klass):
    msg = ((job.get('error_parts') or {}).get('message')
           or err_msg or job.get('error') or 'unknown-failure')
    prefix = 'regression-fail' if klass == 'regression-failure' else 'fail'
    sig = kebab(f'{prefix}-{msg}')
    return sig or 'fail-unknown'


def fixture_step(recipe, skip_fixture):
    """Ensure the fixture scaffold exists; return (status_line, created_bool)."""
    fpath = os.path.join(FIXTURE_DIR, f'{recipe}.json')
    if os.path.exists(fpath):
        try:
            fx = json.load(open(fpath))
            n = len(fx.get('expect', []))
            if n:
                return (f'existing fixture {fpath} with {n} expect(s) — '
                        f'runnable: wt fixture run --recipe {recipe}'), False
            return (f'existing fixture {fpath} but 0 expects — fill input '
                    f'+ expects, then wt fixture run --recipe {recipe}'), False
        except (json.JSONDecodeError, OSError):
            return f'existing fixture {fpath} UNREADABLE — repair by hand', False
    if skip_fixture:
        return 'fixture skipped (--skip-fixture) — no scaffold created', False
    os.makedirs(FIXTURE_DIR, exist_ok=True)
    r = subprocess.run(['python3', WT, 'fixture', 'init', '--recipe', str(recipe)],
                       capture_output=True, text=True)
    if r.returncode != 0 or not os.path.exists(fpath):
        return (f'fixture init FAILED: {(r.stderr or r.stdout)[:200]} '
                f'— scaffold by hand with wt fixture init --recipe {recipe}'), False
    return (f'scaffolded {fpath} (empty) — NEEDS INPUT+EXPECTS before it '
            f'enters the nightly fixture phase (wt fixture run --recipe '
            f'{recipe})'), True


def canon_exists(recipe, job):
    try:
        for line in open(CANON):
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except Exception:
                continue
            if str(e.get('recipe_id')) == str(recipe) and \
                    str(e.get('job_id', '')) == str(job):
                return e
    except OSError:
        pass
    return None


def main():
    ap = argparse.ArgumentParser(description=__doc__)
    ap.add_argument('--recipe', required=True, help='recipe ID')
    ap.add_argument('--job', required=True, help='job handle (j-...)')
    ap.add_argument('--slug', required=True, help='kebab-case canon slug')
    ap.add_argument('--skip-fixture', action='store_true',
                    help='do not scaffold the fixture')
    a = ap.parse_args()
    slug = kebab(a.slug, 80)
    if not slug:
        sys.exit('ERROR: --slug must contain word characters')

    job = wt_jobs_get(a.recipe, a.job)
    if not isinstance(job, dict) or not job.get('lines'):
        sys.exit(f'ERROR: no trace lines for job {a.job} — is the handle right?')

    err_parts = job.get('error_parts') or {}
    # the reported (victim) message: deepest line error message, else the
    # job-level error_parts message, else the top-level error string
    line_errors = [(l, line_err(l)) for l in job['lines']]
    errored = [(l, e) for l, e in line_errors if e]
    deepest_msg = ''
    for l, e in reversed(errored):
        deepest_msg = e.get('message') or e.get('data') or ''
        if isinstance(deepest_msg, str) and deepest_msg:
            break
    err_msg = deepest_msg or err_parts.get('message', '') or str(job.get('error', ''))

    klass = classify(job, err_msg)
    signature = signature_for(job, err_msg, klass)
    origin = errored[0][0] if errored else None       # first step that erred
    victim = errored[-1][0] if errored else None      # where the job died
    ts = datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ')
    today = ts[:10]

    # ---- artifact 3: fixture scaffold ----
    fx_status, fx_created = fixture_step(a.recipe, a.skip_fixture)

    # ---- artifact 2: canon.jsonl entry ----
    dup = canon_exists(a.recipe, a.job)
    if dup:
        canon_note = (f"entry already exists for this job "
                      f"(signature {dup.get('signature')}) — not appended")
    else:
        entry = {
            'ts': ts, 'slug': slug,
            'recipe_id': int(a.recipe) if str(a.recipe).isdigit() else a.recipe,
            'job_id': a.job, 'class': klass, 'signature': signature,
            'kind': 'autopsy-canonization', 'found_by': 'canonize-failure',
            'found': today, 'status': 'open',
            'line': (f'Canonized from job {a.job}: {err_parts.get("message", err_msg)[:160]}'
                     f' — provisional class {klass}; refine via workato-autopsy'),
        }
        atomic_append(CANON, entry)
        canon_note = f'appended to {CANON} (signature {signature})'

    # ---- artifact 1: the md ----
    def step_desc(l):
        if not l:
            return 'none in trace'
        return (f"line {l.get('recipe_line_number')} "
                f"({l.get('adapter_name')}/{l.get('adapter_operation')})")

    md_path = os.path.join(CANON_DIR, f'{slug}.md')
    md = f"""# Failure canon: {slug}

- **recipe:** [{a.recipe}](https://app.workato.com/recipes/{a.recipe})
- **job:** {a.job} (dev)
- **canonized:** {ts}
- **failure class (provisional):** {klass}
- **error signature:** `{signature}`
- **status:** open

## Error signature

`{signature}` — {err_parts.get('message', err_msg)[:300]}
(error_type: {err_parts.get('error_type', 'n/a')})

## Trace map (trace-derived; autopsy names the true origin)

- **origin candidate:** {step_desc(origin)} — first step with an error record
- **victim step:** {step_desc(victim)} — last step with an error record (where the job died)
- **top-level error:** {str(job.get('error', ''))[:200]}

## Classification

Provisional: **{klass}** (trace heuristic). Refine with the workato-autopsy
skill on this job — it maps trace to recipe code, correlates the green→red
window, and produces the proposed diff. Update this file and the canon entry
class when it does.

## Fixture status

{fx_status}

The scaffold is intentionally EMPTY — do not guess input. Fill `input` and
`expect` from the autopsy's "test case that would have caught it", then
`wt fixture run --recipe {a.recipe}`. A non-empty expect list is what the
nightly regression fixture phase runs; filling it IS the nightly slot.

## Canon entry

{canon_note}

## Close-out

1. workato-autopsy on [{a.job}](https://app.workato.com/recipes/{a.recipe}) — refine class + diff.
2. Fill the fixture input + expects (testcase-authoring skill).
3. Fix, prove with a live job trace, `wt fixture run` green.
4. Set the canon entry status to closed (class verified, fixture guarding).
"""
    with open(md_path, 'w') as fh:
        fh.write(md)

    print(f'canonized: {slug}')
    print(f'  recipe {a.recipe} job {a.job} class={klass} signature={signature}')
    print(f'  md: {md_path}')
    print(f'  canon: {canon_note}')
    print(f'  fixture: {fx_status}')


if __name__ == '__main__':
    main()
