#!/usr/bin/env python3
"""Denominator oracle — every claimed result carries its population size.

Usage:
  coverage.py declare --run-id X --population "..." --expected-n N --observed-n M \
      [--source "..."] [--unbounded-sampled]
  coverage.py report [--ledger PATH]

Appends one coverage line to knowledge/coverage/ledger.jsonl (schema per
frontier CONTRACTS.md) and prints the status:
  ok                 coverage >= 0.95 (and not --unbounded-sampled)
  undercollect       coverage < 0.95
  unbounded-sampled  caller declared the population not fully enumerated

`--unbounded-sampled` means expected_n is a SAMPLE bound, not the true
denominator — the line is recorded but never counts as "ok".

Schema:
{"ts","job_or_run_id","population","expected_n","observed_n","coverage" (0-1),
 "source_of_expected","status":"ok|undercollect|unbounded-sampled"}

Pure stdlib. JSONL append-only. Exit 0 on write, 1 on validation error.
"""
import argparse
import json
import os
import sys
import time

LEDGER = os.path.expanduser("~/.claude/knowledge/coverage/ledger.jsonl")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def declare(args):
    if args.expected_n < 0 or args.observed_n < 0:
        sys.exit("expected-n and observed-n must be non-negative")
    if args.expected_n == 0:
        coverage = 1.0
        note = "expected_n=0: nothing to observe, counted fully covered"
    else:
        coverage = round(args.observed_n / args.expected_n, 4)
        note = None
    if args.unbounded_sampled:
        status = "unbounded-sampled"
    elif coverage >= 0.95:
        status = "ok"
    else:
        status = "undercollect"
    line = {
        "ts": now_iso(),
        "job_or_run_id": args.run_id,
        "population": args.population,
        "expected_n": args.expected_n,
        "observed_n": args.observed_n,
        "coverage": coverage,
        "source_of_expected": args.source or "",
        "status": status,
    }
    if note:
        line["note"] = note
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(line) + "\n")
    print(f"OK  {args.run_id}  coverage={coverage:.2f}  status={status}")
    print(f"    {args.population} ({args.observed_n}/{args.expected_n})")
    if args.unbounded_sampled:
        print("    note: unbounded-sampled — expected_n is a sample bound, not the true denominator")
    elif status == "undercollect":
        print(f"    note: below the 0.95 bar by {0.95 - coverage:.2f} — {args.expected_n - args.observed_n} unobserved")
    print(f"    -> {LEDGER}")
    return 0


def report(args):
    if not os.path.exists(args.ledger):
        sys.exit(f"ledger not found: {args.ledger} (nothing declared yet)")
    rows = []
    with open(args.ledger) as f:
        for n, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError as e:
                print(f"WARN ledger line {n} malformed, skipped: {e}", file=sys.stderr)
    if not rows:
        print("ledger is empty")
        return 0
    counts = {}
    for r in rows:
        counts[r.get("status", "?")] = counts.get(r.get("status", "?"), 0) + 1
    bounded = [r for r in rows if r.get("status") != "unbounded-sampled" and r.get("expected_n", 0) > 0]
    mean = sum(r["coverage"] for r in bounded) / len(bounded) if bounded else None
    print(f"coverage ledger — {len(rows)} lines, {os.path.basename(args.ledger)}")
    print("  " + "  ".join(f"{k}={v}" for k, v in sorted(counts.items())))
    if mean is not None:
        print(f"  mean coverage (bounded populations): {mean:.2f}")
    print()
    for r in rows:
        print(f"  {r.get('ts', '?')}  {r.get('job_or_run_id', '?'):32s}  "
              f"{r.get('observed_n')}/{r.get('expected_n')} = {r.get('coverage'):.2f}  {r.get('status')}")
        print(f"      {r.get('population', '')}")
    under = counts.get("undercollect", 0) + counts.get("unbounded-sampled", 0)
    print(f"\n  verdict: {'HEALTHY' if under == 0 else f'{under} line(s) need a real denominator or more collection'}")
    return 0


def main():
    ap = argparse.ArgumentParser(description="Denominator oracle: coverage lines for claimed results.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    d = sub.add_parser("declare", help="append one coverage line")
    d.add_argument("--run-id", required=True)
    d.add_argument("--population", required=True, help="what the denominator is (human text)")
    d.add_argument("--expected-n", type=int, required=True)
    d.add_argument("--observed-n", type=int, required=True)
    d.add_argument("--source", dest="source", default="", help="where expected_n came from")
    d.add_argument("--unbounded-sampled", action="store_true",
                   help="expected_n is a sample bound, not the full population")

    r = sub.add_parser("report", help="summarize the ledger")
    r.add_argument("--ledger", default=LEDGER)

    args = ap.parse_args()
    if args.cmd == "declare":
        return declare(args)
    return report(args)


if __name__ == "__main__":
    sys.exit(main())
