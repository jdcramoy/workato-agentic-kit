#!/usr/bin/env python3
"""eval-run.py — the harness's fitness function.

Runs a battery of cases against the CURRENT harness configuration (the rules,
skills, and hooks as they exist today) and scores each one. This is what makes
"self-learning" falsifiable: the same cases, every run, trended over time.

Cases live in knowledge/evals/cases/<id>.json:
  {"id","prompt","graders":[{"type":"contains"|"not_contains"|"regex","value":...}],
   "notes"}

Each case spawns a bounded `claude -p` with the prompt and grades the reply.
Graders are deterministic; the LLM is the system under test, not the judge.

Usage: python3 eval-run.py [--case <id>] [--write] (write = append to
results.jsonl; default prints only)
"""

import argparse
import glob
import json
import os
import subprocess
import sys
import time

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
CASES = os.path.join(K, "evals", "cases")
RESULTS = os.path.join(K, "evals", "results.jsonl")

# source the gateway env the same way the fleet does
env = dict(os.environ)
try:
    zsh = subprocess.run(["zsh", "-c", "source ~/.zshenv 2>/dev/null; env"],
                         capture_output=True, text=True, timeout=10)
    for line in zsh.stdout.splitlines():
        if "=" in line and line.split("=", 1)[0].startswith(("ANTHROPIC", "CLAUDE")):
            k, v = line.split("=", 1)
            env[k] = v
except Exception:
    pass


def grade(out, g):
    t = g["type"]
    v = g["value"]
    if t == "contains":
        return v.lower() in out.lower()
    if t == "not_contains":
        return v.lower() not in out.lower()
    if t == "regex":
        import re
        return bool(re.search(v, out, re.I | re.S))
    return False


def run_case(case):
    t0 = time.time()
    try:
        r = subprocess.run(
            ["claude", "-p", case["prompt"]],
            capture_output=True, text=True, timeout=240, env=env)
        out = r.stdout
    except Exception as e:
        return {"id": case["id"], "pass": False, "score": 0.0,
                "error": str(e)[:200], "seconds": time.time() - t0}
    checks = [(g, grade(out, g)) for g in case["graders"]]
    score = sum(1 for _, ok in checks) / max(1, len(checks))
    return {"id": case["id"], "pass": score == 1.0, "score": round(score, 2),
            "seconds": round(time.time() - t0, 1),
            "failed": [g["value"][:60] for g, ok in checks if not ok]}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--case", default=None)
    ap.add_argument("--write", action="store_true")
    a = ap.parse_args()

    files = sorted(glob.glob(os.path.join(CASES, "*.json")))
    if a.case:
        files = [f for f in files if os.path.basename(f) == a.case + ".json"]
    if not files:
        print("no cases found in", CASES)
        return 1

    results = []
    for f in files:
        case = json.load(open(f))
        res = run_case(case)
        res["ts"] = time.strftime("%Y-%m-%dT%H:%M:%S")
        results.append(res)
        mark = "PASS" if res["pass"] else "FAIL"
        print(f"{mark} {res['score']:4.2f} {res['seconds']:5.1f}s  {res['id']}" +
              (f"  failed: {res.get('failed')}" if res.get("failed") else ""))

    total = len(results)
    passed = sum(1 for r in results if r["pass"])
    mean = sum(r["score"] for r in results) / max(1, total)
    print(f"\nfitness: {passed}/{total} pass, mean score {mean:.2f}")

    if a.write:
        os.makedirs(os.path.dirname(RESULTS), exist_ok=True)
        with open(RESULTS, "a") as fh:
            for r in results:
                fh.write(json.dumps(r) + "\n")
        print("appended to", RESULTS)
    return 0 if passed == total else 1


if __name__ == "__main__":
    sys.exit(main())
