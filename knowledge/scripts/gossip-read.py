#!/usr/bin/env python3
"""gossip-read.py — merged read view of the agent gossip bus.

Each agent writes ONLY its own outbox: knowledge/dreams/bus/<agent>.jsonl.
This script merges all outboxes, sorts by time, tallies corroborations per
thread, applies TTL expiry, and prints the timeline (or thread/agent slices).

Usage:
  gossip-read.py [--since 24h|7d|all] [--thread SLUG] [--agent NAME] [--json]
"""

import argparse
import glob
import json
import os
import sys
import time

BUS = os.path.expanduser("~/.claude/knowledge/dreams/bus")
VALID_KINDS = ("finding", "verify", "handoff", "proposal-ref")


def parse_since(s):
    if not s or s == "all":
        return 0
    if s.endswith("h"):
        return time.time() - float(s[:-1]) * 3600
    if s.endswith("d"):
        return time.time() - float(s[:-1]) * 86400
    return time.time() - float(s) * 86400


def _ts(ts):
    try:
        return time.mktime(time.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S"))
    except Exception:
        return 0.0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--since", default="24h")
    ap.add_argument("--thread", default=None)
    ap.add_argument("--agent", default=None)
    ap.add_argument("--json", action="store_true")
    a = ap.parse_args()

    cutoff = parse_since(a.since)
    now = time.time()
    events = []
    for path in sorted(glob.glob(os.path.join(BUS, "*.jsonl"))):
        agent_file = os.path.splitext(os.path.basename(path))[0]
        if a.agent and agent_file != a.agent:
            continue
        try:
            with open(path, errors="replace") as fh:
                for n, line in enumerate(fh, 1):
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        print(f"warn: {os.path.basename(path)}:{n} unparsable",
                              file=sys.stderr)
                        continue
                    ev.setdefault("agent", agent_file)
                    events.append(ev)
        except OSError as e:
            print(f"warn: cannot read {path}: {e}", file=sys.stderr)

    # TTL expiry (skip events older than their ttl)
    fresh = []
    for ev in events:
        if not isinstance(ev.get("ts"), str):
            fresh.append(ev)
            continue
        ts = _ts(ev["ts"])
        if now - ts <= ev.get("ttl_days", 14) * 86400:
            fresh.append(ev)
    events = [e for e in fresh
              if not isinstance(e.get("ts"), str)
              or _ts(e.get("ts")) >= cutoff]

    # corroboration tally per thread
    tallies = {}
    for ev in events:
        tid = ev.get("thread_id") or ev.get("subject")
        if tid:
            tallies.setdefault(tid, {"corroborations": 0, "witnesses": set(),
                                     "subject": ev.get("subject", tid)})
            if ev.get("kind") == "verify":
                tallies[tid]["corroborations"] += 1
            tallies[tid]["witnesses"].add(ev.get("agent", "?"))
    for tid, t in tallies.items():
        t["witness_count"] = len(t["witnesses"])

    if a.thread:
        events = [e for e in events
                  if e.get("thread_id") == a.thread or e.get("subject") == a.thread]

    events.sort(key=lambda e: e.get("ts", ""))
    if a.json:
        print(json.dumps({"timeline": events, "threads": {
            k: {**v, "witnesses": sorted(v["witnesses"])}
            for k, v in sorted(tallies.items(),
                               key=lambda kv: (-kv[1]["corroborations"],
                                               -kv[1]["witness_count"]))}},
            indent=1))
        return 0

    if not events:
        print("the bus is quiet (no events in window)")
        return 0

    for ev in events:
        print(f'{ev["ts"][:16]} [{ev.get("agent", "?"):22}] '
              f'{ev.get("kind", "?"):12} {ev.get("subject", "?"):28} '
              f'{ev.get("line", "")[:110]}')
    print()
    print("threads by corroboration:")
    for tid, t in sorted(tallies.items(),
                         key=lambda kv: (-kv[1]["corroborations"],
                                         -kv[1]["witness_count"]))[:10]:
        tag = "PATTERN " if t["corroborations"] >= 1 or t["witness_count"] >= 2 else "solo    "
        print(f'  {tag} {t["corroborations"]}x  {t["witness_count"]} witnesses  '
              f'{tid[:60]}')
    return 0


if __name__ == "__main__":
    sys.exit(main())
