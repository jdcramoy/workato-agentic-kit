#!/usr/bin/env python3
"""shadow-judge.py — the promotion pipeline (jev-replica lever 4).

The judge runs BLIND on open triage cards (prediction ledgered before any
verdict can influence it) and gets scored when Josh's verdict lands. The flip
gates stop being a backtest argument and become a measured trajectory:
  promotion criteria: >= 0.8 accuracy AND non-inverted decay-urgency on
  >= 20 blind verdicts (dissenter's bar, 2026-10-14).

  shadow-judge.py run      # predict open cards (idempotent per content hash)
  shadow-judge.py report   # score blind predictions against landed verdicts

Cascade per card (no model call unless the rules layer passes it):
  triage_state.factors settle fresh/covered/mine -> non-candidates p=0.05
  candidates -> flash judge (p_valuable + decay_urgency) with 3 precedents
Ledger: knowledge/triage/shadow-predictions.jsonl (append-only).
"""
from __future__ import annotations

import hashlib
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import decisions as D  # noqa: E402
from atomic_io import atomic_append  # noqa: E402


def _load(name, filename):
    spec = importlib.util.spec_from_file_location(
        name, Path(__file__).parent / filename)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


TS = _load("triage_state", "triage-state.py")
PREC = _load("precedent", "precedent.py")
J4 = _load("jevish4", "backtest-jevish4.py")  # judge(), JUDGE_SYS — no main()

Q = Path.home() / ".claude/knowledge/triage/queue.jsonl"
PRED = Path.home() / ".claude/knowledge/triage/shadow-predictions.jsonl"
FLASH = "baseten/deepseek-v4.1-flash"


def _rows():
    return [json.loads(l) for l in Q.read_text().splitlines() if l.strip()]


def _hash(r):
    return hashlib.md5(" ".join(str(r.get(k, "")) for k in
                                ("slug", "title", "evidence", "work"))
                       .encode()).hexdigest()[:12]


def cmd_run():
    rows = _rows()
    seen = set()
    if PRED.exists():
        for line in PRED.read_text().splitlines():
            try:
                p = json.loads(line)
                seen.add((p["slug"], p["content_hash"]))
            except (json.JSONDecodeError, KeyError):
                pass
    by_slug = TS.build_index(rows)
    pindex = PREC.PrecedentIndex(rows)
    now = D._now()
    open_rows = [r for r in rows if r.get("status") == "open"]
    n_pred = n_cached = n_settled = 0
    for r in open_rows:
        h = _hash(r)
        if (r["slug"], h) in seen:
            n_cached += 1
            continue
        state = TS.state_block(r["slug"], r, by_slug, as_of=now)
        fac = TS.factors(state, r.get("source", ""))
        rec = {"ts": now, "slug": r["slug"], "content_hash": h,
               "candidate": fac["candidate"],
               "factors": {k: fac[k] for k in ("fresh", "covered", "mine")}}
        if not fac["candidate"]:
            rec["p"] = 0.05
            n_settled += 1
        else:
            ev = (J4.J1.BT.evidence(r) + "\n\n" + TS.render(state) + "\n\n"
                  + PREC.PrecedentIndex.render(
                      pindex.query(" ".join(str(r.get(k, "")) for k in
                                            ("slug", "title", "evidence", "work")),
                                   exclude_slug=r["slug"], as_of=now, k=3)))
            res = J4.judge(FLASH, False, ev)
            if "p" not in res:
                print(f"  judge failed for {r['slug']}: {res['error'][:100]}",
                      file=sys.stderr)
                continue
            rec["p"] = res["p"]
            rec["judge_p"] = res["p"]
            rec["decay_urgency"] = res["urg"]
            n_pred += 1
        atomic_append(PRED, rec)
    print(f"shadow: {n_pred} judged, {n_settled} rule-settled, "
          f"{n_cached} already predicted ({len(open_rows)} open)")


def cmd_report():
    rows = _rows()
    # latest verdict per slug with its decision time
    verdict = {}
    for r in rows:
        if r.get("status") in ("accepted", "rejected", "built", "filed", "deferred"):
            verdict[r["slug"]] = r
    preds = {}
    for line in PRED.read_text().splitlines() if PRED.exists() else []:
        try:
            p = json.loads(line)
            preds.setdefault(p["slug"], []).append(p)
        except json.JSONDecodeError:
            pass
    blind = []
    for slug, ps in preds.items():
        v = verdict.get(slug)
        if not v:
            continue
        vt = v.get("decided_ts") or v.get("ts") or ""
        label = 1 if v["status"] in ("accepted", "built", "filed") else 0
        for p in ps:  # only predictions made BEFORE the verdict count as blind
            if p["ts"] < vt:
                blind.append({"slug": slug, "p": p["p"], "label": label,
                              "urg": p.get("decay_urgency"),
                              "pred_ts": p["ts"], "verdict_ts": vt})
    if not blind:
        print("shadow report: no blind predictions with landed verdicts yet. "
              "Predictions accrue at each triage pass; verdicts close them.")
        return
    n = len(blind)
    acc = sum(1 for b in blind if (b["p"] > 0.5) == bool(b["label"])) / n
    judged = [b for b in blind if b.get("urg") is not None]
    urg_line = "no urgency data"
    if judged:
        pos = [b["urg"] for b in judged if b["label"]]
        neg = [b["urg"] for b in judged if not b["label"]]
        if pos and neg:
            inv = sum(pos) / len(pos) < sum(neg) / len(neg)
            urg_line = (f"decay-urgency accepted {sum(pos)/len(pos):.2f} vs "
                        f"rejected {sum(neg)/len(neg):.2f} "
                        f"({'INVERTED' if inv else 'ok'})")
    gate = n >= 20 and acc >= 0.8 and "INVERTED" not in urg_line
    print(f"shadow report: {n} blind verdicts | acc {acc:.2f} | {urg_line}")
    print(f"flip gates: n>=20 {'OK' if n >= 20 else f'({n}/20)'} | "
          f"acc>=0.8 {'OK' if acc >= 0.8 else f'({acc:.2f})'} | "
          f"urgency {'ok' if 'INVERTED' not in urg_line else 'INVERTED'}")
    print(f"PROMOTION: {'GATES PASS — eligible for Josh review' if gate else 'not met — stays order-only'}")


if __name__ == "__main__":
    {"run": cmd_run, "report": cmd_report}.get(sys.argv[1] if len(sys.argv) > 1
                                               else "", lambda: sys.exit(
        "usage: shadow-judge.py run|report"))()
