"""competence.py — the who-knows-what map: route questions by measured track record.

The fleet routes questions by fixed SOP today. This builds a measured
expertise graph: per agent (and per model lineage), accuracy per domain from
predictions + cases + proposal outcomes — so questions route to demonstrated
competence, and the division of labor emerges from evidence.

  kb competence map                 # the expertise table
  kb competence route "snowflake"   # who should answer a domain question
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

K = Path.home() / ".claude/knowledge"
PREDICTIONS = K / "dreams/predictions.jsonl"
OUTCOMES = K / "garden-reports/proposal-outcomes.jsonl"

DOMAIN_HINTS = {
    "snowflake": ["snowflake", "sql", "warehouse"],
    "slack": ["slack", "workbot", "channel"],
    "workday": ["workday", "soap", "wsdl"],
    "jira": ["jira", "bsys", "btsup"],
    "recipes": ["recipe", "formula", "datapill"],
    "confluence": ["confluence", "wiki"],
}


def domain_of(text: str) -> str:
    low = text.lower()
    for domain, keys in DOMAIN_HINTS.items():
        if any(k in low for k in keys):
            return domain
    return "general"


def build_map() -> dict:
    from collections import defaultdict

    score: dict[str, dict[str, dict]] = defaultdict(lambda: defaultdict(lambda: {"ok": 0, "n": 0}))
    if PREDICTIONS.exists():
        for line in PREDICTIONS.read_text().splitlines():
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            if not r.get("verdict"):
                continue
            agent = r.get("agent", "?")
            dom = domain_of(r.get("action", ""))
            score[agent][dom]["n"] += 1
            if r["verdict"] == "matched":
                score[agent][dom]["ok"] += 1
    # proposal acceptance attributed to the dreamers (per model when frontmatter lands)
    if OUTCOMES.exists():
        for line in OUTCOMES.read_text().splitlines():
            try:
                o = json.loads(line)
            except json.JSONDecodeError:
                continue
            act = o.get("action", "")
            dom = domain_of(o.get("proposal", ""))
            score["dreamers"][dom]["n"] += 1
            if act in ("accepted", "built", "accepted-modified"):
                score["dreamers"][dom]["ok"] += 1
    out = {}
    for agent, domains in score.items():
        out[agent] = {
            dom: {"n": v["n"], "rate": round(v["ok"] / v["n"], 3) if v["n"] else None}
            for dom, v in domains.items()
        }
    return {"built": dt.datetime.now().isoformat(timespec="seconds"), "map": out}


def route(domain: str) -> dict:
    m = build_map()["map"]
    ranked = []
    for agent, domains in m.items():
        d = domains.get(domain, {})
        if d.get("rate") is not None:
            ranked.append((d["rate"], d["n"], agent))
    ranked.sort(reverse=True)
    return {
        "domain": domain,
        "routing": [{"agent": a, "rate": r, "n": n} for r, n, a in ranked[:3]],
        "note": "route to the top when n>=3; otherwise rotate (the map is still learning)",
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("map")
    rt = sub.add_parser("route")
    rt.add_argument("domain")
    a = ap.parse_args()
    if a.cmd == "map":
        print(json.dumps(build_map(), indent=2))
    elif a.cmd == "route":
        print(json.dumps(route(a.domain), indent=2))
