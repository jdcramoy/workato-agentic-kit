#!/usr/bin/env python3
"""patch-genome.py — lineage ledger for every patch to the instruction surface.

Wave-3 amendment 4 scope: SHIP THE LEDGER ONLY. This records patch lineage
(id, ts, parent, target files, source) into knowledge/patches/patch-genome.jsonl
and reads it back. Clause re-earning, recombination, and prompt rewriting are
DEFERRED until a clause->oracle registry exists — this script does none of that
and never edits a prompt.

Fitness attribution for ratchet-watch is PER-TARGET-FILE, never a per-agent
blend: each genome row carries an explicit targets list.

Sources:
  instruction-patch  instruction-patch.py applier (queue-approved one-liners)
  triage-decide      triage-decide.py build dispatches
  manual             Josh-directed edits
  dreamer            harness-dreamer proposals that landed
  other              anything else (be specific in --note)

Usage:
  python3 patch-genome.py record --target FILE [--target FILE2 ...]
      [--parent <id>] [--source instruction-patch|triage-decide|manual|dreamer|other]
      [--note "..."] [--origin-slug <slug>]
  python3 patch-genome.py backfill            # seed genome from the existing
                                              # instruction-patches/applied.jsonl
  python3 patch-genome.py show [--id <id>]    # rows, or one row + descendants
  python3 patch-genome.py --selftest
"""

import argparse
import json
import os
import sys
from datetime import datetime, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from atomic_io import (  # noqa: E402  (read-only reuse per CONTRACTS)
    SchemaViolation, atomic_append_validated, validate_row,
)

K = os.path.join(os.path.expanduser("~"), ".claude", "knowledge")
GENOME = os.path.join(K, "patches", "patch-genome.jsonl")
APPLIED = os.path.join(K, "instruction-patches", "applied.jsonl")

SOURCES = ("instruction-patch", "triage-decide", "manual", "dreamer", "other")

SCHEMA = {
    "required": ["id", "ts", "targets", "source"],
    "enums": {"source": set(SOURCES)},
    "timestamps": ["ts"],
}


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                rows.append(json.loads(ln))
            except json.JSONDecodeError:
                print(f"WARN: skipping malformed line in {path}: {ln[:80]}",
                      file=sys.stderr)
    return rows


def next_id(rows):
    n = 0
    for r in rows:
        rid = str(r.get("id", ""))
        if rid.startswith("pg-"):
            try:
                n = max(n, int(rid[3:]))
            except ValueError:
                pass
    return f"pg-{n + 1:04d}"


def cmd_record(args):
    rows = load_jsonl(GENOME)
    targets = [os.path.expanduser(t) for t in (args.target or [])]
    if not targets:
        print("ERROR: at least one --target is required (per-target-file "
              "attribution needs an explicit file list)", file=sys.stderr)
        return 2
    rec = {
        "id": args.id or next_id(rows),
        "ts": now_iso(),
        "parent": args.parent,
        "targets": targets,
        "source": args.source,
        "origin_slug": args.origin_slug,
        "note": args.note,
    }
    if any(r.get("id") == rec["id"] for r in rows):
        print(f"ERROR: id {rec['id']} already in genome — pass a new --id",
              file=sys.stderr)
        return 2
    try:
        atomic_append_validated(GENOME, rec, SCHEMA)
    except SchemaViolation as e:
        print(f"ERROR: {e}", file=sys.stderr)
        return 2
    print(f"recorded: {rec['id']} ts={rec['ts']} source={rec['source']} "
          f"targets={len(targets)}")
    return 0


def cmd_backfill(args):
    """Seed the genome from instruction-patches/applied.jsonl (amendment:
    backfill over the EXISTING applied log). Idempotent — a row already
    backfilled (same origin_slug + ts) is skipped."""
    applied = load_jsonl(APPLIED)
    if not applied:
        print(f"backfill: applied log {APPLIED} is empty (0 rows) — nothing "
              f"to seed; future applier writes are recorded via record "
              f"--source instruction-patch")
        return 0
    genome = load_jsonl(GENOME)
    seen = {(r.get("origin_slug"), r.get("origin_ts")) for r in genome}
    added = skipped = 0
    for a in applied:
        key = (a.get("slug"), a.get("ts"))
        if key in seen:
            skipped += 1
            continue
        rec = {
            "id": next_id(genome),
            "ts": a.get("ts") or now_iso(),
            "parent": None,
            "targets": [a["target"]] if a.get("target") else [],
            "source": "instruction-patch",
            "origin_slug": a.get("slug"),
            "origin_ts": a.get("ts"),
            "note": a.get("diff_note"),
        }
        errs = validate_row(rec, SCHEMA)
        if errs:
            print(f"WARN: skipping applied row (bad schema: {'; '.join(errs)})",
                  file=sys.stderr)
            continue
        atomic_append_validated(GENOME, rec, SCHEMA)
        genome.append(rec)
        added += 1
    print(f"backfill: added={added} skipped_existing={skipped} "
          f"source_rows={len(applied)}")
    return 0


