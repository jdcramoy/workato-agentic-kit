#!/usr/bin/env python3
"""gym.py — the replay gym (accepted proposal 2026-10-07-replay-gym).

Nightly read-only assertions that the HARNESS still behaves the way the
playbooks say it does — catching harness regressions before Josh does.
Runs from fleet job `gym` (com.josh.fleet.gym, 00:15 nightly).

Assertions (each independent, all read-only):
  A1 heartbeat-contract   every heartbeat-contract fleet job checked in on window
  A2 proposal-file-gate   latest dream's inventions all have proposal files
  A3 guardrails-installed  prod-write gate + lint + digest hooks present in settings
  A4 fleet-prompt-integrity  every fleet prompt exists, references known agents
  A5 bus-liveness         >=1 agent posted to the bus in 24h (warn-only)
  A6 science-layer        cases/curiosity/gym state fresh (<36h)

A failure -> canon entry (regression-canon/gym-canon.jsonl) + triage finding
+ bus post (thread: gym). Exit 0 always; the log line is the verdict.

Usage: gym.py [--json]
"""
import json, os, glob, subprocess, sys, datetime as dt, re
from atomic_io import atomic_append

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
CANON = os.path.join(K, "regression-canon", "gym-canon.jsonl")
QUEUE = os.path.join(K, "triage", "queue.jsonl")
BUS = os.path.join(K, "dreams", "bus", "gym.jsonl")
LOG = os.path.join(HOME, ".local", "state", "fleet", "gym.log")


def log(msg):
    try:
        with open(LOG, "a") as fh:
            fh.write(f"{dt.datetime.now(dt.timezone.utc).isoformat()} {msg}\n")
    except OSError:
        pass


def canon_append(a):
    atomic_append(CANON, {"found": dt.date.today().isoformat(), **a})


def triage_append(a):
    atomic_append(QUEUE, {"ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                          "source": "gym", "kind": "bugfix", "points": 2,
                          "status": "open", **a})


def bus_post(line):
    atomic_append(BUS, {"ts": dt.datetime.now(dt.timezone.utc).isoformat(),
                        "agent": "gym", "kind": "finding",
                        "thread_id": "gym", "line": line})


def a1_heartbeat_contract():
    """Fleet jobs with a heartbeat contract checked in within their window."""
    sys.path.insert(0, os.path.join(HOME, ".claude", "knowledge", "scripts"))
    import brain_dashboard as bd
    bad = [t for t in bd.timers() if t["state"] in ("late", "overdue")]
    return ("fail" if bad else "pass",
            [f'{t["name"]}: {t["detail"]}' for t in bad])


def a2_proposal_file_gate():
    r = subprocess.run(["python3", os.path.join(HOME, ".claude", "knowledge",
                                                "scripts", "proposal-pipeline.py"), "--json"],
                       capture_output=True, text=True, timeout=15)
    c = json.loads(r.stdout).get("counts", {})
    inv = c.get("dream_inventions", 0)
    dream_file = c.get("dream_file", "")  # e.g. 2026-10-07.md
    dream_date = dream_file[:10]
    same_day = glob.glob(os.path.join(K, "dreams", "proposals", f"{dream_date}*.md"))
    if inv > 0 and not same_day:
        return ("fail", [f"dream {dream_file} has {inv} inventions, no proposal file dated {dream_date}"])
    return ("pass", [f"dream {dream_file}: {inv} inventions, {len(same_day)} proposal files filed"])


def a3_guardrails_installed():
    s = json.load(open(os.path.join(HOME, ".claude", "settings.json")))
    blob = json.dumps(s)
    need = {"prod-write gate": "PROD WRITE" in open(os.path.join(
        HOME, "mods", "workato-guardrails", "hooks", "register.js")).read(),
        "lint hook": "lint-changed" in blob,
        "digest hook": "morning-digest" in blob}
    bad = [k for k, v in need.items() if not v]
    return ("fail" if bad else "pass", bad or ["all hooks present"])


