#!/usr/bin/env python3
"""backtest-decisions.py — UAT the decisions engine against JOSH'S ACTUAL VERDICTS.

No waiting for organic calibration: the triage queue already carries ground
truth (accepted = Josh said valuable, rejected = Josh said no). This runs each
labeled finding through the decisions engine and scores discrimination BEFORE
any surface is wired. Also appends outcome rows into the decisions outcomes
ledger under surface=backtest-triage-<model> so the calibration loop starts on
real history, not synthetic smoke.

  backtest-decisions.py                       # both judge models, clean labels
  backtest-decisions.py --model baseten/deepseek-v4.1-flash --limit 8

Labels: accepted=1, rejected=0. built/deferred/open are EXCLUDED (built is
auto-lane contaminated; deferred is ambiguous). Output rows append to
knowledge/decisions/backtest-triage.jsonl (never rewritten).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import datetime as dt
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import decisions as D  # noqa: E402
from atomic_io import atomic_append  # noqa: E402

Q = Path.home() / ".claude/knowledge/triage/queue.jsonl"
BT = Path.home() / ".claude/knowledge/decisions/backtest-triage.jsonl"
MODELS = ["baseten/deepseek-v4.1-flash", "fireworks/kimi-k3"]


def labeled():
    rows, seen = {}, set()
    for line in Q.read_text().splitlines():
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        slug = r.get("slug")
        if not slug:
            continue
        rows[slug] = r  # LAST row wins: triage-decide appends status transitions
    out = []
    for r in rows.values():
        st = r.get("status")
        if st in ("accepted", "rejected"):
            out.append((r, 1 if st == "accepted" else 0))
    return out


def evidence(r) -> str:
    return json.dumps({k: r.get(k, "") for k in ("slug", "title", "kind", "source", "evidence", "work")},
                      indent=1)


# Iteration 2 (2026-10-14): iteration 1 asked "is this valuable" and FAILED
# (acc 0.25-0.31, urgency inverted — stale alerts read dramatic). The real
# discriminator is STALENESS: Josh rejects what is already handled/superseded,
# accepts fresh unaddressed work. Exemplars are real verdicts and are excluded
# from scoring by --exclude below.
QS = [
    {"name": "worth_surfacing", "type": "predicate",
     "instruction": ("Is this finding FRESH and still unaddressed — describing work that has NOT already "
                     "been done, superseded, or covered through another channel (Jira ticket, other agent, "
                     "later fix)? Answer FALSE if the finding is stale, a duplicate/earlier copy of an "
                     "already-handled issue, or its own text says the work is done or planned elsewhere "
                     "(e.g. 'plan ready', 'root cause found', 'superseded', 'awaiting X'). Answer TRUE only "
                     "if acting on it now would not duplicate existing work.\n"
                     "Example FALSE (stale): 'AE-change to Freshdesk plan ready; awaiting build "
                     "authorization + AE field confirmation' — the plan exists; channel is Jira.\n"
                     "Example TRUE (fresh): 'Replay gym leaves open canon entries for deleted recipes and "
                     "transient canary failures surface as defects' — no other channel covers it; action "
                     "still pending.")},
    {"name": "urgency", "type": "score",
     "instruction": ("Urgency 1-5: 1=cosmetic/hygiene, 2=nice-to-have, 3=worth doing soon, "
                     "4=should schedule this week, 5=drop everything / live incident risk"),
     "levels": [1, 2, 3, 4, 5]},
]


def run_one(rec_label, model):
    r, label = rec_label
    qname = f"backtest-triage-{'v41' if 'v4.1' in model else 'kimi'}" + (f"-{a.surface_tag}" if a.surface_tag else "")
    raw, usage = D._ask(model, evidence(r), QS, 2000)
    answers = D._answers(QS, raw)
    did = f"bt-{dt.datetime.now().strftime('%Y%m%d-%H%M%S%f')}-{abs(hash((r['slug'], model))) % 99999}"
    atomic_append(D.STORE, {"id": did, "ts": D._now(), "surface": qname, "model": model,
                            "evidence_src": r["slug"], "questions": QS, "answers": answers,
                            "usage": {k: usage.get(k) for k in ("prompt_tokens", "completion_tokens")}})
    p_true = next(a for a in answers if a["name"] == "worth_surfacing")["probabilities"].get("true", 0.0)
    urg = next(a for a in answers if a["name"] == "urgency")["value"]
    atomic_append(D.OUTCOMES, {"ts": D._now(), "decision_id": did, "name": "worth_surfacing",
                               "observed": bool(label), "note": f"josh-verdict:{r.get('status')}"})
    atomic_append(BT, {"ts": D._now(), "model": model, "slug": r["slug"], "label": label,
                       "p_true": p_true, "urgency": urg, "decision_id": did})
    return {"model": model, "slug": r["slug"], "label": label, "p_true": p_true, "urgency": urg}


def report(rows):
    print(f"\n{'model':32s} {'n':>3s} {'acc':>6s} {'brier':>7s}  urgency(accepted vs rejected)")
    for model in sorted({r["model"] for r in rows}):
        m = [r for r in rows if r["model"] == model]
        acc = sum(1 for r in m if (r["p_true"] > 0.5) == bool(r["label"])) / len(m)
        brier = sum((r["p_true"] - r["label"]) ** 2 for r in m) / len(m)
        pos = [r["urgency"] for r in m if r["label"]]
        neg = [r["urgency"] for r in m if not r["label"]]
        sep = (f"{sum(pos)/len(pos):.2f} vs {sum(neg)/len(neg):.2f}"
               if pos and neg else "n/a (one-sided slice)")
        print(f"{model:32s} {len(m):3d} {acc:6.2f} {brier:7.3f}  {sep}")


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--model", action="append", dest="models")
    ap.add_argument("--limit", type=int, default=0)
    ap.add_argument("--exclude", action="append", default=[])
    ap.add_argument("--surface-tag", default="")
    a = ap.parse_args()
    data = [(r, l) for r, l in labeled() if r["slug"] not in a.exclude]
    print(f"labeled findings: {len(data)} ({sum(l for _, l in data)} accepted / "
          f"{sum(1 for _, l in data if not l)} rejected)")
    pairs = [(r, m) for r in data for m in (a.models or MODELS)]
    if a.limit:
        pairs = pairs[:a.limit * len(a.models or MODELS)]
    results = []
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        for res in ex.map(run_one, [p[0] for p in pairs], [p[1] for p in pairs]):
            results.append(res)
    report(results)


if __name__ == "__main__":
    main()
