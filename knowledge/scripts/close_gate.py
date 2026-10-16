#!/usr/bin/env python3
"""close_gate.py — the failure close-gate mechanism (skill: failure-close-gate).

Contract (proposal 2026-10-10-failure-close-gate, accepted): a run may mark a
finding fixed/accepted ONLY if, in the SAME run, it updates the durable
record. Detection without persistence is the disease this gate exists for
(prod 82090477 re-alerted 5+ times post-resolution; accepted regression
verdicts never reaching the canon).

Subcommands:
  canon   --recipe <id> --signature <sig> --status tested --evidence "<job/trace>"
  triage  --slug <slug> --status fixed|accepted|built --evidence "<...>"
  sweep   --days 3 [--post]   # N-day escalation: flag unclosed records, route to queue

Exit codes (the gate):
  0  closed (or already closed — idempotent)
  3  REFUSED — no matching durable record was updated, so the verdict may
     NOT be recorded as closed anywhere else. The calling run must leave the
     finding open/re-alerting.
  4  bad usage

All writes take the record's own <path>.lock flock, same discipline as
workato-health.triage_append and triage-decide.py.
"""

import argparse
import datetime as dt
import fcntl
import json
import os
import sys

K = os.path.expanduser("~/.claude/knowledge")
CANON = os.path.join(K, "regression-canon", "canon.jsonl")
QUEUE = os.path.join(K, "triage", "queue.jsonl")

E_OK, E_REFUSED, E_USAGE = 0, 3, 4


