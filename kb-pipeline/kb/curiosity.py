"""curiosity.py — questions as first-class objects with lifecycles.

Every surprise (prediction deviation, contradiction, entropy spike, anomaly)
MINTS a question: {question, why, cheapest_experiment, priority}. The
dreamer's nightly job includes spending effort on the highest-value open
question; answers become claims/knowledge. The harness goes from a system
that answers to a system that wants to know.

  kb curiosity mint --question "..." --why "..." --experiment "..." [--from prediction-error]
  kb curiosity open                     # the standing question queue, ranked
  kb curiosity answer --id Q --answer "..." [--claim]   # close a question (optionally as a claim)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from pathlib import Path

LEDGER = Path.home() / ".claude/workato-kb/index/curiosity.jsonl"


def _load() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]


def mint(question: str, why: str, experiment: str, origin: str = "manual", priority: float = 0.5) -> dict:
    q = {
        "id": f"q-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}",
        "question": question, "why": why, "cheapest_experiment": experiment,
        "origin": origin, "priority": priority, "status": "open",
        "minted": dt.datetime.now().isoformat(timespec="seconds"),
    }
    LEDGER.parent.mkdir(parents=True, exist_ok=True)
    with LEDGER.open("a") as f:
        f.write(json.dumps(q, ensure_ascii=False) + "\n")
    return q


def mint_from_prediction_error(pred: dict) -> dict:
    """A deviated prediction is a minter: the model believed wrong — why?"""
    return mint(
        question=f"Why did {pred.get('agent')}'s prediction deviate: expected [{pred.get('expect', '')[:80]}], got [{pred.get('observed', '')[:80]}]?",
        why="prediction errors are unexplained model-of-world failures; explaining one prevents its class",
        experiment="re-run the action with logging; compare step traces",
        origin=f"prediction-error/{pred.get('id', '')}",
        priority=0.8,
    )


def answer(qid: str, answer_text: str, as_claim: bool = False) -> dict:
    recs = _load()
    for r in recs:
        if r["id"] == qid:
            r["status"] = "answered"
            r["answer"] = answer_text
            r["answered_at"] = dt.datetime.now().isoformat(timespec="seconds")
            if as_claim:
                r["claim_filed"] = True
                claims = Path.home() / ".claude/knowledge/claims/claims.jsonl"
                with claims.open("a") as f:
                    f.write(json.dumps({
                        "id": f"clm-cur-{qid}", "claim": answer_text[:300],
                        "verdict": "verified", "source": f"curiosity/{qid}",
                        "created": r["answered_at"],
                    }) + "\n")
    LEDGER.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    return {"answered": qid, "as_claim": as_claim}


def open_questions(k: int = 10) -> list[dict]:
    qs = [r for r in _load() if r.get("status") == "open"]
    return sorted(qs, key=lambda r: -r.get("priority", 0.5))[:k]


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    m = sub.add_parser("mint")
    m.add_argument("--question", required=True)
    m.add_argument("--why", required=True)
    m.add_argument("--experiment", required=True)
    m.add_argument("--priority", type=float, default=0.5)
    an = sub.add_parser("answer")
    an.add_argument("--id", required=True)
    an.add_argument("--answer", required=True)
    an.add_argument("--claim", action="store_true")
    sub.add_parser("open")
    a = ap.parse_args()
    if a.cmd == "mint":
        print(json.dumps(mint(a.question, a.why, a.experiment, priority=a.priority), indent=2))
    elif a.cmd == "answer":
        print(json.dumps(answer(a.id, a.answer, a.claim), indent=2))
    elif a.cmd == "open":
        print(json.dumps(open_questions(), indent=2))
