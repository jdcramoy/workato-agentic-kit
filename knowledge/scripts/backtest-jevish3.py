#!/usr/bin/env python3
"""backtest-jevish3.py — iteration 3: judges on STATE-ENRICHED evidence + cascade arms.

Same labels, same questions, same machinery as backtest-jevish.py — the only
change is the evidence: each finding's payload now carries the triage_state
block (lane semantics, prior decisions, sibling verdicts, ticket coverage,
lexical flags, age), assembled leak-free as-of verdict time.

New arms vs spike 1:
  cascade-single    source-rule settles covered rows, single judge on residue
  cascade-ensemble  source-rule settles covered rows, ensemble on residue
(the cascade IS the Jev-replica design: deterministic/provenance first,
judgment only on the residue the rules can't settle.)

  backtest-jevish3.py --limit 3   # smoke
  backtest-jevish3.py             # full run

Ledger: knowledge/decisions/backtest-jevish3.jsonl (append-only).
"""
from __future__ import annotations

import argparse
import concurrent.futures as cf
import importlib.util
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
import decisions as D  # noqa: E402
from atomic_io import atomic_append  # noqa: E402


def _load(name, path):
    spec = importlib.util.spec_from_file_location(name, path)
    m = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(m)
    return m


J1 = _load("jevish1", Path(__file__).parent / "backtest-jevish.py")
TS = _load("triage_state", Path(__file__).parent / "triage-state.py")

OUT = Path.home() / ".claude/knowledge/decisions/backtest-jevish3.jsonl"


def queue_rows():
    q = Path.home() / ".claude/knowledge/triage/queue.jsonl"
    return [json.loads(l) for l in q.read_text().splitlines() if l.strip()]


