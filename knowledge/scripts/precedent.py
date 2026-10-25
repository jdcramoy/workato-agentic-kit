#!/usr/bin/env python3
"""precedent.py — k-nearest past verdicts for a finding (jev-replica lever 2).

The 2026-10-23 backtests showed text-identical rows with opposite labels
(Josh's reason lives outside the payload). Precedents close that gap: show the
judge the nearest DECIDED findings with their verdicts and Josh's own notes.
This is the piece a licensed judge model structurally lacks — no memory of
Josh's verdicts.

BM25 over title+evidence+work tokens, stdlib only (n is ~hundreds; fancy is
waste). Leak-free: precedents are filtered to rows decided BEFORE the query
row's as_of timestamp (verdict time in backtests, now() for live cards).

  from precedent import PrecedentIndex
  idx = PrecedentIndex(queue_rows)
  hits = idx.query(row_text, exclude_slug=slug, as_of=T, k=3)
  text = PrecedentIndex.render(hits)   # judge-ready block
"""
from __future__ import annotations

import math
import re
from collections import Counter

STOP = set("""a an and are as at be been but by for from had has have how if in
into is it its of on or so that the this to was what when which who will with
would should could not no new now do does done fix fixed work working use using
per then than when while where who why how josh claude knowledge scripts""".split())

TOKEN_RE = re.compile(r"[a-z0-9]{2,}")

DECIDED = ("accepted", "rejected", "built", "deferred", "filed")


def _tokens(text):
    return [t for t in TOKEN_RE.findall((text or "").lower()) if t not in STOP]


def _row_text(r):
    return " ".join(str(r.get(k, "")) for k in ("slug", "title", "evidence", "work"))


def _t(row):
    return row.get("decided_ts") or row.get("ts") or ""


class PrecedentIndex:
    def __init__(self, rows, k1=1.2, b=0.75):
        """rows: raw queue.jsonl dicts (all statuses; only decided rows index)."""
        self.k1, self.b = k1, b
        self.docs = []  # (slug, status, note, decided_ts, token_counts, dl)
        df = Counter()
        for r in rows:
            if r.get("status") not in DECIDED:
                continue
            tc = Counter(_tokens(_row_text(r)))
            if not tc:
                continue
            self.docs.append({"slug": r.get("slug", ""), "status": r["status"],
                              "note": (r.get("note") or "")[:200],
                              "t": _t(r), "tf": tc, "dl": sum(tc.values())})
            for tok in tc:
                df[tok] += 1
        n = len(self.docs)
        self.idf = {t: math.log(1 + (n - c + 0.5) / (c + 0.5))
                    for t, c in df.items()}
        self.avdl = sum(d["dl"] for d in self.docs) / n if n else 1.0

    def query(self, text, exclude_slug=None, as_of=None, k=3):
        q_tf = Counter(_tokens(text))
        out = []
        for d in self.docs:
            if exclude_slug and d["slug"] == exclude_slug:
                continue
            if as_of and d["t"] and d["t"] >= as_of:
                continue  # decided after the query's decision time = future info
            score = 0.0
            for tok, qf in q_tf.items():
                tf = d["tf"].get(tok, 0)
                if not tf:
                    continue
                idf = self.idf.get(tok, 0.0)
                score += idf * (tf * (self.k1 + 1)) / (
                    tf + self.k1 * (1 - self.b + self.b * d["dl"] / self.avdl))
            if score > 0:
                out.append((score, d))
        out.sort(key=lambda x: -x[0])
        return [{"slug": d["slug"], "status": d["status"], "note": d["note"],
                 "score": round(s, 2)} for s, d in out[:k]]

    @staticmethod
    def render(hits):
        if not hits:
            return ""
        lines = ["PAST VERDICTS on similar findings (Josh's actual decisions):"]
        for h in hits:
            note = f" — \"{h['note']}\"" if h["note"] else ""
            lines.append(f"- {h['slug']}: {h['status'].upper()}{note}")
        return "\n".join(lines)


if __name__ == "__main__":
    import json
    import sys
    from pathlib import Path
    rows = [json.loads(l) for l in
            Path.home().joinpath(".claude/knowledge/triage/queue.jsonl")
            .read_text().splitlines() if l.strip()]
    idx = PrecedentIndex(rows)
    print(f"index: {len(idx.docs)} decided rows")
    if len(sys.argv) > 1:
        slug = sys.argv[1]
        row = next((r for r in rows if r.get("slug") == slug), None)
        if row:
            print(PrecedentIndex.render(idx.query(_row_text(row),
                                                  exclude_slug=slug,
                                                  as_of=_t(row) or None)))
