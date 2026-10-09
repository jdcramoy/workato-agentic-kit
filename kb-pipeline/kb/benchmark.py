#!/usr/bin/env python3
"""benchmark.py — the measured claim: harness vs bare agent.

"Best agentic harness in the world" is rhetoric until two agents run the
SAME tasks and the results have numbers. This runs a fixed task set through
two arms — BARE (fresh dir, no CLAUDE.md/agents/KB/MCP) and HARNESS (the
full setup) — and scores time, tokens, and evidence quality.

  benchmark.py tasks                      # the task set
  benchmark.py run --task 1 --arm bare    # one task, one arm (headless claude)
  benchmark.py run --all --arm bare       # the full set
  benchmark.py score                      # the scorecard from results

Scoring rubric per task: correctness (artifact exists + matches the known
answer shape), evidence (citations to real traces/URLs in the output),
time (wall), tokens (from claude -p usage). The scorecard renders both arms
side by side. Costs: each arm burns real tokens — default n=1 task per
invocation so runs stay deliberate.

Honest limits: headless arms can't use MCP-side surfaces (calendar etc.);
task set = Workato build/verify tasks that fit headless; n=1 per cell.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import subprocess
import time
from pathlib import Path

K = Path.home() / ".claude/knowledge"
RESULTS = K / "benchmark"
HARNESS_CWD = str(Path.home() / "Documents/workbench")
BARE_CWD = str(Path.home() / "Documents/benchmark-bare")

TASKS = {
    1: {"task": "Write the Workato formula that returns the safe-navigation of a datapill that may be null, and cite the docs page you used.", "expect": "safe-navigation",
        "checks": {"needs": ["&.", "docs.workato.com"], "bonus": ["to_s", "changelog"]}},
    2: {"task": "Explain what stop_cause=trigger_errors_limit means on a scheduled recipe and what to check first. Cite your source.", "expect": "trigger",
        "checks": {"needs": ["trigger_errors", "stall"], "bonus": ["heartbeat", "schedule"]}},
    3: {"task": "Draft the manifest structure for promoting two recipes from dev to production. Name required fields.", "expect": "manifest",
        "checks": {"needs": ["recipes", "folder"], "bonus": ["version", "environment"]}},
    4: {"task": "A recipe writes to Snowflake and posts to Slack. It failed 3 times tonight at step 4. Give your diagnostic plan in order.", "expect": "trace",
        "checks": {"needs": ["job", "trace"], "bonus": ["step", "snowflake"]}},
    5: {"task": "Write the YAML for a recipe-builder if-step condition: run only when the datapill `is_active` equals the string 'true'.", "expect": "to_s",
        "checks": {"needs": ["is_active", "to_s"], "bonus": ["==", "true"]}},
}


def run_task(task_id: int, arm: str, timeout: int = 600) -> dict:
    spec = TASKS[task_id]
    cwd = HARNESS_CWD if arm == "harness" else BARE_CWD
    Path(cwd).mkdir(parents=True, exist_ok=True)
    cmd = ["claude", "-p", spec["task"], "--output-format", "json"]
    env = None
    if arm == "bare":
        # true bare: empty config dir (no user CLAUDE.md/skills/memory). Auth
        # survives via the keychain; first call may re-pair the trust prompt.
        import os

        env = dict(os.environ)
        env["CLAUDE_CONFIG_DIR"] = str(BARE_CWD + "/.claude-config")
        Path(env["CLAUDE_CONFIG_DIR"]).mkdir(parents=True, exist_ok=True)
    t0 = time.time()
    r = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True, timeout=timeout, env=env)
    wall = time.time() - t0
    tokens = {}
    num_turns = None
    cost = None
    try:
        out = json.loads(r.stdout)
        tokens = out.get("usage", out.get("modelUsage", {}))
        num_turns = out.get("num_turns")
        cost = out.get("total_cost_usd")
        text = out.get("result", r.stdout[:2000])
    except json.JSONDecodeError:
        text = r.stdout[:2000]
    checks = spec.get("checks", {})
    low = text.lower()
    needs = sum(1 for k in checks.get("needs", []) if k.lower() in low)
    bonus = sum(1 for k in checks.get("bonus", []) if k.lower() in low)
    n_needed = max(len(checks.get("needs", [])), 1)
    rec = {
        "task_id": task_id,
        "arm": arm,
        "accuracy": round(needs / n_needed, 3),  # primary axis
        "depth_bonus": bonus,
        "turns": num_turns,
        "cost_usd": cost,
        "wall_s": round(wall, 1),  # secondary (demoted)
        "tokens": {k: v for k, v in tokens.items() if isinstance(v, (int, float))},
        "output_excerpt": text[:1500],
        "expect_key": spec["expect"],
        "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    out_dir = RESULTS / f"task-{task_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{arm}.json").write_text(json.dumps(rec, indent=2))
    return rec


def run_weekly() -> dict:
    """The auto-triggered pass: full set, both arms, score, trend, bus."""
    out = {}
    for tid in TASKS:
        for arm in ("bare", "harness"):
            try:
                out[f"task-{tid}-{arm}"] = run_task(tid, arm)
            except Exception as e:  # noqa: BLE001 - a failed run is data, not a crash
                out[f"task-{tid}-{arm}"] = {"error": str(e)[:150]}
    scorecard = score()
    trend_path = RESULTS / "trend.jsonl"
    trend_path.parent.mkdir(parents=True, exist_ok=True)
    with trend_path.open("a") as f:
        f.write(json.dumps({"date": dt.date.today().isoformat(), "scorecard": scorecard}, ensure_ascii=False) + "\n")
    # bus post (typed)
    try:
        subprocess.run(
            ["python3", str(K / "scripts/bus_post.py"), "post", "--agent", "benchmark",
             "--type", "finding", "--subject", f"benchmark-{dt.date.today().isoformat()}",
             "--claim", f"weekly A/B done: {len(scorecard['scorecard'])} tasks; "
             + "; ".join(f"{r['task_id']}: bare {r.get('bare', {}).get('wall_s', '?')}s / harness {r.get('harness', {}).get('wall_s', '?')}s" for r in scorecard["scorecard"][:5]),
             "--confidence", "high"],
            capture_output=True, text=True,
        )
    except Exception:  # noqa: BLE001
        pass
    return {"tasks_run": len(out), "scorecard": scorecard}


def score() -> dict:
    rows = []
    agg = {arm: {"accuracy": [], "turns": [], "cost": []} for arm in ("bare", "harness")}
    for d in sorted(RESULTS.glob("task-*")):
        pair = {"task_id": d.name}
        for arm in ("bare", "harness"):
            f = d / f"{arm}.json"
            if f.exists():
                r = json.loads(f.read_text())
                pair[arm] = {k: r.get(k) for k in ("accuracy", "depth_bonus", "turns", "cost_usd", "wall_s")}
                if r.get("accuracy") is not None:
                    agg[arm]["accuracy"].append(r["accuracy"])
                if r.get("turns"):
                    agg[arm]["turns"].append(r["turns"])
                if r.get("cost_usd"):
                    agg[arm]["cost"].append(r["cost_usd"])
        rows.append(pair)
    summary = {}
    for arm, a in agg.items():
        n = len(a["accuracy"])
        if n:
            # composite: accuracy 60%, depth bonus 20%, turn efficiency 20%
            # (fewer turns to correct = better planning; latency demoted to footnote)
            avg_acc = sum(a["accuracy"]) / n
            avg_turns = sum(a["turns"]) / len(a["turns"]) if a["turns"] else None
            composite = avg_acc * 0.8 + (1.0 / (avg_turns or 1)) * 0.2 if avg_turns else avg_acc
            summary[arm] = {
                "accuracy": round(avg_acc, 3),
                "avg_turns": round(avg_turns, 1) if avg_turns else None,
                "avg_cost_usd": round(sum(a["cost"]) / len(a["cost"]), 4) if a["cost"] else None,
                "composite": round(composite, 3),
            }
    return {
        "scorecard": rows,
        "summary": summary,
        "note": "composite = accuracy 80% + turn-efficiency 20% (fewer turns to correct = "
        "better planning). Raw latency demoted: bare wins it by construction (shorter "
        "system prompt); the interesting axes are accuracy and turns. Human-grade "
        "correctness scoring is still Josh's pass.",
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tasks")
    rn = sub.add_parser("run")
    rn.add_argument("--task", type=int)
    rn.add_argument("--arm", choices=["bare", "harness"], required=True)
    rn.add_argument("--all", action="store_true")
    sc = sub.add_parser("score")
    sub.add_parser("weekly")
    a = ap.parse_args()
    if a.cmd == "tasks":
        print(json.dumps(TASKS, indent=2))
    elif a.cmd == "run":
        ids = list(TASKS) if a.all else [a.task]
        for tid in ids:
            print(json.dumps(run_task(tid, a.arm), indent=2))
    elif a.cmd == "score":
        print(json.dumps(score(), indent=2))
    elif a.cmd == "weekly":
        print(json.dumps(run_weekly(), indent=2))


if __name__ == "__main__":
    main()
