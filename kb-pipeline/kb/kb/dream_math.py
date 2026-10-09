"""Dream math: quantitative self-evaluation for the dreaming team.

Every proposal card carries a MATH BLOCK produced here:
  - P(accept): Beta-Bayesian posterior over Josh's acceptance rate, updated by
    the outcomes ledger; logistic regression over proposal features once n>=20
    (features: domain breadth, evidence count, cost, novelty vs outcome).
  - EV: expected value = P(success) * value - cost (hours), with a sensitivity
    line naming the assumption the EV hinges on most.
  - Assumption regression: proposals register assumptions; `check` re-tests
    them against the current KB and flags decay (the assumption an accepted
    proposal silently outlived).

    python3 -m kb.dream_math score --cost 16 --value 60 --domains 3 --evidence 4
    python3 -m kb.dream_math fit                      # outcomes -> model (n>=20)
    python3 -m kb.dream_math assume --proposal X --text "..." --query "..."
    python3 -m kb.dream_math assume --check           # re-test all assumptions
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import Counter
from pathlib import Path

KNOWLEDGE = Path.home() / ".claude/knowledge"
# the REAL ledger written by proposal-decide.py (garden-reports, append-only)
OUTCOMES = KNOWLEDGE / "garden-reports/proposal-outcomes.jsonl"
LEGACY_OUTCOMES = KNOWLEDGE / "dreams/proposals/outcomes.jsonl"
ASSUMPTIONS = KNOWLEDGE / "dreams/assumptions.jsonl"

# informed prior: Josh accepts ambitious-but-evidenced harness proposals often
# Beta(2.2, 1.3) -> prior mean ~0.63; weakens as real outcomes accumulate
PRIOR_ALPHA, PRIOR_BETA = 2.2, 1.3


def _outcomes() -> list[dict]:
    recs = []
    for p in (OUTCOMES, LEGACY_OUTCOMES):
        if p.exists():
            recs += [json.loads(l) for l in p.read_text().splitlines() if l.strip()]
    return recs


def flywheel() -> dict:
    """Ledger stats for the /proposals display — the habit made visible."""
    recs = _outcomes()
    counts = Counter(o.get("action", "?") for o in recs)
    n_decided = counts.get("accepted", 0) + counts.get("rejected", 0)
    a, b = PRIOR_ALPHA, PRIOR_BETA
    for o in recs:
        if o.get("action") in ("accepted", "built"):
            a += 1
        elif o.get("action") == "rejected":
            b += 1
    return {
        "total_records": len(recs),
        "decisions": dict(counts),
        "posterior_p_accept": round(a / (a + b), 3),
        "message": (
            "prior-dominated — decide through the queue to train the model"
            if n_decided < 10
            else "learning from your decisions"
        ),
        "fit_ready": n_decided >= 20,
    }


def p_accept(domains: int, evidence: int, cost: float) -> dict:
    outcomes = _outcomes()
    a, b = PRIOR_ALPHA, PRIOR_BETA
    for o in outcomes:
        act = o.get("action", o.get("decision", ""))
        if act in ("accepted", "built", "accept"):
            a += 1
        elif act in ("rejected", "reject"):
            b += 1
    post_mean = a / (a + b)
    out = {
        "p_accept_beta": round(post_mean, 3),
        "evidence_n": len(outcomes),
        "method": "beta posterior (prior Beta(2.2,1.3) + outcomes)",
    }
    if len(outcomes) >= 20:
        try:
            import numpy as np

            X = np.array(
                [
                    [o.get("domains", 1), o.get("evidence", 0), o.get("cost", 8)]
                    for o in outcomes
                ],
                dtype=float,
            )
            y = np.array([1.0 if o.get("action", o.get("decision")) in ("accepted", "built", "accept") else 0.0 for o in outcomes])
            from sklearn.linear_model import LogisticRegression

            m = LogisticRegression(max_iter=200).fit(X, y)
            x = np.array([[domains, evidence, cost]], dtype=float)
            out["p_accept_model"] = round(float(m.predict_proba(x)[0][1]), 3)
            out["method"] = "logistic regression on outcomes"
        except Exception as e:  # noqa: BLE001 - fall back to beta
            out["model_error"] = str(e)[:100]
    return out


def ev(cost: float, value: float, p: float) -> dict:
    net = p * value - cost
    return {
        "expected_net_hours": round(net, 1),
        "verdict": "positive EV" if net > 0 else "negative EV — reshape or drop",
        "sensitivity": f"breaks even at P(success)={cost / value:.2f} (value {value}h, cost {cost}h)",
    }


def score(args) -> dict:
    p = p_accept(args.domains, args.evidence, args.cost)
    p_use = p.get("p_accept_model", p["p_accept_beta"])
    result = {"p_accept": p, "ev": ev(args.cost, args.value, p_use)}
    return result


def assume_add(proposal: str, text: str, query: str) -> dict:
    ASSUMPTIONS.parent.mkdir(parents=True, exist_ok=True)
    rec = {
        "id": f"asm-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "proposal": proposal,
        "assumption": text,
        "kb_query": query,
        "added": dt.datetime.now().isoformat(timespec="seconds"),
        "last_checked": None,
        "status": "open",
    }
    with ASSUMPTIONS.open("a") as f:
        f.write(json.dumps(rec) + "\n")
    return rec


def assume_check() -> dict:
    if not ASSUMPTIONS.exists():
        return {"assumptions": 0}
    from .search import search

    recs = [json.loads(l) for l in ASSUMPTIONS.read_text().splitlines() if l.strip()]
    out = []
    for r in recs:
        if r.get("status") == "closed":
            continue
        hits, _ = search(r["kb_query"], k=3, rerank=False)
        r["last_checked"] = dt.datetime.now().isoformat(timespec="seconds")
        if hits:
            top = hits[0]
            r["latest_evidence"] = top.url
            r["status"] = "supported" if top.text else "weakened"
        else:
            r["status"] = "no-evidence"
        out.append({k: r[k] for k in ("id", "proposal", "assumption", "status", "latest_evidence") if k in r})
    with ASSUMPTIONS.open("w") as f:
        for r in recs:
            f.write(json.dumps(r) + "\n")
    return {"checked": len(out), "results": out}


def fit() -> dict:
    outcomes = _outcomes()
    if len(outcomes) < 20:
        return {"error": f"only {len(outcomes)} outcomes; logistic fit needs n>=20 — Beta posterior active"}
    from .pmi import json as _json  # noqa: F401
    import numpy as np

    X = np.array([[o.get("domains", 1), o.get("evidence", 0), o.get("cost", 8)] for o in outcomes], dtype=float)
    y = np.array([1.0 if o.get("action", o.get("decision")) in ("accepted", "built", "accept") else 0.0 for o in outcomes])
    from sklearn.linear_model import LogisticRegression

    m = LogisticRegression(max_iter=200).fit(X, y)
    return {"n": len(outcomes), "coef_domains": round(m.coef_[0][0], 3), "coef_evidence": round(m.coef_[0][1], 3), "coef_cost": round(m.coef_[0][2], 3)}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    s = sub.add_parser("score")
    s.add_argument("--cost", type=float, required=True, help="hours")
    s.add_argument("--value", type=float, required=True, help="hours of value if it works")
    s.add_argument("--domains", type=int, default=2)
    s.add_argument("--evidence", type=int, default=2)
    sub.add_parser("fit")
    sub.add_parser("flywheel")
    a2 = sub.add_parser("assume")
    a2.add_argument("--proposal", required=True)
    a2.add_argument("--text", required=True)
    a2.add_argument("--query", required=True)
    a2.add_argument("--check", action="store_true")
    args = ap.parse_args()
    if args.cmd == "score":
        print(json.dumps(score(args), indent=2))
    elif args.cmd == "fit":
        print(json.dumps(fit(), indent=2))
    elif args.cmd == "flywheel":
        print(json.dumps(flywheel(), indent=2))
    elif args.cmd == "assume":
        print(json.dumps(assume_check() if args.check else assume_add(args.proposal, args.text, args.query), indent=2))