def cmd_show(args):
    rows = load_jsonl(GENOME)
    if args.id:
        row = next((r for r in rows if r.get("id") == args.id), None)
        if not row:
            print(f"ERROR: no genome row with id {args.id}", file=sys.stderr)
            return 2
        kids = [r for r in rows if r.get("parent") == args.id]
        print(json.dumps({"row": row, "children": kids}, indent=1))
        return 0
    print(f"genome: {len(rows)} patch(es)")
    for r in rows:
        print(f"  {r['id']}  {r.get('ts', '?')}  src={r.get('source')}  "
              f"targets={len(r.get('targets') or [])}  "
              f"slug={r.get('origin_slug')}")
    return 0


def cmd_selftest(_args):
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        g = os.path.join(td, "genome.jsonl")
        global GENOME
        real_genome, GENOME = GENOME, g
        try:
            assert cmd_record(argnamespace(
                id=None, parent=None, target=["/tmp/a.md"], source="manual",
                note="t1", origin_slug=None)) == 0
            assert cmd_record(argnamespace(
                id=None, parent="pg-0001", target=["/tmp/b.md"],
                source="dreamer", note="t2", origin_slug="s-1")) == 0
            rows = load_jsonl(g)
            assert len(rows) == 2, rows
            assert rows[0]["id"] == "pg-0001" and rows[1]["parent"] == "pg-0001"
            # lineage
            import io, contextlib
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                assert cmd_show(argnamespace(id="pg-0001")) == 0
            assert '"parent": "pg-0001"' in buf.getvalue()
            # schema gate: bad source refused, nothing written
            rc = cmd_record(argnamespace(
                id=None, parent=None, target=["/tmp/c.md"], source="bogus",
                note=None, origin_slug=None))
            assert rc == 2 and len(load_jsonl(g)) == 2, "schema gate failed"
            # backfill idempotence on a synthetic applied log
            applied_rows = [{"ts": "2026-10-10T00:00:00Z", "slug": "s-1",
                             "target": "/tmp/b.md", "applied": True,
                             "diff_note": "x"},
                            {"ts": "2026-10-11T00:00:00Z", "slug": "s-2",
                             "target": "/tmp/d.md", "applied": True,
                             "diff_note": "y"}]
            ap = os.path.join(td, "applied.jsonl")
            with open(ap, "w") as f:
                for r in applied_rows:
                    f.write(json.dumps(r) + "\n")
            global APPLIED
            real_applied, APPLIED = APPLIED, ap
            assert cmd_backfill(None) == 0
            n1 = len(load_jsonl(g))
            assert cmd_backfill(None) == 0  # second pass = no dupes
            n2 = len(load_jsonl(g))
            assert n2 == n1, f"backfill not idempotent: {n1} vs {n2}"
        finally:
            GENOME, APPLIED = real_genome, real_applied
    print("selftest: PASS (record/id-sequence/lineage/schema-gate/backfill/"
          "backfill-idempotence)")
    return 0


def argnamespace(**kw):
    return argparse.Namespace(**kw)


def main():
    ap = argparse.ArgumentParser(
        description="Patch lineage ledger (wave-3 amendment 4: ledger + "
                    "backfill only — no clause re-earning, no prompt editing)")
    ap.add_argument("--selftest", action="store_true",
                    help="run the synthetic-data self test and exit")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("record", help="record one patch into the genome")
    p.add_argument("--target", action="append", required=True,
                   help="target file (repeatable)")
    p.add_argument("--parent", help="genome id this patch descends from")
    p.add_argument("--source", default="manual", choices=SOURCES)
    p.add_argument("--note")
    p.add_argument("--origin-slug", dest="origin_slug")
    p.add_argument("--id", help="explicit id (auto pg-NNNN by default)")
    p.set_defaults(fn=cmd_record)

    p = sub.add_parser("backfill",
                       help="seed genome from instruction-patches/applied.jsonl")
    p.set_defaults(fn=cmd_backfill)

    p = sub.add_parser("show", help="list genome rows (or one + children)")
    p.add_argument("--id")
    p.set_defaults(fn=cmd_show)

    args = ap.parse_args()
    if args.selftest:
        return cmd_selftest(None)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
