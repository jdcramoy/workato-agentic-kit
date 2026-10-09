"""gym_judgment.py — spaced repetition for fleet judgment.

The modality: re-present past incidents (cases) as drills; score the
diagnosis against the case's known answer; resurface failed cases more
often (SM-2-lite). Calibration.py finds WHERE judgment is weak; the gym
TRAINS it; the curve shows improvement.

  kb gym_judgment drill [-k 3]        # drill N cases (LLM-judged, spaced)
  kb gym_judgment history             # the improvement curve data
"""

from __future__ import annotations

import argparse
import datetime as dt
import re
import json
import math
from pathlib import Path

from .cases import _connect as cases_connect

HIST = Path.home() / ".claude/workato-kb/index/gym-judgment.jsonl"
GAP_DAYS = [1, 3, 7, 14, 30]  # successful drills push the interval out


def _due_cases(k: int) -> list[dict]:
    """Cases due for drill: never-drilled first, then by due date (failed = sooner)."""
    db = cases_connect()
    try:
        rows = db.execute("SELECT case_id, created, presentation, diagnosis, treatment, outcome, tags FROM cases").fetchall()
    finally:
        db.close()
    hist: dict[str, list[dict]] = {}
    if HIST.exists():
        for line in HIST.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            hist.setdefault(r["case_id"], []).append(r)
    now = dt.datetime.now()
    scored = []
    for case in rows:
        cid = case[0]
        h = hist.get(cid, [])
        if not h:
            scored.append((0, now, case))  # new case: drill first
            continue
        last = h[-1]
        due = dt.datetime.fromisoformat(last["next_due"])
        last_ok = last.get("grade", 0) >= 0.6
        # failed cases resurface quickly; success pushes out
        interval = GAP_DAYS[min(last.get("streak", 0), len(GAP_DAYS) - 1)] if last_ok else 1
        if (now - due).total_seconds() >= 0 or not last_ok:
            scored.append((1 + (0 if last_ok else 2), due, case))
    scored.sort(key=lambda x: (x[0], x[1]))
    return [c for _, _, c in scored[:k]]


def drill(k: int = 3, judge_model: str = "deepseek", persona: str = "doctor") -> dict:
    """Present case presentations to a fresh lens; grade diagnosis vs known answer."""
    from .lens_call import _call

    cases = _due_cases(k)
    out = []
    for case in cases:
        cid, created, presentation, diagnosis, treatment, outcome, tags = case
        prompt = (
            "A Workato incident has this signature (you have no other context):\n"
            f"{presentation}\n\n"
            "Give your diagnosis (root cause) and treatment in at most 3 lines."
        )
        try:
            resp = _call(judge_model, "", prompt, max_tokens=900)
            answer = resp.get("text", "")
        except Exception as e:  # noqa: BLE001
            out.append({"case_id": cid, "error": str(e)[:150]})
            continue
        # grade: LLM-judge comparing answer to the known diagnosis
        judge_prompt = (
            f"Known correct diagnosis: {diagnosis}\nKnown treatment: {treatment}\n\n"
            f"Candidate answer: {answer[:800]}\n\n"
            "Grade 0.0-1.0 on diagnosis correctness. Reply with ONLY the number."
        )
        try:
            g = _call("deepseek", "", judge_prompt, max_tokens=30)
            grade = float(re.search(r"([01](?:\.\d+)?)", g.get("text", "0.5")).group(1))
        except Exception:  # noqa: BLE001
            grade = 0.5
        out.append({"case_id": cid, "grade": grade, "answer_excerpt": answer[:200], "known": diagnosis[:150]})
        with HIST.open("a") as f:
            f.write(json.dumps({
                "case_id": cid, "ts": dt.datetime.now().isoformat(timespec="seconds"),
                "grade": grade, "judge": judge_model,
                "next_due": (dt.datetime.now() + dt.timedelta(days=1 if grade < 0.6 else 7)).isoformat(),
                "streak": 0,  # streak maintenance simplified: history reads compute it
            }) + "\n")
    return {"drilled": len(out), "results": out}


def history() -> dict:
    if not HIST.exists():
        return {"note": "no drills yet"}
    drills = [json.loads(l) for l in HIST.read_text().splitlines() if l.strip()]
    by_ts = sorted(drills, key=lambda r: r["ts"])
    grades = [r["grade"] for r in by_ts]
    n = len(grades)
    half = n // 2 or 1
    early = sum(grades[:half]) / half
    late = sum(grades[half:]) / max(n - half, 1)
    return {
        "drills": n, "avg_grade_all": round(sum(grades) / n, 3),
        "trend_early_vs_late": [round(early, 3), round(late, 3)],
        "verdict": "improving" if late > early else "flat/declining (or n too small)",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("drill")
    d.add_argument("-k", type=int, default=3)
    sub.add_parser("history")
    a = ap.parse_args()
    if a.cmd == "drill":
        print(json.dumps(drill(a.k), indent=2))
    elif a.cmd == "history":
        print(json.dumps(history(), indent=2))
