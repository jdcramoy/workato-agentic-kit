#!/usr/bin/env python3
"""verify_one_shot.py — the push-then-verify loop, fused into one command.

The 3-day transcript mine (dreams/data/2026-10-11-mine.json) found the house
habit is 4+ calls every verify: recipe_get, job_list, trace fetch, grep —
56 occurrences in 3 days, each session re-plumbing the same read-back. This
script does the whole loop in one call, per the verify-recipe skill's
procedure:

    python3 verify_one_shot.py --recipe 82272892
    python3 verify_one_shot.py --recipe 82272892 --trace-key warning --profile josh-prod

Pipeline (all via the `wt` Developer-CLI passthrough, read-only):
  1. `wt recipes get`      -> recipe exists + identity (name, updated_at)
  2. `wt jobs list`        -> newest job for the recipe
  3. `wt jobs get`         -> the job's full trace
  4. grep the trace for --trace-key (default ERROR, case-insensitive)

Output: exactly one verdict line
    PASS  recipe=<id> job=<handle> status=<s> completed=<ts>
    FAIL  recipe=<id> job=<handle> status=<s> completed=<ts> [reason]
followed by the RAW trace lines that matched the key (indented `>` lines).
The script never prints a bare PASS: the matched lines ARE the evidence.
The test-automation checks API is the escalation path when a check-level
verdict is needed, not this script:
  https://docs.workato.com/en/test-automation/test-case-results.md

Exit code: 0 = PASS, 1 = FAIL, 2 = indeterminate (no jobs, wt error — never
a verdict). Stdlib only, read-only against Workato.
"""

import argparse
import json
import os
import re
import subprocess
import sys

WT = os.environ.get("WT_BIN", os.path.expanduser("~/.local/bin/wt"))
PROFILE = {"dev": "josh-us", "prod": "josh-prod"}
SNIPPET = 240  # cap per matched trace-line snippet


def wt(args, timeout=30):
    """Run one wt command; return (parsed_json, raw_stdout, error)."""
    cmd = [WT] + args + ["--raw", "--profile", PROFILE.get(PROFILE_NAME, PROFILE_NAME)]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except subprocess.TimeoutExpired:
        return None, "", "timeout"
    out = r.stdout.strip()
    if r.returncode != 0 or not out.startswith("{"):
        return None, out, (out or r.stderr)[:300]
    try:
        return json.loads(out), out, None
    except ValueError:
        return None, out, "unparseable wt output"


EMPTY_VAL = re.compile(r'"\s*:\s*(?:""|null)\s*[,}]', re.I)


def trace_hits(trace, key):
    """Yield (line_no, adapter, matched_snippet) for trace lines containing key.

    Key match is case-insensitive substring over the serialized line JSON —
    the same grep the house habit did by hand, but bounded and cited. An
    occurrence that is an EMPTY-VALUED field (`"error": ""` / `null`) does
    not count: a clean 200 response carries the error key with nothing in
    it, and calling that a failure would make the script lie the other way.
    """
    needle = key.lower()
    for i, line in enumerate(trace.get("lines") or [], 1):
        blob = json.dumps(line, default=str)
        real = []
        for m in re.finditer(re.escape(needle), blob.lower()):
            tail = blob[m.end():m.end() + 24]
            if EMPTY_VAL.match(tail):
                continue
            real.append(m.start())
        if not real:
            continue
        lo = max(0, real[0] - SNIPPET // 2)
        snippet = blob[lo:lo + SNIPPET]
        yield (line.get("recipe_line_number", i),
               line.get("adapter_name", "?"), snippet)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipe", required=True, help="recipe ID")
    ap.add_argument("--trace-key", default="ERROR",
                    help="key to grep the trace for (default ERROR)")
    ap.add_argument("--profile", default="josh-us",
                    help="wt profile: dev alias josh-us, prod alias josh-prod")
    args = ap.parse_args()
    global PROFILE_NAME
    PROFILE_NAME = args.profile

    rid = str(args.recipe)

    # 1. recipe exists / identity
    recipe, _, err = wt(["recipes", "get", rid])
    if recipe is None:
        print(f"INDETERMINATE recipe={rid} — recipes get failed: {err}")
        return 2
    name = recipe.get("name", "?")

    # 2. newest job
    jobs, _, err = wt(["jobs", "list", rid])
    if jobs is None:
        print(f"INDETERMINATE recipe={rid} — jobs list failed: {err}")
        return 2
    items = jobs.get("items") or []
    if not items:
        print(f"INDETERMINATE recipe={rid} ({name}) — no jobs ever ran")
        return 2
    newest = items[0]
    jid = newest.get("id") or newest.get("handle") or "?"
    status = newest.get("status") or ("failed" if newest.get("is_error") else "?")
    completed = newest.get("completed_at", "?")

    # 3. full trace
    trace, _, err = wt(["jobs", "get", rid, jid])
    if trace is None:
        print(f"INDETERMINATE recipe={rid} job={jid} — jobs get failed: {err}")
        return 2

    # 4. grep the trace
    hits = list(trace_hits(trace, args.trace_key))

    cite = f"recipe={rid} job={jid} status={status} completed={completed}"
    reasons = []
    if status != "succeeded":
        reasons.append(f"newest job not succeeded (status={status})")
    if hits:
        reasons.append(f"{len(hits)} trace line(s) matched '{args.trace_key}'")

    print(f"{'FAIL' if reasons else 'PASS'} {cite} ({name})")
    for reason in reasons:
        print(f"  reason: {reason}")
    for line_no, adapter, snippet in hits[:5]:
        print(f"  > line {line_no} [{adapter}]: {snippet}")
    if trace.get("error"):
        print(f"  > job error field: {json.dumps(trace['error'])[:SNIPPET]}")
    return 1 if reasons else 0


PROFILE_NAME = "josh-us"

if __name__ == "__main__":
    sys.exit(main())
