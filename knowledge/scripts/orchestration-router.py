#!/usr/bin/env python3
"""
orchestration-router.py — decide how to execute a task: solo, fanout, pipeline, or team.

Two layers, evaluated in order:
  1. HARD RULES (strategic gates) — prod writes, adversarial separation, triviality.
     These override any score. They encode Josh's standing orders verbatim.
  2. WEIGHTED FEATURE SCORE (mathematical) — six features scored 0.0-1.0,
     four patterns scored by weighted sum, argmax wins.

Usage:
  orchestration-router.py --task "sweep 10 repos for TODOs" \
    --independence 0.9 --statefulness 0.1 --coordination 0.0 \
    --context-volume 0.7 --collision-risk 0.0 --latency-sensitivity 0.8

  Flags: --prod-write, --adversarial, --subtask-count N tune the gates.

Exit: prints verdict + scores + reasoning; exit 0.
"""

import argparse
import sys

PATTERNS = ["solo", "fanout", "pipeline", "team"]

# Weight vectors per pattern over features:
#   ind=independence, sta=statefulness, coo=coordination,
#   ctx=context-volume, col=collision-risk, lat=latency-sensitivity,
#   seq=sequential (1=strict stage ordering/handoffs, 0=parallel-friendly)
W = {
    "solo":     {"ind": -0.5, "sta": -0.5, "coo": -1.0, "ctx": -2.0, "col": -0.5, "lat": -1.0, "seq": -0.5, "bias": 1.5},
    "fanout":   {"ind":  2.0, "sta": -1.5, "coo": -2.0, "ctx":  1.5, "col": -1.5, "lat":  1.0, "seq": -1.0, "bias": 0.0},
    "pipeline": {"ind":  1.0, "sta":  0.5, "coo":  1.0, "ctx":  1.0, "col":  0.0, "lat": -0.5, "seq":  2.0, "bias": 0.0},
    "team":     {"ind":  0.0, "sta":  2.0, "coo":  2.0, "ctx":  1.0, "col":  1.5, "lat":  0.5, "seq": -1.0, "bias": -0.5},
}

FEATURE_LABELS = {
    "ind": "independence (subtasks disjoint, no shared state)",
    "sta": "statefulness (work spans turns / roles / persistent judgment)",
    "coo": "coordination (agents need each other's outputs mid-flight)",
    "ctx": "context-volume (worker grunt work would flood the orchestrator)",
    "col": "collision-risk (shared files/assets, ordering sensitivity)",
    "lat": "latency-sensitivity (parallel wall-clock benefit)",
    "seq": "sequential (strict stage ordering — pipeline shape, not mesh)",
}

GUARDRAILS = {
    "solo": ["Answer in the main session; no dispatch overhead."],
    "fanout": [
        "Spawn all agents in ONE message so they run concurrently.",
        "Results land via notification; verify claims against live evidence before merging.",
        "Orchestrator is the verification gate — no worker claim enters the thread un-checked.",
    ],
    "pipeline": [
        "Use Workflow/scripted stages; each stage verifies before handing to the next.",
        "Keep stage prompts fixed for auditability.",
    ],
    "team": [
        "Name teammates by ROLE; disjoint file ownership declared up front.",
        "All coordination on the bus/claims ledger — every claim row closes out.",
        "Builder never reviews its own work; independent reviewer mandatory.",
        "Persistent state rots: close claims, or flag POSSIBLE UNFINISHED PROD STATE.",
    ],
}


def hard_rules(args, f):
    """Return (verdict, reason) if a strategic gate fires, else None."""
    if args.prod_write:
        return ("orchestrator-gated", (
            "HARD RULE: prod write — happens in THIS session after first-hand "
            "confirmation. Never delegated (teams OR fanout); blanket delegations "
            "never satisfy prod gates. Workers may gather read-only evidence first."))
    if args.adversarial:
        return ("team", (
            "HARD RULE: adversarial separation required — the builder never reviews "
            "its own work. Dispatch an independent agent as a distinct role; "
            "one-shot fanout cannot provide role continuity for the gate."))
    if args.subtask_count is not None and args.subtask_count <= 1 and f["ctx"] < 0.3:
        return ("solo", "Single small subtask — dispatch overhead exceeds value.")
    if f["col"] >= 0.8 and args.subtask_count is not None and args.subtask_count > 1:
        return ("team", (
            "HARD RULE: high collision risk across multiple subtasks — serial or "
            "team-with-disjoint-ownership only (agent-swarm rule: no ordering races)."))
    return None


def score(f):
    out = {}
    for p in PATTERNS:
        w = W[p]
        out[p] = (w["ind"] * f["ind"] + w["sta"] * f["sta"] + w["coo"] * f["coo"]
                  + w["ctx"] * f["ctx"] + w["col"] * f["col"] + w["lat"] * f["lat"]
                  + w["seq"] * f["seq"] + w["bias"])
    return out


def main():
    ap = argparse.ArgumentParser(description="Orchestration pattern router")
    ap.add_argument("--task", required=True, help="one-line task description")
    ap.add_argument("--independence", type=float, default=0.5)
    ap.add_argument("--statefulness", type=float, default=0.3)
    ap.add_argument("--coordination", type=float, default=0.3)
    ap.add_argument("--context-volume", dest="context_volume", type=float, default=0.5)
    ap.add_argument("--collision-risk", dest="collision_risk", type=float, default=0.2)
    ap.add_argument("--latency-sensitivity", dest="latency_sensitivity", type=float, default=0.5)
    ap.add_argument("--sequential", type=float, default=0.3)
    ap.add_argument("--subtask-count", dest="subtask_count", type=int)
    ap.add_argument("--prod-write", dest="prod_write", action="store_true")
    ap.add_argument("--adversarial", action="store_true")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    f = {
        "ind": args.independence, "sta": args.statefulness, "coo": args.coordination,
        "ctx": args.context_volume, "col": args.collision_risk, "lat": args.latency_sensitivity,
        "seq": args.sequential,
    }
    for k, v in f.items():
        if not 0.0 <= v <= 1.0:
            sys.exit(f"feature {k}={v} out of range [0,1]")

    gate = hard_rules(args, f)
    if gate:
        verdict, reason = gate
        print(f"VERDICT: {verdict}")
        print(f"REASON: {reason}")
        for g in GUARDRAILS.get(verdict, []):
            print(f"  - {g}")
        return

    s = score(f)
    winner = max(s, key=s.get)
    margin = s[winner] - sorted(s.values())[-2]

    if args.json:
        import json
        print(json.dumps({"task": args.task, "verdict": winner,
                          "scores": s, "margin": round(margin, 2),
                          "features": f}, indent=2))
        return

    print(f"TASK: {args.task}")
    print(f"VERDICT: {winner}  (margin {margin:.2f} over runner-up)")
    print("\nPattern scores:")
    for p in sorted(s, key=s.get, reverse=True):
        print(f"  {p:9s} {s[p]:+.2f}")
    print("\nFeature read:")
    for k, label in FEATURE_LABELS.items():
        print(f"  {f[k]:.1f}  {label}")
    print("\nGuardrails:")
    for g in GUARDRAILS[winner]:
        print(f"  - {g}")
    if margin < 0.5:
        print("\nNOTE: close margin — the feature that would flip this is the one "
              "with the largest |weight| gap between top two patterns. Re-run with "
              "that feature measured, not guessed.")


if __name__ == "__main__":
    main()