def process(rec_label, by_slug):
    r, label = rec_label
    state = TS.state_block(r["slug"], r, by_slug)
    ev = J1.BT.evidence(r) + "\n\n" + TS.render(state)

    votes, vusage = [], []
    for model, phr in J1.VOTES:
        v = J1.vote(model, phr, ev)
        votes.append(v)
        vusage.append((model, v.get("usage", {})))
    ok = [v for v in votes if "ws" in v]
    try:
        p_single, u_single, susage = J1.single_call(J1.SINGLE_MODEL, ev)
    except (Exception, SystemExit) as e:
        p_single, u_single, susage = None, None, {}
        print(f"  WARN single-call failed for {r['slug']}: {str(e)[:120]}", flush=True)

    row = {"ts": D._now(), "slug": r["slug"], "label": label,
           "source": r.get("source", ""),
           "state_flags": state["lexical_flags"],
           "n_prior": len(state["prior_decisions"]),
           "n_siblings": len(state["siblings"]),
           "n_votes_ok": len(ok),
           "votes": [{k: v[k] for k in ("ws", "urgency") if k in v} |
                     ({"error": v["error"]} if "error" in v else {}) for v in votes],
           "p_single": p_single, "urg_single": u_single}
    if len(ok) >= 3:
        row["p_ens"] = sum(1 for v in ok if v["ws"]) / len(ok)
        row["urg_ens"] = sum(v["urgency"] for v in ok) / len(ok)
    atomic_append(OUT, row)
    tokens = {}
    for model, u in vusage + [(J1.SINGLE_MODEL, susage)]:
        t = tokens.setdefault(model, [0, 0])
        t[0] += u.get("prompt_tokens", 0)
        t[1] += u.get("completion_tokens", 0)
    return row, tokens


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--limit", type=int, default=0)
    a = ap.parse_args()

    data = J1.labeled()
    if a.limit:
        data = data[:a.limit]
    by_slug = TS.build_index(queue_rows())
    print(f"labeled findings: {len(data)} ({sum(l for _, l in data)} accepted / "
          f"{sum(1 for _, l in data if not l)} rejected)", flush=True)

    rows, tokens = [], {}
    with cf.ThreadPoolExecutor(max_workers=6) as ex:
        futs = [ex.submit(process, rl, by_slug) for rl in data]
        for f in cf.as_completed(futs):
            row, tk = f.result()
            rows.append(row)
            for m, (pi, po) in tk.items():
                t = tokens.setdefault(m, [0, 0])
                t[0] += pi
                t[1] += po
            print(f"  {row['slug'][:52]:52s} label={row['label']} "
                  f"p_single={row['p_single'] if row['p_single'] is None else round(row['p_single'],2)} "
                  f"p_ens={round(row['p_ens'],2) if 'p_ens' in row else '-'}", flush=True)

    ys = [r["label"] for r in rows]
    sng = [r for r in rows if r.get("p_single") is not None]
    ens = [r for r in rows if "p_ens" in r]
    maj = sum(ys) / len(ys)

    iso_single = J1.crossfit([{**r, "p": r["p_single"]} for r in sng], "p")
    iso_ens = J1.crossfit([{**r, "p": r["p_ens"]} for r in ens], "p")

    def cascade(judge_p):
        return [(J1.source_rule(r["source"]) if J1.source_rule(r["source"]) is not None
                 else judge_p(r)) for r in rows]

    n_rule_covered = sum(1 for r in rows
                         if J1.source_rule(r["source"]) is not None)

    arms = {
        "source-rule(+majority)": ([(J1.source_rule(r["source"])
                                     if J1.source_rule(r["source"]) is not None
                                     else 0.0) for r in rows], ys),
        "single+state": ([r["p_single"] for r in sng], [r["label"] for r in sng]),
        "single+state+iso": ([iso_single[r["slug"]] for r in sng],
                             [r["label"] for r in sng]),
        "ensemble+state": ([r["p_ens"] for r in ens], [r["label"] for r in ens]),
        "ensemble+state+iso": ([iso_ens[r["slug"]] for r in ens],
                               [r["label"] for r in ens]),
        "cascade rule->single": (cascade(lambda r: r["p_single"]
                                         if r.get("p_single") is not None else 0.0), ys),
        "cascade rule->ensemble": (cascade(lambda r: r.get("p_ens", 0.0)), ys),
    }

    print(f"\n{'arm':26s} {'n':>3s} {'acc':>6s} {'brier':>7s} {'ece':>6s} {'auroc':>6s}")
    for name, (ps, yy) in arms.items():
        acc, br, ec, au = J1.metrics(ps, yy)
        gate = "  GATE-OK" if acc >= 0.8 else ""
        print(f"{name:26s} {len(ps):3d} {acc:6.2f} {br:7.3f} {ec:6.3f} {au:6.2f}{gate}")
    print(f"\ncascade coverage: rule settles {n_rule_covered}/{len(rows)} "
          f"({n_rule_covered/len(rows):.0%}); judge sees only the residue")

    print("\nurgency separation on state-enriched evidence (accepted vs rejected):")
    for name, ukey in (("single", "urg_single"), ("ensemble", "urg_ens")):
        sub = [r for r in rows if r.get(ukey) is not None]
        pos = [r[ukey] for r in sub if r["label"]]
        neg = [r[ukey] for r in sub if not r["label"]]
        if not pos or not neg:
            print(f"  {name:9s}: n/a")
            continue
        verdict = "INVERTED" if sum(pos) / len(pos) < sum(neg) / len(neg) else "ok"
        print(f"  {name:9s}: {sum(pos)/len(pos):.2f} vs {sum(neg)/len(neg):.2f}  ({verdict})")

    print("\nconfident-FALSE region (p<0.2) accepted share (lower=better):")
    for name, ps in (("single+state", [(r["p_single"], r["label"]) for r in sng]),
                     ("ensemble+state", [(r["p_ens"], r["label"]) for r in ens]),
                     ("casc->ens", list(zip(cascade(lambda r: r.get("p_ens", 0.0)), ys)))):
        sub = [(p, y) for p, y in ps if p < 0.2]
        if sub:
            print(f"  {name:15s}: n={len(sub)}  accepted={sum(y for _, y in sub)}"
                  f" ({sum(y for _, y in sub)/len(sub):.2f})")

    print("\nspike-1 reference (text-only evidence): single acc=0.61, ensemble acc=0.49, "
          "rule acc=0.81, urgency INVERTED in both judge arms")

    print("\nest. cost (rate card):")
    price = {"deepseek": (0.22, 0.66), "glm": (0.15, 0.50)}
    total = 0.0
    for m, (pi, po) in tokens.items():
        pr = price["deepseek"] if "deepseek" in m else price["glm"]
        c = pi / 1e6 * pr[0] + po / 1e6 * pr[1]
        total += c
        print(f"  {m:32s} {pi:>9,} in / {po:>8,} out  ~= ${c:.4f}")
    print(f"  {'TOTAL':32s} {'':>22s} ~= ${total:.4f}")


if __name__ == "__main__":
    main()