def _now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _locked_update(path, matcher, mutator, record_label):
    """Find the first record matching matcher(row) under flock, apply
    mutator(row) in place, rewrite the file. Returns (found, already)."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path + ".lock", "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                with open(path, "r", encoding="utf-8") as fh:
                    raw = fh.read().splitlines(keepends=True)
            except FileNotFoundError:
                print(f"REFUSED: {record_label} does not exist ({path})", file=sys.stderr)
                return False, False
            out, found, already = [], False, False
            for line in raw:
                if not line.strip():
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    out.append(line)
                    continue
                if not found and matcher(row):
                    if row.get("status") == mutator["status"]:
                        found, already = True, True
                        out.append(line)
                        continue
                    row["status"] = mutator["status"]
                    row["closed_ts"] = _now_iso()
                    row["close_evidence"] = mutator["evidence"]
                    found = True
                    out.append(json.dumps(row) + "\n")
                else:
                    out.append(line)
            if found and not already:
                with open(path, "w", encoding="utf-8") as fh:
                    fh.writelines(out)
            return found, already
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def close_canon(args):
    label = f"canon entry {args.recipe}:{args.signature}"

    def match(row):
        return (str(row.get("recipe_id")) == str(args.recipe)
                and row.get("signature") == args.signature)

    found, already = _locked_update(
        CANON, match,
        {"status": args.status, "evidence": args.evidence}, label)
    if not found:
        print(f"REFUSED: no {label} in {CANON} — the close-gate will not record "
              f"this verdict; the canon entry must be seeded/created first "
              f"(regression-nightly.py auto-seeds on detection).", file=sys.stderr)
        return E_REFUSED
    print(("already " if already else "closed ") + label
          + f" -> {args.status} (evidence: {args.evidence})")
    return E_OK


def close_triage(args):
    label = f"triage card {args.slug}"
    row_state = {}

    def match(row):
        if row.get("slug") != args.slug:
            return False
        row_state["status"] = row.get("status")
        return row.get("status") == "open"

    found, already = _locked_update(
        QUEUE, match,
        {"status": args.status, "evidence": args.evidence}, label)
    if already:
        print(f"already {label} -> {args.status}")
        return E_OK
    if found:
        print(f"closed {label} -> {args.status} (evidence: {args.evidence})")
        return E_OK
    if row_state.get("status"):
        print(f"REFUSED: {label} exists but status is '{row_state['status']}', "
              f"not open — re-alerting is correct behavior, not a dedupe bug.",
              file=sys.stderr)
        return E_REFUSED
    print(f"REFUSED: no {label} in {QUEUE} — closing a finding that was never "
          f"durably recorded is the orphan pattern this gate forbids.",
          file=sys.stderr)
    return E_REFUSED


def _age_days(ts_or_date):
    try:
        if "T" in str(ts_or_date):
            t = dt.datetime.fromisoformat(str(ts_or_date).replace("Z", "+00:00"))
            return (dt.datetime.now(dt.timezone.utc) - t).total_seconds() / 86400
        return (dt.date.today() - dt.date.fromisoformat(str(ts_or_date))).days
    except (ValueError, TypeError):
        return 0.0


def sweep(args):
    """N-day escalation: unclosed records older than --days get routed to the
    triage queue with a needs-owner escalation row (dedupe-aware), NOT a
    repeat of the original alert."""
    cutoff = float(args.days)
    stale = []
    try:
        for line in open(CANON, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if r.get("status") != "tested" and _age_days(r.get("found")) > cutoff:
                stale.append({
                    "record": "canon", "key": f"{r.get('recipe_id')}:{r.get('signature')}",
                    "age_days": round(_age_days(r.get("found")), 1),
                    "title": (r.get("line") or "")[:120],
                })
    except FileNotFoundError:
        pass
    try:
        for line in open(QUEUE, encoding="utf-8"):
            if not line.strip():
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            if (r.get("status") == "open"
                    and not str(r.get("slug", "")).startswith("close-gate-escalation-")
                    and _age_days(r.get("ts")) > cutoff):
                stale.append({
                    "record": "triage", "key": r.get("slug"),
                    "age_days": round(_age_days(r.get("ts")), 1),
                    "title": (r.get("title") or "")[:120],
                })
    except FileNotFoundError:
        pass

    stale.sort(key=lambda s: -s["age_days"])
    if not stale:
        print(f"close-gate sweep: nothing unclosed beyond {cutoff} days")
        return E_OK
    print(f"close-gate sweep: {len(stale)} record(s) unclosed > {cutoff} days:")
    for s in stale:
        print(f"  [{s['record']}] {s['key']} — {s['age_days']}d — {s['title']}")
    if args.post:
        posted = 0
        for s in stale:
            slug = f"close-gate-escalation-{s['record']}-{s['key']}"
            found, _al = _locked_update(
                QUEUE,
                lambda row, _s=slug: row.get("slug") == _s and row.get("status") == "open",
                {"status": "open", "evidence": "close-gate sweep"},
                f"escalation {slug}")
            if not found:
                row = {
                    "slug": slug, "kind": "close-gate-escalation",
                    "source": "failure-close-gate",
                    "title": f"UNCLOSED {s['age_days']}d ({s['record']}): {s['key']} — needs a named owner",
                    "evidence": f"{s['title']}",
                    "work": f"close or disposition the {s['record']} record '{s['key']}' via close_gate.py; assign an owner",
                    "status": "open", "ts": _now_iso(),
                }
                with open(QUEUE + ".lock", "w") as lock:
                    fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
                    try:
                        with open(QUEUE, "a", encoding="utf-8") as fh:
                            fh.write(json.dumps(row) + "\n")
                    finally:
                        fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
                posted += 1
        print(f"routed {posted} escalation row(s) to {QUEUE}")
    else:
        print("(dry run — pass --post to route escalation rows to the triage queue)")
    return E_OK


def main():
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    sub = p.add_subparsers(dest="cmd", required=True)

    pc = sub.add_parser("canon")
    pc.add_argument("--recipe", required=True)
    pc.add_argument("--signature", required=True)
    pc.add_argument("--status", required=True, choices=["tested", "closed"])
    pc.add_argument("--evidence", required=True)
    pc.set_defaults(fn=close_canon)

    pt = sub.add_parser("triage")
    pt.add_argument("--slug", required=True)
    pt.add_argument("--status", required=True, choices=["fixed", "accepted", "built"])
    pt.add_argument("--evidence", required=True)
    pt.set_defaults(fn=close_triage)

    ps = sub.add_parser("sweep")
    ps.add_argument("--days", type=int, default=3)
    ps.add_argument("--post", action="store_true")
    ps.set_defaults(fn=sweep)

    args = p.parse_args()
    sys.exit(args.fn(args))


if __name__ == "__main__":
    main()
