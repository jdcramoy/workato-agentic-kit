#!/usr/bin/env python3
"""prediction-submit.py — append a falsifiable prediction to the Calibration Ledger.

Ownership (frontier CONTRACTS.md): knowledge/predictions/ + this script.
Appends one JSONL line, append-only:

  {"id","ts","agent","claim","confidence" (0-1 exclusive),"resolve_by" (ISO date),
   "resolver_query","consequential": true|false,"status":"open"}

resolver_query convention (consumed by brier-resolve.py):
  wt-health:recipe=<id>:expect=running|stopped|new-failures|no-new-failures
  wt-health:sweeps:indicator=<name>:expect=above-baseline|below-baseline
  manual                       -> nightly resolver flags it "needs-josh"
  anything else                -> nightly resolver extends resolve_by (+7d, "unresolved-extended")

Exit codes: 0 appended, 1 validation error / write failure.
"""
import argparse, json, os, re, sys, time
from datetime import date, datetime

LEDGER = os.path.expanduser("~/.claude/knowledge/predictions/predictions.jsonl")
VALID_EXPECT = {"running", "stopped", "new-failures", "no-new-failures",
                "above-baseline", "below-baseline"}


def next_id(rows):
    """Sequential prd-NNN based on max existing numeric suffix."""
    hi = 0
    for r in rows:
        m = re.match(r"prd-(\d+)$", str(r.get("id", "")))
        if m:
            hi = max(hi, int(m.group(1)))
    return f"prd-{hi + 1:03d}"


def validate_wt_health(q):
    """Return (ok, err) for a wt-health resolver query."""
    m = re.match(r"^wt-health:recipe=(\d+):expect=(\w[\w-]*)$", q)
    if m:
        if m.group(2) not in VALID_EXPECT:
            return False, f"expect='{m.group(2)}' not one of {sorted(VALID_EXPECT)}"
        return True, ""
    m = re.match(r"^wt-health:sweeps:indicator=(\w[\w-]*):expect=(\w[\w-]*)$", q)
    if m:
        if m.group(2) not in ("above-baseline", "below-baseline"):
            return False, f"sweeps expect='{m.group(2)}' must be above-baseline|below-baseline"
        return True, ""
    return False, ("wt-health query must be "
                   "'wt-health:recipe=<id>:expect=<kind>' or "
                   "'wt-health:sweeps:indicator=<name>:expect=<above|below>-baseline'")


def main():
    ap = argparse.ArgumentParser(
        description="Submit a falsifiable prediction to the Calibration Ledger "
                    f"({LEDGER}). Confidence must be strictly inside (0,1) — "
                    "0 and 1 are anti-Bayesian certainties and are rejected.")
    ap.add_argument("--agent", required=True, help="who is on record (agent or 'josh')")
    ap.add_argument("--claim", required=True, help="falsifiable claim text")
    ap.add_argument("--confidence", required=True, type=float, help="0 < c < 1")
    ap.add_argument("--resolve-by", required=True, dest="resolve_by",
                    help="ISO date YYYY-MM-DD the claim is due for resolution")
    ap.add_argument("--resolver-query", required=True, dest="resolver_query",
                    help="how brier-resolve.py checks it (see --help header)")
    ap.add_argument("--consequential", action="store_true",
                    help="boldness flag: a prediction that costs something if wrong")
    ap.add_argument("--id", help="explicit id (default: sequential prd-NNN)")
    args = ap.parse_args()

    c = args.confidence
    if not (0.0 < c < 1.0):
        sys.exit(f"error: confidence {c} rejected — must be strictly inside (0,1); "
                 "certainty (0 or 1) is not a prediction")

    try:
        due = datetime.strptime(args.resolve_by, "%Y-%m-%d").date()
    except ValueError:
        sys.exit(f"error: --resolve-by must be YYYY-MM-DD, got {args.resolve_by!r}")
    today = date.today()
    if due < today:
        print(f"WARNING: resolve_by {due} is in the past (today {today.isoformat()}); "
              "submitting anyway — brier-resolve will attempt it on the next run",
              file=sys.stderr)

    rq = args.resolver_query.strip()
    if rq.startswith("wt-health"):
        ok, err = validate_wt_health(rq)
        if not ok:
            sys.exit(f"error: {err}")
    elif rq != "manual":
        # non-standard queries are allowed but resolve as unresolved-extended
        print("NOTE: resolver_query is neither 'manual' nor a wt-health pattern; "
              "the nightly resolver will treat it as unresolved-extended (+7d)",
              file=sys.stderr)

    rows = read_rows()
    rid = args.id or next_id(rows)
    if any(r.get("id") == rid for r in rows):
        sys.exit(f"error: id {rid} already exists in the ledger")

    row = {
        "id": rid,
        "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
        "agent": args.agent,
        "claim": args.claim,
        "confidence": round(c, 4),
        "resolve_by": due.isoformat(),
        "resolver_query": rq,
        "consequential": bool(args.consequential),
        "status": "open",
    }
    append(row)
    print(f"appended {rid} [{row['agent']}] conf={row['confidence']} "
          f"resolve_by={row['resolve_by']}{' *consequential*' if row['consequential'] else ''}")
    print(f"  claim: {row['claim']}")
    print(f"  resolver: {row['resolver_query']}")


def read_rows():
    if not os.path.exists(LEDGER):
        return []
    out = []
    with open(LEDGER) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                out.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARNING: skipping malformed line {n} in ledger", file=sys.stderr)
    return out


def append(row):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


if __name__ == "__main__":
    main()
