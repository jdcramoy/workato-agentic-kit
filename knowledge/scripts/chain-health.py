#!/usr/bin/env python3
"""chain-health.py — nightly-chain power tripwire (READ-ONLY, approved 2026-10-26).

Proposal: dreams/proposals/2026-10-19-night-chain-power-tripwire.md (accepted;
built 2026-10-26 by the mechanical-verdict run). The nightly chain silently
skips when the Mac is off/asleep — no error, no trace. This script attributes
a missed job to POWER-OFF (machine asleep/off during the expected firing,
pmset evidence) vs JOB-DEAD (machine up, no heartbeat).

For each fleet job:
  1. last heartbeat ts from garden-reports/heartbeat.jsonl (JSON-parsed, never
     spaced-literal grepped — 2026-10-20 heartbeat-selfcheck-grep-fragility).
  2. heartbeat age > 2x schedule interval -> CHAIN-STALE <job> <hours>h.
  3. On stale: cross-check `pmset -g log` for a Sleep/Wake window covering the
     expected firing and emit POWER-OFF (window found) or JOB-DEAD (machine up).

The output states the window found, not a verdict — the reader decides
(proposal dissent, pre-answered). Read-only: no writes, no bus posts, no cron.
Cortex pulse / morning brief invoke it as a lookup.

Usage: python3 chain-health.py [--all]   (default: only stale jobs shown)
Rollback: delete this file. No state is modified.
"""
import json
import os
import subprocess
import sys
import datetime as dt

K = os.path.expanduser("~/.claude/knowledge")
HEARTBEAT = os.path.join(K, "garden-reports", "heartbeat.jsonl")

# job -> schedule interval in hours (heartbeat-freshness budget).
# Age threshold = 2x interval per the proposal.
SCHEDULE_H = {
    "cortex": 2, "session-shadow": 2, "ops-visibility": 2, "bus-actuate": 2,
    "workato-health": 2, "brain-dashboard": 2,
    "docs-watch": 26, "gardener": 26, "brain-gardener": 26,
    "watchdog": 26, "workato-watchdog": 26, "harness-health": 26,
    "harness-backup": 26, "backup": 26, "healer": 26,
    "dreamer": 26, "project-dreamer": 26, "value-ledger": 26,
    "instruction-miner": 26, "evidence": 26, "morning-brief": 26, "brief": 26,
    "loadout": 26, "decision-inbox": 26, "ops-autopsy": 26,
    "uat-sweep": 26, "harness-fix": 26, "harness-docs-sync": 26,
    "synaptic-strength": 26, "index-budget": 26, "titer-report": 26,
    "replay-sample": 26, "cost-governor": 26, "wave3-nightly": 26,
    "frontier-nightly": 26, "autonomy-nightly": 26, "restore-drill": 26,
    "effdash": 26, "regression": 26, "kb-audit": 26, "queue-drift": 50,
    "corpus": 170, "roi-weekly": 170, "estate-architect": 170,
    "kb-corpus-sync": 170, "knowledge-corpus-sync": 170,
    "jira-triage": 26, "jira-triage-fleet": 170, "command-canary": 50,
    "canary": 50, "board-minutes": 170, "minutes": 170, "architect": 170,
    "replay-gym": 26, "gym": 26, "turn-audit": 50,
    "watchdog-liveness": 12,
}


def last_heartbeats():
    jobs = {}
    with open(HEARTBEAT, errors="replace") as fh:
        for line in fh:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            job, ts = row.get("job"), row.get("ts")
            if job and ts:
                jobs[job] = ts
    return jobs


def parse_ts(ts):
    ts = str(ts).replace("Z", "+00:00")
    try:
        t = dt.datetime.fromisoformat(ts)
    except ValueError:
        return None
    if t.tzinfo is None:
        t = t.replace(tzinfo=dt.timezone.utc)
    return t


def pmset_off_window(start_utc, end_utc):
    """True if a sleep/wake boundary pair covers [start,end] (UTC datetimes)."""
    try:
        out = subprocess.run(["pmset", "-g", "log"], capture_output=True,
                             text=True, timeout=20).stdout
    except Exception:
        return False
    sleeps, wakes = [], []
    for line in out.splitlines():
        if "Entering Sleep" in line:
            t = parse_pmset(line)
            if t:
                sleeps.append(t)
        elif "Wake from" in line:
            t = parse_pmset(line)
            if t:
                wakes.append(t)
    for s in sleeps:
        after = [w for w in wakes if w > s]
        if not after:
            continue
        w = min(after)
        if s <= start_utc and w >= end_utc:
            return True
    return False


def parse_pmset(line):
    # "2026-10-20 01:16:05 -0700 ..." style prefix
    try:
        date_s = " ".join(line.split()[:3])
        return dt.datetime.strptime(date_s, "%Y-%m-%d %H:%M:%S %z").astimezone(dt.timezone.utc)
    except (ValueError, IndexError):
        return None


def main():
    show_all = "--all" in sys.argv
    now = dt.datetime.now(dt.timezone.utc)
    jobs = last_heartbeats()
    stale = 0
    for job, interval in sorted(SCHEDULE_H.items()):
        ts = jobs.get(job)
        if not ts:
            print(f"NO-HEARTBEAT {job}")
            stale += 1
            continue
        t = parse_ts(ts)
        if not t:
            continue
        age_h = (now - t).total_seconds() / 3600.0
        if age_h <= 2 * interval:
            if show_all:
                print(f"OK {job} last={ts} age={age_h:.1f}h")
            continue
        expected_fire = now - dt.timedelta(hours=age_h)
        attribution = "POWER-OFF" if pmset_off_window(t, now) else "JOB-DEAD"
        print(f"CHAIN-STALE {job} {age_h:.1f}h (budget {2*interval}h) "
              f"last={ts} -> {attribution}")
        stale += 1
    print(f"--- {stale} flagged job(s), {len(jobs)} heartbeats read")


if __name__ == "__main__":
    main()
