#!/usr/bin/env python3
"""gossip-actuate.py — wire the bus corroboration tally to consequences.

The GOSSIP.md standing rule always said "1 witness = observation, 2 = pattern,
3+ = act" — bus_post.py computes the count, nothing ever ACTED on it. This
script closes that loop: zero-LLM, runs on the fleet, watches the merged bus
read, and when a thread crosses the confidence threshold it ACTS:

  1. Files a triage card (knowledge/triage/queue.jsonl, status:"open" —
     the /triage skill renders it for Josh's verdict; humans audit, the
     queue decides nothing by itself).
  2. Posts a bus announcement (agent "bus-actuator") so the network can
     see the actuation and not re-derive it.

Eligibility (documented design choice, v1):
  * kind "defect" in the thread AND corroborations >= 1 (PATTERN with an
    evidence-bearing witness from a DIFFERENT agent), or
  * any thread with corroborations >= 2 ("3+ = act": finder + 2 witnesses),
  * thread's newest post within --fresh-hours (default 48) — stale threads
    are history, actuating them files noise,
  * thread not already acted on (idempotency ledger, append-only).

Discordance (v1): a "corrigendum" from a different agent than the finder
flags the card for dissenter review (flag in the card's evidence text).
Structured corrigendum kind is the only signal trusted — keyword sniffing
on prose was rejected as too fragile.

Reads go through gossip-read.py --json (single source of truth for the
tally logic — PATTERN/OBS epistemics live there, NOT here).

Usage:
  gossip-actuate.py [--dry-run] [--since 7d] [--fresh-hours 48]
                    [--bus DIR] [--queue PATH] [--min-corroborations N]
--bus/--queue overrides exist for tests against a throwaway bus; a test
run must never touch the real queue (same contract as gossip-read's --bus).
"""

import argparse
import json
import os
import re
import subprocess
import sys
import time

K = os.path.expanduser("~/.claude/knowledge")
GOSSIP_READ = os.path.join(K, "scripts", "gossip-read.py")
BUS_POST = os.path.join(K, "scripts", "bus_post.py")
QUEUE = os.path.join(K, "triage", "queue.jsonl")
LEDGER = os.path.join(K, "dreams", "bus", "actuations.jsonl")
SELF = "bus-actuator"

sys.path.insert(0, os.path.join(K, "scripts"))
from atomic_io import atomic_append  # noqa: E402  (same flock/tmp discipline as triage-decide)


def load_events(bus_dir, since):
    cmd = ["python3", GOSSIP_READ, "--since", since, "--json"]
    if bus_dir:
        cmd += ["--bus", bus_dir]
    out = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if out.returncode != 0:
        raise SystemExit(f"gossip-read.py failed rc={out.returncode}: {out.stderr[:400]}")
    return json.loads(out.stdout)


def acted_threads(ledger_path):
    if not os.path.exists(ledger_path):
        return {}
    acted = {}
    with open(ledger_path, errors="replace") as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except Exception:
                print(f"warn: {ledger_path}:{n} unparsable, skipped", file=sys.stderr)
                continue
            acted[r.get("thread", "?")] = r
    return acted


def newest_age_hours(events):
    """Age of the thread's newest parseable-ISO post, in hours. None if none parse."""
    import datetime as dt
    newest = None
    for ev in events:
        ts = ev.get("ts")
        if not isinstance(ts, str):
            continue
        try:
            t = dt.datetime.strptime(ts[:19], "%Y-%m-%dT%H:%M:%S")
        except Exception:
            continue
        newest = t if newest is None else max(newest, t)
    if newest is None:
        return None
    now = dt.datetime.now(dt.timezone.utc).replace(tzinfo=None)
    return (now - newest).total_seconds() / 3600.0


def eligible_threads(data, fresh_hours, min_general):
    """Yield (tid, tally, events, route) for actuation-eligible threads."""
    timeline = data.get("timeline", [])
    threads = data.get("threads", {})
    per = {}
    for ev in timeline:
        tid = ev.get("thread_id") or ev.get("subject") or ev.get("thread")
        per.setdefault(tid, []).append(ev)

    for tid, t in threads.items():
        evs = per.get(tid, [])
        if not evs:
            continue
        corroborations = t.get("corroborations", 0)
        has_defect = any(e.get("kind") == "defect" for e in evs)
        if has_defect and corroborations >= 1:
            threshold = "defect>=1"
        elif corroborations >= min_general:
            threshold = f"general>={min_general}"
        else:
            continue
        age = newest_age_hours(evs)
        if age is None or age > fresh_hours:
            continue
        finder = next((e.get("agent") for e in evs if e.get("kind") == "finding"),
                      evs[0].get("agent", "?"))
        discordant = any(e.get("kind") == "corrigendum"
                         and e.get("agent") != finder for e in evs)
        route = "dissenter" if discordant else "evidence"
        yield tid, {**t, "threshold": threshold}, evs, route


