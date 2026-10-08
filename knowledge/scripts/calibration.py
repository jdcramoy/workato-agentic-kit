#!/usr/bin/env python3
"""calibration.py — agent calibration as measurable science.

Every prediction closed (predict.py) and every proposal verdict logged
(proposal-outcomes.jsonl) is a data point about an agent's reliability.
This script turns those points into CALIBRATION: not "is the agent smart"
but "when this agent predicts X, how often is X true" — per agent, per
action class, with a week-over-week trend. The harness's compounding
claim becomes a curve.

  calibration.py                     # all agents, current window
  calibration.py --agent harness-dreamer
  calibration.py --card              # write the weekly calibration card

A well-calibrated agent says 'deviated' when things deviate: its accuracy
should approach the confidence it implies. Overconfidence (accuracy far
below implied) is the failure mode this measures.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

K = Path.home() / ".claude/knowledge"
PREDICTIONS = K / "dreams/predictions.jsonl"
OUTCOMES = K / "garden-reports/proposal-outcomes.jsonl"
CARDS = K / "dreams/calibration"


def load_all() -> dict:
    preds = []
    if PREDICTIONS.exists():
        preds = [json.loads(l) for l in PREDICTIONS.read_text().splitlines() if l.strip()]
    outcomes = []
    if OUTCOMES.exists():
        outcomes = [json.loads(l) for l in OUTCOMES.read_text().splitlines() if l.strip()]
    return {"predictions": preds, "outcomes": outcomes}


def agent_calibration(agent: str | None = None) -> dict:
    data = load_all()
    # prediction accuracy by agent and action class
    by_agent: dict[str, dict] = defaultdict(lambda: {"matched": 0, "deviated": 0, "failed": 0, "open": 0})
    for p in data["predictions"]:
        a = by_agent[p.get("agent", "?")]
        v = p.get("verdict")
        if v is None:
            a["open"] += 1
        else:
            a[v] += 1
    # proposal verdict accuracy: how often did the dreamers' proposals get accepted?
    proposal_stats: dict[str, dict] = defaultdict(lambda: {"accepted": 0, "rejected": 0})
    for o in data["outcomes"]:
        act = o.get("action", "")
        if act in ("accepted", "built", "accepted-modified"):
            proposal_stats["dreamers"]["accepted"] += 1
        elif act == "rejected":
            proposal_stats["dreamers"]["rejected"] += 1

    out = {"generated": dt.datetime.now().isoformat(timespec="seconds"), "agents": {}}
    for name, c in by_agent.items():
        if agent and name != agent:
            continue
        decided = c["matched"] + c["deviated"] + c["failed"]
        acc = round(c["matched"] / decided, 3) if decided else None
        out["agents"][name] = {
            "predictions": {**c, "accuracy": acc},
            # overconfidence flag: claiming confidence while missing often
            "overconfidence": (
                round(1 - acc, 3) if acc is not None and decided >= 3 else None
            ),
        }
    if not agent or agent == "dreamers":
        out["agents"]["dreamers"] = {
            "proposal_acceptance": {
                **proposal_stats.get("dreamers", {"accepted": 0, "rejected": 0}),
                "rate": None,
            }
        }
        acc = proposal_stats.get("dreamers", {})
        n = acc.get("accepted", 0) + acc.get("rejected", 0)
        if n:
            out["agents"]["dreamers"]["proposal_acceptance"]["rate"] = round(acc["accepted"] / n, 3)
    out["verdict_note"] = (
        "accuracy far below 1.0 with n>=5 = the agent's expectations need work; "
        "an agent with no closed predictions is unmeasured, not trusted"
    )
    return out


def write_card() -> Path:
    data = agent_calibration()
    CARDS.mkdir(parents=True, exist_ok=True)
    week = dt.date.today().isocalendar()
    out = CARDS / f"{dt.date.today().isoformat()}-calibration.md"
    lines = [
        f"# Calibration card — week {week[1]} {week[0]}",
        "",
        "| Agent | Closed predictions | Accuracy | Overconfidence gap |",
        "|---|---|---|---|",
    ]
    for name, d in data["agents"].items():
        p = d.get("predictions", {})
        if p:
            n = p.get("matched", 0) + p.get("deviated", 0) + p.get("failed", 0)
            lines.append(f"| {name} | {n} | {p.get('accuracy') or 'unmeasured'} | {d.get('overconfidence') or '-'} |")
        if "proposal_acceptance" in d:
            pa = d["proposal_acceptance"]
            lines.append(f"| dreamers (proposals) | {pa.get('accepted', 0) + pa.get('rejected', 0)} | {pa.get('rate') or 'unmeasured'} | - |")
    lines += ["", f"_n below 5 per cell = anecdote, not calibration. Open predictions: "
              f"{sum(d.get('predictions', {}).get('open', 0) for d in data['agents'].values())}_"]
    out.write_text("\n".join(lines) + "\n")
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--agent", default=None)
    ap.add_argument("--card", action="store_true")
    a = ap.parse_args()
    if a.card:
        p = write_card()
        print(f"card written: {p}")
    else:
        print(json.dumps(agent_calibration(a.agent), indent=2))
