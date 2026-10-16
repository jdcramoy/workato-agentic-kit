#!/usr/bin/env python3
"""drift-gate.py — memory-vs-world alignment check for the claim ledger.

The entropy report (kb.dream_entropy) measures the memory's internal STATE
(redundancy, contradiction, decay, dispersion). This gate measures the other
axis: does each active claim still match what the GROUND TRUTH (Workato docs
corpus in the kb vector store) says? Catches semantic drift — agent-written
claims slowly diverging from the documented platform across generations.

For every active claim:
  1. Retrieve top-k passages from the kb (BM25 + vector + rerank).
  2. Classify:
     doc-supported  - strong top rerank (>= 0.5); gardener confirms entailment
     weak-support   - hits exist but weak (< 0.5) — gardener adjudicates first
     no-source      - nothing meaningful in docs (platform-behavior claims);
                      NOT drift — route to claim-verification's live probe
Output: human digest on stdout + one history line per claim appended to
garden-reports/drift-gate.jsonl (trend: is alignment improving or rotting?).

The gardener's Phase 2.5 runs this, then adjudicates weak-support rows by
reading the cited kb docs (kb.read <doc_id>) — a rerank score cannot say
"contradicted", only the entailment read can. Advisory; proposes, never edits.

    python3 ~/.claude/knowledge/scripts/drift-gate.py [--k 3] [--source docs]
"""
import argparse
import datetime as dt
import json
import sys
import time
from pathlib import Path

K = Path.home() / ".claude/knowledge"
CLAIMS = K / "claims/claims.jsonl"
HISTORY = K / "garden-reports/drift-gate.jsonl"
KB = Path.home() / "Documents/workato-kb"
WEAK_RERANK = 0.5  # same weak line kb.search's own uncertainty gate uses


def load_active_claims():
    if not CLAIMS.exists():
        return []
    return [json.loads(l) for l in CLAIMS.read_text().splitlines() if l.strip()
            and json.loads(l).get("status") == "active"]


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--k", type=int, default=3)
    ap.add_argument("--source", default=None,
                    help="restrict ground truth to one kb source (docs, changelog, confluence, ...)")
    args = ap.parse_args()

    sys.path.insert(0, str(KB))
    from kb.search import search  # the kb venv runs this script

    claims = load_active_claims()
    if not claims:
        print("no active claims — nothing to gate")
        return

    today = dt.date.today().isoformat()
    rows = []
    print(f"DRIFT GATE — {len(claims)} active claims vs kb ground truth "
          f"(source={args.source or 'all'})\n")
    for c in claims:
        subject, claim_text = c.get("subject", "?"), c.get("claim", "")
        cid = c.get("id", subject)
        query = f"{subject} {claim_text}".strip()
        # Concurrent KB jobs (sync, docs-watch) hold the sqlite write lock and
        # used to make this search raise "database is locked" -> the claim was
        # silently skipped, zeroing out whole evaluation runs (2026-10-12).
        # Retry with backoff so a transient lock delays, not drops, a claim.
        hits, meta = None, None
        for attempt in range(4):
            try:
                hits, meta = search(query, k=args.k, source=args.source)
                break
            except Exception as e:
                if "locked" not in str(e).lower() or attempt == 3:
                    print(f"  [{cid}] kb search FAILED after {attempt + 1} attempt(s): {e}")
                    break
                time.sleep(2 ** attempt)  # 1s, 2s, 4s
        if hits is None:
            continue

        if not hits:
            verdict = "no-source"
            top = 0.0
            top_doc = None
        else:
            top = hits[0].rerank if hits[0].rerank is not None else hits[0].final
            top_doc = hits[0].doc_id if hasattr(hits[0], "doc_id") else hits[0].chunk_id
            verdict = "doc-supported" if top >= WEAK_RERANK else "weak-support"

        rows.append({"date": today, "claim_id": cid, "subject": subject,
                     "verdict": verdict, "top_score": round(top, 3),
                     "top_doc": top_doc,
                     "confidence_bits": meta.get("confidence_bits")})
        flag = {"doc-supported": "ok", "weak-support": "?ADJUDICATE",
                "no-source": "no docs (live-probe path)"}[verdict]
        print(f"  [{flag:>22}] {subject[:38]:38} top={top:.3f} {top_doc or ''}")

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    print(f"\nverdicts: {counts}")

    HISTORY.parent.mkdir(parents=True, exist_ok=True)
    with HISTORY.open("a") as f:
        for r in rows:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")
    print(f"history appended: {len(rows)} rows -> {HISTORY}")

    adj = [r for r in rows if r["verdict"] == "weak-support"]
    if adj:
        print("\nadjudication queue (gardener: kb.read each doc, judge entailment):")
        for r in adj:
            print(f"  - {r['claim_id']}: {r['subject']} vs {r['top_doc']}")


if __name__ == "__main__":
    main()
