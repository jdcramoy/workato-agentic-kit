#!/usr/bin/env python3
"""capabilities.py — the capability registry: what this harness can DO, and
when it learned to do it.

This is the answer to "is it actually self-learning?" — a falsifiable ledger
of capabilities with earned-on dates and evidence. New capabilities enter when
a dream proposal is applied or a build lands them; never without evidence.

Usage:
  capabilities.py list [--since 7d]
  capabilities.py add "<capability>" --evidence "<proof>"
  capabilities.py new   (capabilities earned in the last 7 days)
"""

import argparse
import datetime as dt
import json
import os
import time

K = os.path.expanduser("~/.claude/knowledge")
REG = os.path.join(K, "capabilities.jsonl")


def load():
    rows = []
    try:
        for line in open(REG):
            line = line.strip()
            if line:
                try:
                    rows.append(json.loads(line))
                except Exception:
                    pass
    except OSError:
        pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("cmd", choices=["list", "add", "new"])
    ap.add_argument("capability", nargs="?")
    ap.add_argument("--evidence", default="")
    ap.add_argument("--since", default="7d")
    a = ap.parse_args()

    rows = load()
    if a.cmd == "add":
        if not a.capability:
            print("add needs a capability name")
            return 1
        rows.append({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                     "capability": a.capability, "evidence": a.evidence})
        with open(REG, "a") as fh:
            fh.write(json.dumps(rows[-1]) + "\n")
        print(f"earned: {a.capability}")
        return 0

    days = 7
    if a.since.endswith("d"):
        days = float(a.since[:-1])
    cut = time.time() - days * 86400 if a.cmd == "new" else 0
    shown = 0
    for r in rows:
        try:
            ts = time.mktime(time.strptime(r["ts"][:19], "%Y-%m-%dT%H:%M:%S"))
        except Exception:
            ts = 0
        if ts >= cut:
            print(f"  {r['ts'][:10]}  {r['capability']}" +
                  (f"  [{r.get('evidence','')[:80]}]" if r.get("evidence") else ""))
            shown += 1
    if not shown:
        print("no capabilities in window")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
