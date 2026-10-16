#!/usr/bin/env python3
"""asset-fingerprint.py — self-discovery of "assets we own" from the build ledger.

Reads build-ledger.jsonl airo-mutation rows (every recipe/genie/MCP the
harness has touched, server-tagged) and writes the owned-asset registry the
health sweep monitors. This is how monitoring stays self-discovering: build
something tonight, it's monitored tonight — no hand-curated list.

Designations:
  new       first touch <= 7 days ago
  hypercare prod asset touched <= 14 days ago (or any pinned asset)
  warm      touched <= 3 days ago
  stale     untouched > 30 days

Usage:
  asset-fingerprint.py            rebuild registry, print summary
  asset-fingerprint.py --json     registry as JSON
"""
import json, os, glob, datetime as dt
from collections import defaultdict

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
LEDGER = os.path.join(K, "build-ledger.jsonl")
OUT = os.path.join(K, "workato-health", "owned-registry.json")

now = dt.datetime.utcnow()


def parse_ts(ts):
    try:
        return dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00").replace("+00:00", ""))
    except Exception:
        return None


def age_days(ts):
    t = parse_ts(ts)
    if not t:
        return 999
    return (now - t).days


def main():
    recipes = {}
    genies = {}
    for line in open(LEDGER, errors="replace"):
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if r.get("kind") != "airo-mutation":
            continue
        if r.get("recipe_id"):
            rid = str(r["recipe_id"])
            d = recipes.setdefault(rid, {"asset": "recipe", "id": rid, "servers": set(),
                                         "n": 0, "first": None, "last": None, "tools": set()})
        elif r.get("tool", "").startswith("genie_") and r.get("genie_id"):
            rid = "genie:" + str(r["genie_id"])
            d = genies.setdefault(rid, {"asset": "genie", "id": str(r["genie_id"]), "servers": set(),
                                        "n": 0, "first": None, "last": None, "tools": set()})
        else:
            continue
        d["servers"].add(r.get("server", "?"))
        d["n"] += 1
        d["tools"].add(r.get("tool", ""))
        ts = r.get("ts", "")
        if not d["first"] or str(ts) < str(d["first"]):
            d["first"] = ts
        if not d["last"] or str(ts) > str(d["last"]):
            d["last"] = ts

    def flag(d):
        prod = "prod" in d["servers"]
        a_first, a_last = age_days(d["first"]), age_days(d["last"])
        tags = []
        if prod and a_last <= 14:
            tags.append("hypercare")
        if a_first <= 7:
            tags.append("new")
        if a_last <= 3:
            tags.append("warm")
        if a_last > 30:
            tags.append("stale")
        return tags or ["quiet"]

    reg = {"updated": now.isoformat() + "Z", "recipes": [], "genies": []}
    for d in list(recipes.values()) + list(genies.values()):
        entry = {"id": d["id"], "asset": d["asset"], "servers": sorted(d["servers"]),
                 "touches": d["n"], "first_touch": d["first"], "last_touch": d["last"],
                 "tools": sorted(d["tools"]), "flags": flag(d)}
        reg["recipes" if d["asset"] == "recipe" else "genies"].append(entry)
    reg["recipes"].sort(key=lambda e: e["last_touch"], reverse=True)

    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    json.dump(reg, open(OUT, "w"), indent=1)

    n_hyper = sum(1 for e in reg["recipes"] if "hypercare" in e["flags"])
    n_new = sum(1 for e in reg["recipes"] if "new" in e["flags"])
    print(f"owned-registry: {len(reg['recipes'])} recipes · {len(reg['genies'])} genies · "
          f"{n_hyper} hypercare · {n_new} new -> {os.path.relpath(OUT, HOME)}")
    for e in reg["recipes"][:8]:
        print(f'  {e["id"]} {e["flags"]} {e["servers"]} last {e["last_touch"][:16]}')


if __name__ == "__main__":
    main()
