#!/usr/bin/env python3
"""Integrity mesh — write claims with receipts to knowledge/claims/claims.jsonl.

2026-10-22 (triage: dual-claims-ledger-merge + claims-ledger-id-collision):
this recorder used to write a SECOND ledger at integrity/claims.jsonl that
drift-gate could not see, and it minted random uuid IDs. It now appends to the
single canonical ledger (claims/claims.jsonl) in the canonical claim schema,
allocating sequential clm-NNN IDs with a uniqueness guard (scan existing max,
increment — the clm-014 duplicate class can never recur).

Usage:
  claim-submit.py --agent X --statement "..." \
      [--proof-kind jira_transition|workato_job|file_hash|api_digest --uri U] \
      [--digest D] [--postcondition-query Q] [--postcondition-result R]
  claim-submit.py backfill

A claim given a full proof (--proof-kind AND --uri) gets tier "proved"; without
--proof-* it gets tier "asserted" (second-class; reconcile.py flags asserted
claims older than 24h).

`backfill` re-emits the durable claims from the RETIRED ledgers
(integrity/claims.jsonl.merged-2026-10-22) as tier-"asserted" canonical rows
(idempotent — skips ids already present).

Schema (canonical, claims/claims.jsonl + receipt extras):
{"id":"clm-NNN","subject","claim",
 "evidence":[{"type","ref"}],
 "confidence","asserted_at","last_verified","status",
 "agent","ts","tier":"proved|asserted",
 "proof":{"kind":"jira_transition|workato_job|file_hash|api_digest",
          "uri","fetched_at","digest","postcondition_query","postcondition_result"}}

Pure stdlib. JSONL append-only. Exit 0 on success, 1 on validation error.
"""
import argparse
import json
import os
import re
import sys
import time

KB = os.path.expanduser("~/.claude/knowledge")
LEDGER = os.path.join(KB, "claims", "claims.jsonl")
LEGACY_CLAIMS = os.path.join(KB, "integrity", "claims.jsonl.merged-2026-10-22")
PROOF_KINDS = ("jira_transition", "workato_job", "file_hash", "api_digest")


def now_iso():
    return time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())


def append(line):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    with open(LEDGER, "a") as f:
        f.write(json.dumps(line) + "\n")


def next_claim_id():
    """Sequential clm-NNN allocator: scan the ledger for the highest NNN and
    increment. Guards the 2026-10-21 clm-014 duplicate-ID class: if the minted
    id somehow already exists (concurrent writer), keep incrementing."""
    n = 0
    for cid in existing_ids():
        m = re.match(r"^clm-(\d+)$", str(cid or ""))
        if m:
            n = max(n, int(m.group(1)))
    while True:
        n += 1
        candidate = f"clm-{n:03d}"
        if candidate not in existing_ids():
            return candidate


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
                row = json.loads(ln)
                ids.add(row.get("id") or row.get("claim_id"))
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
    cid = next_claim_id()
    # subject = the text before the first colon when it reads like a kebab/
    # short subject; otherwise a truncated statement slug.
    stmt = args.statement.strip()
    subject = None
    if ":" in stmt:
        head = stmt.split(":", 1)[0].strip()
        if 0 < len(head) <= 60 and " " not in head:
            subject = head.lower()
    if not subject:
        subject = re.sub(r"[^a-z0-9]+", "-", stmt.lower()).strip("-")[:60]
    line = {
        "id": cid,
        "subject": subject,
        "claim": stmt,
        "evidence": [],
        "confidence": "high" if proved else "medium",
        "asserted_at": now_iso()[:10],
        "last_verified": now_iso()[:10],
        "status": "active",
        "agent": args.agent,
        "ts": now_iso(),
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
        line["evidence"].append({
            "type": "live-call",
            "ref": f"{args.uri} (proof digest {(args.digest or '')[:16]})",
        })
    else:
        line["evidence"].append({"type": "rule", "ref": f"asserted by {args.agent} via claim-submit.py"})
    append(line)
    tier = line["tier"]
    print(f"OK  {cid}  tier={tier}")
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
            cid = old.get("claim_id") or old.get("id")
            if cid in seen:
                skipped += 1
                continue
            asserted = old.get("asserted_at") or (old.get("ts") or "")[:10]
            line = {
                "id": cid,
                "subject": old.get("subject", "unspecified"),
                "claim": old.get("claim") or old.get("statement", ""),
                "evidence": old.get("evidence") or [{"type": "memory", "ref": LEGACY_CLAIMS}],
                "confidence": old.get("confidence") or "medium",
                "asserted_at": asserted or now_iso()[:10],
                "last_verified": old.get("last_verified") or now_iso()[:10],
                "status": old.get("status") or "active",
                "tier": "asserted",
                "backfill_source": LEGACY_CLAIMS,
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
