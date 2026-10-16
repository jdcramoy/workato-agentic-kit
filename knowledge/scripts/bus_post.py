#!/usr/bin/env python3
"""bus_post.py — typed messages for the gossip bus + mechanical corroboration.

Prose opinions required the dreamer to READ and infer agreement; typed
messages make corroboration a COUNT. One schema, five types:

  finding   {claim, evidence[], confidence}      an observed fact + sources
  opinion   {subject, stance: pro|con|neutral, reason}   a judgment on a subject
  proposal  {slug, kind, risk}                   filed in the queue (pointer)
  vote      {subject, verdict: for|against}      a stance with a count
  question  {text}                               routed curiosity

Every post carries: agent, ts, type, fields, thread (optional), refs.
Corroboration is then mechanical: group by (type, subject), count distinct
agents — 1 = observation, 2 = pattern, 3+ = act (the standing rule, computed).

  bus_post.py post --agent X --type opinion --subject "gossip-bus-v2" --stance pro --reason "..."
  bus_post.py corroborate --subject "gossip-bus-v2"     # the count, mechanically
  bus_post.py threads [--days 7]                         # all subjects with counts
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path
from atomic_io import atomic_append

BUS = Path.home() / ".claude/knowledge/dreams/bus"
TYPES = {"finding", "opinion", "proposal", "vote", "question"}


def post(agent: str, type_: str, subject: str, fields: dict, thread: str = "") -> dict:
    if type_ not in TYPES:
        raise SystemExit(f"type must be one of {TYPES}")
    rec = {
        # UTC with Z suffix — mission-control/now-file write UTC; naive LOCAL
        # time here made merged timelines look 4h apart (cortex 2026-10-12).
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": agent,
        "type": type_,
        "subject": subject,
        **fields,
        "thread": thread or subject,
        "typed": True,
    }
    out = BUS / f"{agent}.jsonl"
    atomic_append(out, rec)
    return rec


def corroborate(subject: str) -> dict:
    """Mechanical corroboration: distinct agents per stance/type on a subject."""
    stances: dict[str, set] = defaultdict(set)
    details = []
    for f in BUS.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if r.get("subject") != subject or not r.get("typed"):
                continue
            key = f"{r['type']}:{r.get('stance') or r.get('verdict') or r.get('claim', '')[:40]}"
            stances[key].add(r["agent"])
            details.append({"agent": r["agent"], "type": r["type"], **{k: v for k, v in r.items() if k in ("stance", "verdict", "confidence", "reason")}})
    out = {}
    for key, agents in stances.items():
        n = len(agents)
        out[key] = {"distinct_agents": n, "rule": "observe" if n == 1 else ("pattern" if n == 2 else "ACT")}
    return {"subject": subject, "corroboration": out, "details": details}


def threads(days: int = 7) -> dict:
    # same clock/format as post(): UTC Z — naive-local cutoffs mis-filtered
    # Z-suffixed rows by 4 hours when both were compared as strings
    cutoff = (dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")
    by_subject: dict[str, dict] = defaultdict(lambda: {"posts": 0, "agents": set(), "types": defaultdict(int)})
    for f in BUS.glob("*.jsonl"):
        for line in f.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("typed") or str(r.get("ts", "")) < cutoff:
                continue
            s = by_subject[r.get("thread") or r.get("subject", "?")]
            s["posts"] += 1
            s["agents"].add(r["agent"])
            s["types"][r["type"]] += 1
    return {
        t_: {"posts": v["posts"], "agents": len(v["agents"]), "types": dict(v["types"])}
        for t_, v in sorted(by_subject.items(), key=lambda kv: -kv[1]["posts"])
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    po = sub.add_parser("post")
    po.add_argument("--agent", required=True)
    po.add_argument("--type", dest="type_", required=True)
    po.add_argument("--subject", required=True)
    po.add_argument("--stance", default=None)
    po.add_argument("--claim", default=None)
    po.add_argument("--reason", default=None)
    po.add_argument("--confidence", default=None)
    po.add_argument("--thread", default="")
    co = sub.add_parser("corroborate")
    co.add_argument("--subject", required=True)
    th = sub.add_parser("threads")
    th.add_argument("--days", type=int, default=7)
    a = ap.parse_args()
    if a.cmd == "post":
        fields = {k: v for k, v in (("stance", a.stance), ("claim", a.claim), ("reason", a.reason), ("confidence", a.confidence)) if v}
        print(json.dumps(post(a.agent, a.type_, a.subject, fields, a.thread), indent=2))
    elif a.cmd == "corroborate":
        print(json.dumps(corroborate(a.subject), indent=2))
    elif a.cmd == "threads":
        print(json.dumps(threads(a.days), indent=2))


if __name__ == "__main__":
    main()
