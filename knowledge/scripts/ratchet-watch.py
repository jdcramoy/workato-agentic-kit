#!/usr/bin/env python3
"""ratchet-watch.py — Muller's ratchet counter for the patch genome.

Wave-3 amendment 4 scope: COUNTER + TRIP LOGIC ONLY. Counts patches added
WITHOUT a measured benefit inside the window and trips a finding when the
counter crosses the threshold. Recombination / clause re-earning is DEFERRED
(no clause->oracle registry exists) — on trip this script writes nothing and
mutates nothing; it prints the finding and exits 3 so the integrator's plist
or hook can route it.

Outcome signals consulted (all real, all read-only):
  garden-reports/proposal-outcomes.jsonl   (accepted actions)
  garden-reports/triage-outcomes.jsonl     (built/fixed/shipped actions)
  regression-canon/gym-canon.jsonl         (gym.py results, resolved rows)

Attribution is PER-TARGET-FILE: a patch counts as benefited only if a positive
signal dated on/after the patch references one of its target files (basename
match) or the patch id / origin slug. No per-agent blending.

Usage:
  python3 ratchet-watch.py [--window-days 14] [--threshold 3] [--json]
  python3 ratchet-watch.py --selftest

Exit codes: 0 = under threshold, 3 = RATCHET TRIPPED, 2 = input error.
"""

import argparse
import fnmatch
import json
import os
import sys
from datetime import datetime, timedelta, timezone

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

K = os.path.join(os.path.expanduser("~"), ".claude", "knowledge")
GENOME = os.path.join(K, "patches", "patch-genome.jsonl")
SIGNAL_SOURCES = [
    ("proposal-outcomes", os.path.join(K, "garden-reports",
                                       "proposal-outcomes.jsonl")),
    ("triage-outcomes", os.path.join(K, "garden-reports",
                                     "triage-outcomes.jsonl")),
    ("gym-canon", os.path.join(K, "regression-canon", "gym-canon.jsonl")),
]

POSITIVE_ACTIONS = {
    "accepted", "built", "fixed", "shipped", "resolved", "verified",
    "rejected-false-alarm",  # a measured "nothing wrong" IS a measurement
}

TEXT_FIELDS = ("finding", "proposal", "notes", "detail", "slug", "assertion",
               "action", "report")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    print(f"WARN: malformed line skipped in {path}",
                          file=sys.stderr)
    return rows


def row_date(r):
    d = r.get("date") or r.get("found") or r.get("ts") or ""
    return str(d)[:10]


def signal_text(r):
    return " ".join(str(r[k]) for k in TEXT_FIELDS
                    if r.get(k)).lower()


def load_signals():
    signals = []
    for name, path in SIGNAL_SOURCES:
        for r in load_jsonl(path):
            date = row_date(r)
            if not date:
                continue
            positive = (r.get("status") in ("resolved", "closed")
                        if name == "gym-canon"
                        else r.get("action") in POSITIVE_ACTIONS)
            signals.append({
                "source": name,
                "date": date,
                "positive": positive,
                "text": signal_text(r) + " " + os.path.basename(path).lower(),
            })
    return signals


def basename_hits(targets, text):
    for t in targets or []:
        if os.path.basename(str(t)).lower() in text:
            return True
    return False


def compute(window_days, threshold):
    genome = load_jsonl(GENOME)
    if not genome:
        return {"genome_rows": 0, "window_patches": 0, "unbenefited": 0,
                "tripped": False, "threshold": threshold,
                "detail": [], "note": "genome empty or missing"}
    signals = load_signals()
    cutoff = (datetime.now(timezone.utc) - timedelta(days=window_days)
              ).strftime("%Y-%m-%d")
    detail = []
    unbenefited = 0
    for r in genome:
        ts = str(r.get("ts", ""))
        date = ts[:10] or row_date(r)
        if date and date < cutoff:
            continue  # outside window
        ids = {str(r.get("id", "")).lower(), str(r.get("origin_slug", "") or
                                                 "").lower()}
        targets = r.get("targets") or []
        # benefited requires BOTH an explicit target list (per-target-file
        # attribution) and a positive signal dated on/after the patch.
        # NB: id/slug checks are guarded non-empty — "" in text is vacuously
        # true and would attribute every patch to every signal.
        pid = str(r.get("id", "")).lower()
        slug = (r.get("origin_slug") or "").lower()
        hits = [s for s in signals
                if s["positive"] and s["date"] >= date
                and ((pid != "" and pid in s["text"])
                     or (slug != "" and slug in s["text"])
                     or basename_hits(targets, s["text"]))]
        benefited = bool(targets) and bool(hits)
        if not benefited:
            unbenefited += 1
        detail.append({
            "id": r.get("id"), "date": date, "source": r.get("source"),
            "targets": targets,
            "benefited": benefited,
            "signal_refs": [f'{h["source"]}@{h["date"]}' for h in
                            (hits if benefited else [])][:3],
        })
    tripped = unbenefited >= threshold
    return {"genome_rows": len(genome), "window_days": window_days,
            "window_patches": len(detail), "unbenefited": unbenefited,
            "threshold": threshold, "tripped": tripped, "detail": detail}


