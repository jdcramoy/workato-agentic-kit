#!/usr/bin/env python3
"""backfill-reasons.py — reason-code the historical verdict ledger (lever 3).

Writes verdict-reasons.jsonl rows for DECIDED queue rows whose note/text
confidently implies a canonical reason. Conservative: no confident match, no
row. Idempotent: (slug, decided_ts) already in the ledger is skipped.

  backfill-reasons.py          # append backfill rows
  backfill-reasons.py --dry    # print what would be written
"""
from __future__ import annotations

import json
import re
import sys
from pathlib import Path

Q = Path.home() / ".claude/knowledge/triage/queue.jsonl"
OUT = Path.home() / ".claude/knowledge/triage/verdict-reasons.jsonl"

# ordered: first match wins; patterns aim for precision, not recall
RULES = [
    ("stale", re.compile(r"\b(superseded|stale|re-?report|no longer|moot|already handled)\b", re.I)),
    ("covered", re.compile(r"\b(covered by|fix filed|filed (as|to)|tracked (in|by)|dup(licate)? of)\b", re.I)),
    ("done", re.compile(r"\b(already (done|built|fixed|shipped|verified|landed)|is done|completed)\b", re.I)),
    ("not-mine", re.compile(r"\b(not (mine|josh'?s)|another (lane|team|agent)|wrong (team|queue)|someone else)\b", re.I)),
    ("not-valuable", re.compile(r"\b(not valuable|no (real )?value|noise|not worth|low[- ]value|cosmetic only)\b", re.I)),
    ("cheap-win", re.compile(r"\b(cheap|quick win|one[- ]liner|trivial)\b", re.I)),
    ("blocks-other", re.compile(r"\b(block(s|ing|ed)|unblock|critical path)\b", re.I)),
]
DECIDED = ("accepted", "rejected", "built", "deferred", "filed")

# polarity gate: reject-side reasons never tag accept-side verdicts and vice
# versa — a BUILT row whose note mentions "stale FTO doc" is describing the
# FINDING's subject, not the verdict's reason.
NEGATIVE = {"stale", "covered", "not-mine", "done", "not-valuable"}
POSITIVE = {"valuable", "cheap-win", "blocks-other"}
VERDICT_SIDE = {"rejected": NEGATIVE, "deferred": NEGATIVE | {"blocks-other"},
                "accepted": POSITIVE, "built": POSITIVE, "filed": POSITIVE}


def classify(note, status):
    if not note or not note.strip():
        return None
    allowed = VERDICT_SIDE.get(status, set())
    for code, rx in RULES:
        if code in allowed and rx.search(note):
            return code
    return None


def main():
    dry = "--dry" in sys.argv
    existing = set()
    if OUT.exists():
        for line in OUT.read_text().splitlines():
            try:
                r = json.loads(line)
                existing.add((r.get("slug"), r.get("ts") or r.get("decided_ts")))
            except json.JSONDecodeError:
                pass
    written = skipped = unmatched = 0
    fh = None if dry else OUT.open("a")
    for line in Q.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("status") not in DECIDED:
            continue
        # the REASON lives in the decision note; the title is the finding's
        # own self-description and must not be matched
        code = classify(str(r.get("note") or ""), r["status"])
        if not code:
            unmatched += 1
            continue
        key = (r.get("slug"), r.get("decided_ts") or r.get("ts"))
        if key in existing:
            skipped += 1
            continue
        rec = {"ts": r.get("decided_ts") or r.get("ts"), "slug": r.get("slug"),
               "action": r["status"], "reason": code, "note": (r.get("note") or "")[:200],
               "reason_source": "backfill-rule", "by": "backfill-reasons.py"}
        if dry:
            print(f"  {r['status']:9s} {code:12s} {r.get('slug','')[:50]} | {(r.get('note') or '')[:60]}")
        else:
            fh.write(json.dumps(rec, ensure_ascii=False) + "\n")
        existing.add(key)
        written += 1
    if fh:
        fh.close()
    print(f"{'DRY: would write' if dry else 'wrote'} {written} rows "
          f"({skipped} already present, {unmatched} no confident match) "
          f"-> {OUT}")


if __name__ == "__main__":
    main()
