#!/usr/bin/env python3
"""Integrity mesh — write claims with receipts to knowledge/integrity/claims.jsonl.

Usage:
  claim-submit.py --agent X --statement "..." \
      [--proof-kind jira_transition|workato_job|file_hash|api_digest --uri U] \
      [--digest D] [--postcondition-query Q] [--postcondition-result R]
  claim-submit.py backfill

A claim given a full proof (--proof-kind AND --uri) gets tier "proved"; without
--proof-* it gets tier "asserted" (second-class; reconcile.py flags asserted
claims older than 24h).

`backfill` re-emits the durable claims already living in
~/.claude/knowledge/claims/claims.jsonl as tier-"asserted" entries in
integrity/claims.jsonl (idempotent — skips claim_ids already present).

Schema (frontier CONTRACTS.md, claim receipt):
{"claim_id","ts","agent","statement",
 "proof":{"kind":"jira_transition|workato_job|file_hash|api_digest",
          "uri","fetched_at","digest","postcondition_query","postcondition_result"},
 "tier":"proved|asserted"}

Pure stdlib. JSONL append-only. Exit 0 on success, 1 on validation error.
"""
import argparse
import json
import os
import sys
import time
import uuid

KB = os.path.expanduser("~/.claude/knowledge")
LEDGER = os.path.join(KB, "integrity", "claims.jsonl")
LEGACY_CLAIMS = os.path.join(KB, "claims", "claims.jsonl")
PROOF_KINDS = ("jira_transition", "workato_job", "file_hash", "api_digest")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append(line):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(line) + "\n")


def existing_ids():
    if not os.path.exists(LEDGER):
        return set()
    ids = set()
    with open(LEDGER) as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                ids.add(json.loads(ln).get("claim_id"))
            except json.JSONDecodeError:
                pass
    return ids


def submit(args):
    if args.proof_kind and not args.uri:
        sys.exit("--proof-kind requires --uri (a proof without a receipt uri is not a receipt)")
    if args.uri and not args.proof_kind:
        sys.exit("--uri requires --proof-kind")
    if args.proof_kind and args.proof_kind not in PROOF_KINDS:
        sys.exit(f"--proof-kind must be one of {', '.join(PROOF_KINDS)}")

    proved = bool(args.proof_kind)
    line = {
        "claim_id": f"clm-{uuid.uuid4().hex[:8]}",
        "ts": now_iso(),
        "agent": args.agent,
        "statement": args.statement,
        "tier": "proved" if proved else "asserted",
    }
    if proved:
        line["proof"] = {
            "kind": args.proof_kind,
            "uri": args.uri,
            "fetched_at": now_iso(),
            "digest": args.digest,
            "postcondition_query": args.postcondition_query,
            "postcondition_result": args.postcondition_result,
        }
    append(line)
    tier = line["tier"]
    print(f"OK  {line['claim_id']}  tier={tier}")
    print(f"    {args.statement[:120]}")
    print(f"    -> {LEDGER}")
    if tier == "asserted":
        print("    note: asserted claims are second-class; reconcile.py flags them after 24h")
    return 0


def backfill():
    if not os.path.exists(LEGACY_CLAIMS):
        sys.exit(f"no legacy claim file at {LEGACY_CLAIMS}")
    seen = existing_ids()
    written = skipped = 0
    with open(LEGACY_CLAIMS) as f:
        for ln in f:
            ln = ln.strip()
            if not ln:
                continue
            try:
                old = json.loads(ln)
            except json.JSONDecodeError as e:
                print(f"WARN skipping malformed legacy line: {e}", file=sys.stderr)
                continue
            cid = old.get("id")
            if cid in seen:
                skipped += 1
                continue
            asserted = old.get("asserted_at", "")
            ts = asserted if "T" in asserted else (asserted + "T00:00:00Z" if asserted else now_iso())
            line = {
                "claim_id": cid,
                "ts": ts,
                "agent": "claims-ledger (backfill)",
                "statement": f"{old.get('subject', 'unspecified')}: {old.get('claim', '')}",
                "tier": "asserted",
                "legacy_status": old.get("status"),
                "legacy_confidence": old.get("confidence"),
                "legacy_last_verified": old.get("last_verified"),
                "backfill_source": "knowledge/claims/claims.jsonl",
            }
            append(line)
            seen.add(cid)
            written += 1
    print(f"backfill: {written} written, {skipped} already present -> {LEDGER}")
    return 0


def main():
    if len(sys.argv) > 1 and sys.argv[1] == "backfill":
        return backfill()
    ap = argparse.ArgumentParser(description="Write a claim (with optional proof receipt) to the integrity mesh.")
    ap.add_argument("--agent", required=True, help="agent or session making the claim")
    ap.add_argument("--statement", required=True, help="the assertion, one sentence")
    ap.add_argument("--proof-kind", choices=PROOF_KINDS, help="proof type; omit for tier=asserted")
    ap.add_argument("--uri", help="proof location (job ref, URL, file path)")
    ap.add_argument("--digest", help="hash or API digest of the proof")
    ap.add_argument("--postcondition-query", help="how to re-check this claim later")
    ap.add_argument("--postcondition-result", help="what the postcondition check returned at submit time")
    args = ap.parse_args()
    return submit(args)


if __name__ == "__main__":
    sys.exit(main())