def compose_card(tid, tally, evs, route):
    slug_src = re.sub(r"[^a-z0-9]+", "-", (tid or "thread").lower()).strip("-")[:40]
    slug = f"bus-act-{slug_src}-{time.strftime('%Y%m%d')}"
    finder_ev = next((e for e in evs if e.get("kind") == "defect"), evs[0])
    body = (str(finder_ev.get("line") or finder_ev.get("text")
                or finder_ev.get("note") or finder_ev.get("claim") or ""))[:300]
    refs = finder_ev.get("refs") or finder_ev.get("evidence") or []
    witnesses = sorted({e.get("agent", "?") for e in evs})
    return {
        "slug": slug,
        "kind": "bugfix" if any(e.get("kind") == "defect" for e in evs) else "build",
        "source": SELF,
        "title": f"Bus PATTERN actuation: {tid}",
        "evidence": (f"{tally['corroborations']}x evidence-bearing corroboration "
                     f"({tally['threshold']}), witnesses: {', '.join(witnesses)}. "
                     f"Opening claim: {body} Refs: {refs}"),
        "work": (f"Independent re-derivation by the evidence fleet job, then "
                 f"Josh's /triage verdict"
                 + ("" if route == "evidence" else
                    " (corrigendum in thread — dissenter review first)")),
        "points": 2,
        "status": "open",
    }


def announce(thread_id, card, queue_path, tally):
    # bus_post CLI has no --evidence flag — refs ride in claim/reason text
    cmd = ["python3", BUS_POST, "post", "--agent", SELF, "--type", "finding",
           "--subject", f"actuated:{thread_id[:60]}",
           "--claim", f"actuated: filed triage card {card['slug']} "
                      f"({tally['corroborations']}x corroboration, "
                      f"route={route_kind(card)})",
           "--reason", f"refs: {queue_path} | thread: {thread_id}"]
    out = subprocess.run(cmd, capture_output=True, text=True)
    if out.returncode != 0:
        print(f"warn: bus_post failed rc={out.returncode}: {out.stderr[:300]}",
              file=sys.stderr)


def route_kind(card):
    return "dissenter" if "dissenter" in card["work"] else "evidence"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true",
                    help="print eligible threads + composed cards, write nothing")
    ap.add_argument("--since", default="7d")
    ap.add_argument("--fresh-hours", type=float, default=48.0)
    ap.add_argument("--min-corroborations", type=int, default=2,
                    help="general-thread threshold (defect threads act at >=1)")
    ap.add_argument("--bus", default=None)
    ap.add_argument("--queue", default=None)
    ap.add_argument("--ledger", default=None)
    a = ap.parse_args()

    queue_path = a.queue or QUEUE
    ledger_path = a.ledger or LEDGER
    data = load_events(a.bus, a.since)
    acted = acted_threads(ledger_path)

    acted_count = 0
    for tid, tally, evs, route in eligible_threads(data, a.fresh_hours,
                                                   a.min_corroborations):
        if tid in acted:
            continue
        card = compose_card(tid, tally, evs, route)
        if a.dry_run:
            print(f"WOULD-ACTUATE {tid} ({tally['threshold']}, "
                  f"{tally['corroborations']}x, route={route}) -> {card['slug']}")
            continue
        atomic_append(queue_path, card)
        atomic_append(ledger_path, {
            "ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "thread": tid, "slug": card["slug"],
            "corroborations": tally["corroborations"],
            "threshold": tally["threshold"], "route": route,
        })
        if not a.queue:  # real bus announcement only on the live queue
            announce(tid, card, queue_path, tally)
        acted_count += 1
        print(f"actuated {tid} -> {card['slug']} ({tally['threshold']}, "
              f"route={route})")

    if acted_count == 0:
        print(f"bus-actuator: no eligible threads "
              f"(since={a.since}, fresh<={a.fresh_hours}h, "
              f"already-acted={len(acted)})")
    return 0


if __name__ == "__main__":
    sys.exit(main())
