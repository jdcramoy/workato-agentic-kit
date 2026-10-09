#!/usr/bin/env python3
"""model_routing.py — route by measured quality, not assumption.

The fleet has three model lineages. Tonight lenses were assigned by REASONING
about them; this module makes assignment EMPIRICAL: track which model's
opinions/proposals Josh actually accepted (or rejected), compute per-model,
per-task-type acceptance + cost, and recommend the routing.

Data in: the outcomes ledger (proposals carry `models:` frontmatter — which
models touched them), the dissent ledger (per-critic catch rates), and the
kimi ledger (cost).

  model_routing.py stats                    # the table
  model_routing.py recommend --task lens    # which model for this task type

The routing rule it enforces once data exists: assign the task type to the
model with the best acceptance-at-lowest-cost; re-evaluate weekly (explore
the laggards at small budget so the measurement stays live).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
from collections import defaultdict
from pathlib import Path

K = Path.home() / ".claude/knowledge"
OUTCOMES = K / "garden-reports/proposal-outcomes.jsonl"
PROPOSALS = K / "dreams/proposals"
KIMI_LEDGER = Path.home() / ".claude/workato-kb/kimi-ledger.jsonl"

MODEL_NAMES = {"kimi": "kimi-k3", "glm": "glm-5.3-flash", "deepseek": "deepseek-4.1-flash"}


def _proposal_models(slug_frag: str) -> list[str]:
    """Which models touched a proposal (from its `models:` frontmatter)."""
    for f in PROPOSALS.glob("*.md"):
        if slug_frag.split("-")[0] not in f.name:
            continue
        m = re.search(r"^models:\s*(.+)$", f.read_text(), re.M)
        if m:
            found = []
            for short, full in MODEL_NAMES.items():
                if short in m.group(1).lower() or full in m.group(1).lower():
                    found.append(short)
            return found
    return []


def stats() -> dict:
    outcomes = [json.loads(l) for l in OUTCOMES.read_text().splitlines() if l.strip()] if OUTCOMES.exists() else []
    per_model: dict[str, dict] = defaultdict(lambda: {"accepted": 0, "rejected": 0, "touched": 0})
    for o in outcomes:
        models = _proposal_models(o.get("proposal", ""))
        act = o.get("action", "")
        for m in models:
            per_model[m]["touched"] += 1
            if act in ("accepted", "built", "accepted-modified"):
                per_model[m]["accepted"] += 1
            elif act == "rejected":
                per_model[m]["rejected"] += 1
    out = {}
    for m, c in per_model.items():
        n = c["accepted"] + c["rejected"]
        out[m] = {**c, "acceptance": round(c["accepted"] / n, 3) if n else None}
    # cost side: kimi token ledger
    if KIMI_LEDGER.exists():
        kimi_tokens = sum(
            (json.loads(l).get("input_tokens") or 0) + (json.loads(l).get("output_tokens") or 0) * 3
            for l in KIMI_LEDGER.read_text().splitlines() if l.strip()
        )
        out.setdefault("kimi", {})["weighted_tokens_spent"] = kimi_tokens
    out["_note"] = (
        "acceptance is per-proposal-attributed (a proposal touched by kimi+glm credits both) — "
        "resolution sharpens as proposals carry single-model authorship; explore-exploit: "
        "keep giving each model one seat so the measurement stays live"
    )
    return {"generated": dt.datetime.now().isoformat(timespec="seconds"), "models": out}


def recommend(task: str) -> dict:
    s = stats()["models"]
    if not s or all(v.get("acceptance") is None for v in s.values()):
        return {"task": task, "recommendation": "no measured data yet — rotate all three (explore phase)"}
    scored = {m: v for m, v in s.items() if v.get("acceptance") is not None}
    if not scored:
        return {"task": task, "recommendation": "no measured data yet — rotate all three (explore phase)"}
    best = max(scored, key=lambda m: (scored[m]["acceptance"], -scored[m].get("weighted_tokens_spent", 0)))
    return {
        "task": task,
        "recommendation": f"{best} (acceptance {scored[best]['acceptance']}) — but keep one seat per session for the others (explore-exploit)",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("stats")
    r = sub.add_parser("recommend")
    r.add_argument("--task", default="lens")
    a = ap.parse_args()
    print(json.dumps(stats() if a.cmd == "stats" else recommend(a.task), indent=2))
