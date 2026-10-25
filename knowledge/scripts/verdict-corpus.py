#!/usr/bin/env python3
"""verdict-corpus.py — export the verdict corpus (jev-replica lever 6 prep).

The endgame for "Jev at home" is a small model fine-tuned on Josh's verdicts.
That needs a corpus that doesn't exist yet: verdicts WITH reasons and the
state they were made against. This exports what we have, joined:
  queue.jsonl (decided rows) x verdict-reasons.jsonl (reason codes)
  x shadow-predictions.jsonl (what the cascade predicted blind)

Each row: {slug, ts, source, kind, evidence, work, factors, verdict, reason,
           shadow_p, shadow_urg}. The ~200 reason-coded verdicts threshold is
the viability bar for a fine-tune; below that the corpus feeds few-shot
precedent retrieval (precedent.py already consumes the same material).

  verdict-corpus.py            # write knowledge/triage/verdict-corpus.jsonl + stats
"""
from __future__ import annotations

import importlib.util
import json
import sys
from collections import Counter
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TS = _load("triage_state", "triage-state.py")

K = Path.home() / ".claude/knowledge"
Q = K / "triage/queue.jsonl"
REASONS = K / "triage/verdict-reasons.jsonl"
SHADOW = K / "triage/shadow-predictions.jsonl"
OUT = K / "triage/verdict-corpus.jsonl"
DECIDED = ("accepted", "rejected", "built", "deferred", "filed")
THRESHOLD = 200


def _load_jsonl(p):
    if not p.exists():
        return []
    out = []
    for line in p.read_text().splitlines():
        try:
            out.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return out


def main():
    rows = _load_jsonl(Q)
    reasons = {}
    for r in _load_jsonl(REASONS):
        reasons[(r.get("slug"), r.get("ts"))] = r.get("reason")
        # also index by slug alone as a fallback (latest wins)
        reasons[r.get("slug")] = r.get("reason")
    shadow = {}
    for p in _load_jsonl(SHADOW):
        cur = shadow.get(p["slug"])
        if not cur or p["ts"] > cur["ts"]:
            shadow[p["slug"]] = p

    by_slug = TS.build_index(rows)
    out = []
    for r in rows:
        if r.get("status") not in DECIDED:
            continue
        slug = r.get("slug")
        state = TS.state_block(slug, r, by_slug)
        fac = TS.factors(state, r.get("source", ""))
        sh = shadow.get(slug, {})
        out.append({
            "slug": slug, "ts": r.get("decided_ts") or r.get("ts"),
            "source": r.get("source", ""), "kind": r.get("kind", ""),
            "title": r.get("title", ""), "evidence": r.get("evidence", ""),
            "work": r.get("work", ""),
            "factors": {k: fac[k] for k in ("fresh", "covered", "mine", "candidate")},
            "verdict": r["status"],
            "reason": reasons.get((slug, r.get("decided_ts") or r.get("ts")))
                      or reasons.get(slug),
            "shadow_p": sh.get("p"), "shadow_urg": sh.get("decay_urgency"),
        })
    with OUT.open("w") as fh:
        for r in out:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    coded = [r for r in out if r["reason"]]
    print(f"corpus: {len(out)} decided verdicts -> {OUT}")
    print(f"reason-coded: {len(coded)} ({len(coded)/max(1,len(out)):.0%}) — "
          f"fine-tune threshold {THRESHOLD}: "
          f"{'MET' if len(coded) >= THRESHOLD else f'{len(coded)}/{THRESHOLD} — keep collecting'}")
    print("reason mix:", dict(Counter(r["reason"] for r in coded)))
    print("verdict mix:", dict(Counter(r["verdict"] for r in out)))


if __name__ == "__main__":
    main()