def main():
    ap = argparse.ArgumentParser(
        description="Ratchet counter: patches added without measured benefit "
                    "(wave-3 amendment 4 — watch only, never mutates)")
    ap.add_argument("--selftest", action="store_true")
    ap.add_argument("--window-days", type=int, default=14,
                    help="sliding window in days (default 14)")
    ap.add_argument("--threshold", type=int, default=3,
                    help="trip when unbenefited count reaches this (default 3)")
    ap.add_argument("--json", action="store_true",
                    help="full JSON result instead of the summary line")
    args = ap.parse_args()

    if args.selftest:
        return selftest()

    if args.window_days <= 0 or args.threshold <= 0:
        ap.error("--window-days and --threshold must be positive")
    res = compute(args.window_days, args.threshold)
    if args.json:
        print(json.dumps(res, indent=1))
    else:
        verdict = "TRIP" if res["tripped"] else "clear"
        print(f"ratchet: {verdict} unbenefited={res['unbenefited']} "
              f"window_patches={res['window_patches']} "
              f"threshold={res['threshold']} window_days={res['window_days']}")
        for d in res.get("detail", []):
            mark = "OK " if d["benefited"] else "MISS"
            print(f"  [{mark}] {d['id']} {d['date']} src={d['source']} "
                  f"targets={d['targets'] or 'NONE'} "
                  f"signals={d['signal_refs'] or '-'}")
    if res.get("tripped"):
        ids = [d["id"] for d in res.get("detail", []) if not d["benefited"]]
        print(f"RATCHET TRIP: {res['unbenefited']} patches added without "
              f"measured benefit in {args.window_days}d (threshold "
              f"{args.threshold}): {ids} — recombination is DEFERRED (no "
              f"clause->oracle registry); route this finding to Josh for a "
              f"manual cull decision.", file=sys.stderr)
        return 3
    return 0


def selftest():
    import tempfile
    with tempfile.TemporaryDirectory() as td:
        g = os.path.join(td, "genome.jsonl")
        sig_dir = os.path.join(td, "sig")
        os.makedirs(sig_dir)
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        rows = []
        for i, tgt in enumerate(["a.md", "b.md", "c.md", "d.md"]):
            rows.append({"id": f"pg-{i+1:04d}", "ts": f"{today}T00:0{i}:00Z",
                         "targets": [f"/x/{tgt}"], "source": "manual"})
        with open(g, "w") as f:
            for r in rows:
                f.write(json.dumps(r) + "\n")
        # one positive signal covering a.md only
        prop = os.path.join(sig_dir, "proposal-outcomes.jsonl")
        with open(prop, "w") as f:
            f.write(json.dumps({"date": today, "proposal": "touched a.md",
                                "action": "accepted", "notes": "x"}) + "\n")
        real = (globals()["GENOME"], globals()["SIGNAL_SOURCES"])
        globals()["GENOME"] = g
        globals()["SIGNAL_SOURCES"] = [
            ("proposal-outcomes", prop)]
        try:
            res = compute(14, 3)
            assert res["window_patches"] == 4, res
            assert res["unbenefited"] == 3, res
            assert res["tripped"] is True, res
            assert res["detail"][0]["benefited"] is True
            res2 = compute(14, 4)
            assert res2["tripped"] is False, res2
            # empty genome path
            globals()["GENOME"] = os.path.join(td, "missing.jsonl")
            res3 = compute(14, 1)
            assert res3["genome_rows"] == 0 and res3["tripped"] is False
        finally:
            globals()["GENOME"], globals()["SIGNAL_SOURCES"] = real
    print("selftest: PASS (window/count/attribution/threshold-edge/empty-genome)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
