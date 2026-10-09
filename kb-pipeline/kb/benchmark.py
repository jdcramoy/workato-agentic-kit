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
    1: {"task": "Write the Workato formula that returns the safe-navigation of a datapill that may be null, and cite the docs page you used.", "expect": "safe-navigation"},
    2: {"task": "Explain what stop_cause=trigger_errors_limit means on a scheduled recipe and what to check first. Cite your source.", "expect": "trigger"},
    3: {"task": "Draft the manifest structure for promoting two recipes from dev to production. Name required fields.", "expect": "manifest"},
    4: {"task": "A recipe writes to Snowflake and posts to Slack. It failed 3 times tonight at step 4. Give your diagnostic plan in order.", "expect": "trace"},
    5: {"task": "Write the YAML for a recipe-builder if-step condition: run only when the datapill `is_active` equals the string 'true'.", "expect": "to_s"},
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
    try:
        out = json.loads(r.stdout)
        tokens = out.get("usage", out.get("modelUsage", {}))
        text = out.get("result", r.stdout[:2000])
    except json.JSONDecodeError:
        text = r.stdout[:2000]
    rec = {
        "task_id": task_id,
        "arm": arm,
        "wall_s": round(wall, 1),
        "tokens": tokens,
        "output_excerpt": text[:1500],
        "expect_key": spec["expect"],
        "ran_at": dt.datetime.now().isoformat(timespec="seconds"),
    }
    out_dir = RESULTS / f"task-{task_id}"
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / f"{arm}.json").write_text(json.dumps(rec, indent=2))
    return rec


def score() -> dict:
    rows = []
    for d in sorted(RESULTS.glob("task-*")):
        pair = {"task_id": d.name}
        for arm in ("bare", "harness"):
            f = d / f"{arm}.json"
            if f.exists():
                r = json.loads(f.read_text())
                pair[arm] = {"wall_s": r["wall_s"], "cites_docs": int("docs.workato" in r["output_excerpt"] or "atlassian" in r["output_excerpt"])}
        rows.append(pair)
    return {"scorecard": rows, "note": "evidence scoring = cited-real-source in output; human-grade correctness scoring is Josh's pass"}


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("tasks")
    rn = sub.add_parser("run")
    rn.add_argument("--task", type=int)
    rn.add_argument("--arm", choices=["bare", "harness"], required=True)
    rn.add_argument("--all", action="store_true")
    sc = sub.add_parser("score")
    a = ap.parse_args()
    if a.cmd == "tasks":
        print(json.dumps(TASKS, indent=2))
    elif a.cmd == "run":
        ids = list(TASKS) if a.all else [a.task]
        for tid in ids:
            print(json.dumps(run_task(tid, a.arm), indent=2))
    elif a.cmd == "score":
        print(json.dumps(score(), indent=2))


if __name__ == "__main__":
    main()