def a4_fleet_prompt_integrity():
    jobs = glob.glob(os.path.join(HOME, ".local", "bin", "fleet", "jobs", "*.prompt"))
    agents = {os.path.basename(p)[:-3] for p in glob.glob(os.path.join(HOME, ".claude", "agents", "*.md"))}
    bad = []
    for j in jobs:
        body = open(j, errors="replace").read().strip()
        if not body:
            bad.append(f"{os.path.basename(j)} is EMPTY")
            continue
        # anchor on real dispatch idioms only (subagent_type X / "the X agent type");
        # bare "<word> agent" prose false-positives (e.g. "UAT sweep agent")
        for m1, m2 in re.findall(r"subagent_type[:\s]+([a-z][a-z0-9-]+)|\bthe\s+([a-z][a-z0-9-]+)\s+agent\s+type\b", body):
            m = m1 or m2
            if m and m not in agents and m not in ("the", "a", "general-purpose"):
                bad.append(f"{os.path.basename(j)} references unknown agent '{m}'")
    return ("fail" if bad else "pass", bad or [f"{len(jobs)} prompts ok"])


def a5_bus_liveness():
    cut = dt.datetime.now(dt.timezone.utc).timestamp() - 86400
    alive = set()
    for f in glob.glob(os.path.join(K, "dreams", "bus", "*.jsonl")):
        for line in open(f, errors="replace"):
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            try:
                ts = dt.datetime.fromisoformat(str(e.get("ts", "")).replace("Z", "+00:00")).timestamp()
            except Exception:
                continue
            if ts >= cut:
                alive.add(e.get("agent", "?"))
    return ("warn" if not alive else "pass",
            ["bus silent 24h — network health check"] if not alive else [f"{len(alive)} agents alive"])


def main():
    checks = {"A1-heartbeat-contract": a1_heartbeat_contract,
              "A2-proposal-file-gate": a2_proposal_file_gate,
              "A3-guardrails-installed": a3_guardrails_installed,
              "A4-fleet-prompt-integrity": a4_fleet_prompt_integrity,
              "A5-bus-liveness": a5_bus_liveness,
              "A6-science-layer": check_a6}
    results = {}
    fails = []
    for name, fn in checks.items():
        try:
            verdict, detail = fn()
        except Exception as e:
            verdict, detail = "error", [f"{type(e).__name__}: {e}"]
        results[name] = {"verdict": verdict, "detail": detail}
        if verdict == "fail":
            fails.append((name, detail))

    for name, detail in fails:
        slug = f"gym-{name.lower()}"
        canon_append({"assertion": name, "status": "open", "detail": "; ".join(detail)[:200]})
        triage_append({"slug": slug, "title": f"GYM FAIL: {name} — {'; '.join(detail)[:120]}",
                       "evidence": f"gym.py::{name} @ {dt.datetime.now(dt.timezone.utc).isoformat()}"})
    if fails:
        bus_post(f"gym: {len(fails)} assertion(s) failed: " + ", ".join(n for n, _ in fails))
    verdict_line = (f"gym: {len(results) - len(fails)}/{len(results)} pass"
                    + (f" | FAILED: {', '.join(n for n, _ in fails)}" if fails else " | harness invariants hold"))
    log(verdict_line)
    atomic_append(os.path.join(K, "garden-reports", "heartbeat.jsonl"),
                  {"ts": dt.datetime.now(dt.timezone.utc).isoformat(), "job": "gym"})
    print(json.dumps(results, indent=1) if "--json" in sys.argv else verdict_line)


# A6 science-layer liveness (added 2026-10-09): cases/curiosity/coverage
def check_a6():
    import os
    sci = os.path.expanduser("~/.claude/workato-kb/science-state.json")
    if not os.path.exists(sci):
        return ("fail", ["no science-state.json — nightly sync's science stage missing"])
    import json, datetime as dt
    s = json.load(open(sci))
    age_h = (dt.datetime.now() - dt.datetime.fromisoformat(s["updated"])).total_seconds() / 3600
    ok = age_h < 36
    detail = f"state age {age_h:.0f}h; cases={s['cases'].get('cases')}, curiosity_open={s['curiosity_open']}"
    return (("pass" if ok else "fail"), [detail])


if __name__ == "__main__":
    main()
