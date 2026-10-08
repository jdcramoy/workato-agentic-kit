#!/usr/bin/env python3
"""rehearsal.py — the rehearsal cortex: counterfactual replay before a build.

Friston's generative model, made operational: before a consequential change
to a recipe, the harness rehearses the change against the recipe's OWN recent
history and reports what WOULD have happened differently.

Mechanism (honest about what replay can and cannot do):
  1. Enumerate the recipe's last N jobs (wt jobs list) and capture each job's
     trigger input as a fixture (wt jobs get).
  2. Counterfactual stage (requires the proposed change as a testable recipe
     version): create/parametrize test cases with those fixtures and run them
     against the candidate version (wt testcases run) — then diff per-fixture:
     historical outcome vs rehearsal outcome.
  3. Report: N rehearsed, M identical outcomes, K divergent (the interesting
     ones — the change would have changed history), plus explicit coverage
     limits (external side effects re-fire; fixtures are cached trigger data).

Modes tonight: --stage fixtures proves extraction on a real dev recipe without
touching anything. The counterfactual stage activates when a real build
supplies a candidate version — the queued liveness-sentinel build is its
first customer.

  rehearsal.py plan --recipe <id> [-n 10]      # rehearsal plan: fixtures + limits
  rehearsal.py fixtures --recipe <id> [-n 5]   # extract + store trigger fixtures
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
from pathlib import Path

K = Path.home() / ".claude/knowledge"
REHEARSALS = K / "dreams/rehearsals"


def _wt(*args: str) -> dict | list:
    out = subprocess.run(["wt", *args], capture_output=True, text=True)
    if out.returncode != 0:
        raise RuntimeError(f"wt {args[0]} failed: {out.stderr[:200]}")
    return json.loads(out.stdout)


def fixtures(recipe_id: int, n: int = 5) -> dict:
    jobs = _wt("jobs", "list", str(recipe_id), "--raw")
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", jobs.get("items", []))
    taken = jobs[:n]
    out_dir = REHEARSALS / str(recipe_id)
    out_dir.mkdir(parents=True, exist_ok=True)
    manifest = []
    for j in taken:
        jid = str(j.get("id") or j.get("job_id"))
        detail = _wt("jobs", "get", str(recipe_id), jid)
        # trigger input lives in the first job line's input (the trigger step)
        lines = detail.get("lines") or []
        trigger_input = (lines[0].get("input") if lines and isinstance(lines[0], dict) else None)
        fpath = out_dir / f"fixture-{jid}.json"
        fpath.write_text(
            json.dumps(
                {
                    "job_id": jid,
                    "historical_status": j.get("status"),
                    "trigger_input": trigger_input,
                    "trigger_adapter": (lines[0].get("adapter_name") if lines else None),
                    "full_lines": lines,
                },
                indent=2,
            )
        )
        manifest.append(
            {
                "job_id": jid,
                "status": j.get("status"),
                "fixture": str(fpath),
                "has_trigger_data": trigger_input is not None,
            }
        )
    summary = {
        "recipe": recipe_id,
        "rehearsal_window": f"last {len(taken)} jobs of {len(jobs)}",
        "fixtures_extracted": sum(1 for m in manifest if m["has_trigger_data"]),
        "limit_note": "fixtures are cached trigger data; external side effects re-fire "
        "in any replay — rehearsal proves OUTCOME deltas, not side-effect safety",
        "manifest": manifest,
    }
    (out_dir / "manifest.json").write_text(json.dumps(summary, indent=2))
    return summary


def plan(recipe_id: int, n: int = 10) -> dict:
    jobs = _wt("jobs", "list", str(recipe_id), "--raw")
    if isinstance(jobs, dict):
        jobs = jobs.get("jobs", jobs.get("items", []))
    recent = jobs[:n]
    fail = sum(1 for j in recent if j.get("status") == "failed")
    return {
        "recipe": recipe_id,
        "rehearse_n": len(recent),
        "historical_failures_in_window": fail,
        "counterfactual_question": "of these jobs, which would have produced a DIFFERENT "
        "outcome under the proposed change — and are the divergences improvements?",
        "stages": [
            "1. fixtures: extract trigger data per job (rehearsal.py fixtures)",
            "2. candidate: the proposed change as a testable recipe version (dev)",
            "3. replay: test cases per fixture against the candidate (wt testcases)",
            "4. diff: historical vs rehearsed outcomes — divergences are the report",
        ],
        "guard": "dev only; production rehearsal keeps its standing sign-off gate",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    fx = sub.add_parser("fixtures")
    fx.add_argument("--recipe", type=int, required=True)
    fx.add_argument("-n", type=int, default=5)
    pl = sub.add_parser("plan")
    pl.add_argument("--recipe", type=int, required=True)
    pl.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "fixtures":
        print(json.dumps(fixtures(a.recipe, a.n), indent=2))
    elif a.cmd == "plan":
        print(json.dumps(plan(a.recipe, a.n), indent=2))
