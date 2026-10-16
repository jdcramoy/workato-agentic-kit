#!/usr/bin/env python3
"""rebuild-queue.py — regenerate triage/queue.jsonl from the immutable outcomes log.

The queue is a PROJECTION; the append-only audit log
(garden-reports/triage-outcomes.jsonl) is the source of truth. When the queue
is corrupted (2026-10-10, commit 31ac8df) or lost to a checkout -f (2026-10-11,
49 decisions), this script rebuilds the projection from the log and NEVER
touches the live queue in place.

What the outcomes log does NOT carry (known projection gaps, reported in the
drill): kind, evidence, work, points, urgency, and second-precision ts —
outcomes carry date-granularity only. Reconstructed rows use date + T00:00:00Z
and omit those fields. Open findings that were never decided have NO outcome
row and cannot be rebuilt from the log (append them again via queue-append.py).

Usage:
  rebuild-queue.py --out /tmp/rebuilt.jsonl                    # rebuild only
  rebuild-queue.py --out /tmp/rebuilt.jsonl --compare          # + live diff
  TRIAGE_OUTCOMES=... TRIAGE_QUEUE=... rebuild-queue.py ...    # custom paths
"""
import argparse
import json
import os
import sys
from collections import OrderedDict

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_write  # noqa: E402

K = os.path.join(os.path.expanduser("~"), ".claude", "knowledge")
OUTCOMES = os.environ.get("TRIAGE_OUTCOMES",
                          os.path.join(K, "garden-reports", "triage-outcomes.jsonl"))
QUEUE = os.environ.get("TRIAGE_QUEUE", os.path.join(K, "triage", "queue.jsonl"))

# outcome action -> queue status. log_outcome appends the MAPPED result
# status ("built", "filed", ...); the verb forms are kept as a legacy fallback
# so both generations of the log rebuild cleanly.
ACTION_STATUS = {
    "accept": "accepted", "reject": "rejected", "defer": "deferred",
    "build": "built", "filed": "filed",
    "accepted": "accepted", "built": "built",
    "rejected": "rejected", "deferred": "deferred",
}


def load_jsonl(path):
    rows = []
    with open(path) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError as e:
                sys.exit(f"{path}:{n}: unparsable line ({e}) — this is the "
                         f"corruption class rebuild-queue exists for; the log "
                         f"itself must never be hand-edited")
    return rows


def rebuild(outcomes_rows):
    """Last decision per slug wins; first-seen order preserved."""
    by_slug: "OrderedDict[str, dict]" = OrderedDict()
    for row in outcomes_rows:
        slug = row.get("slug", "")
        if not slug:
            continue
        date = row.get("date", "")
        status = ACTION_STATUS.get(row.get("action", ""))
        if status is None:
            continue  # unknown action — leave to the drill report, don't guess
        prior = by_slug.get(slug, {})
        by_slug[slug] = {
            "slug": slug,
            "status": status,
            "source": row.get("source", ""),
            "title": row.get("finding", ""),
            "note": row.get("notes", ""),
            "jira": row.get("jira", "") or prior.get("jira", ""),
            # date-granularity reconstruction (the log carries no clock time)
            "ts": (prior.get("ts") or (date + "T00:00:00Z" if date else "")),
            "decided_ts": (date + "T00:00:00Z" if date else ""),
            "_reconstructed": True,
        }
    return list(by_slug.values())


def compare(built, live_rows):
    live_by_slug = {}
    for r in live_rows:
        live_by_slug.setdefault(r.get("slug", ""), []).append(r)
    built_slugs = {r["slug"] for r in built}
    live_slugs = set(live_by_slug)
    report = {
        "live_rows": len(live_rows),
        "built_rows": len(built),
        "in_live_only_never_decided": sorted(live_slugs - built_slugs),
        "in_built_only": sorted(built_slugs - live_slugs),
        "differing_slugs": [],
    }
    def norm(v):
        return None if v in (None, "") else v

    for r in built:
        for lrow in live_by_slug.get(r["slug"], []):
            diffs = {k: {"rebuilt": r.get(k), "live": lrow.get(k)}
                     for k in ("status", "note", "jira")
                     if norm(r.get(k)) != norm(lrow.get(k))}
            if diffs:
                report["differing_slugs"].append({"slug": r["slug"], "diffs": diffs})
    return report


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--out", required=True,
                    help="where the rebuilt projection goes (NEVER the live queue)")
    ap.add_argument("--compare", action="store_true",
                    help="also diff the projection against the live queue")
    a = ap.parse_args()

    out_abs = os.path.abspath(a.out)
    if os.path.abspath(QUEUE) == out_abs:
        sys.exit(f"refusing to write the live queue in place ({out_abs}) — "
                 f"the drill path is: write to scratch, diff, then swap with "
                 f"Josh's eyes on it")
    if not os.path.exists(OUTCOMES):
        sys.exit(f"no outcomes log at {OUTCOMES}")

    outcomes = load_jsonl(OUTCOMES)
    built = rebuild(outcomes)
    atomic_write(out_abs, "".join(json.dumps(r, ensure_ascii=False) + "\n"
                                  for r in built))
    print(f"rebuilt {len(built)} rows from {len(outcomes)} outcome rows -> {out_abs}")

    if a.compare:
        live = load_jsonl(QUEUE)
        rep = compare(built, live)
        print(f"live queue: {rep['live_rows']} rows | rebuilt: {rep['built_rows']} rows")
        print(f"never-decided open rows in live only "
              f"({len(rep['in_live_only_never_decided'])}): "
              + (", ".join(rep["in_live_only_never_decided"]) or "none"))
        print(f"rebuilt-only slugs ({len(rep['in_built_only'])}): "
              + (", ".join(rep["in_built_only"]) or "none"))
        print(f"status/note/jira differing rows ({len(rep['differing_slugs'])}):")
        for d in rep["differing_slugs"]:
            print(f"  {d['slug']}: {json.dumps(d['diffs'], ensure_ascii=False)}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
