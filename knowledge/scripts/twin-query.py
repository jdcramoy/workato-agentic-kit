#!/usr/bin/env python3
"""Twin query: offline questions against the twin snapshot (knowledge/twin/v1).

Zero network, zero LLM. Every answer prints the snapshot age. If the snapshot
is older than 24h the query REFUSES (exit 1, "TWIN STALE (>24h)") unless
--allow-stale is passed — refresh with twin-snapshot.py.

Commands:
  twin-query.py deps <connection-or-adapter-name>   # which recipes use it
  twin-query.py stale [--days 90]                   # recipes not updated in N days
  twin-query.py recipes --folder <ID>               # recipes in a folder
  twin-query.py running                             # the live scheduler set
  twin-query.py summary                             # estate overview
"""
import argparse, json, os, sys, time
from datetime import datetime, timezone

TWIN_DIR = os.path.expanduser("~/.claude/knowledge/twin/v1")
MAX_AGE_H = 24


def load_twin():
    meta_path = os.path.join(TWIN_DIR, "meta.json")
    if not os.path.exists(meta_path):
        sys.exit(f"no twin found at {TWIN_DIR} — run twin-snapshot.py first")
    meta = json.load(open(meta_path))
    recipes = [json.loads(l) for l in open(os.path.join(TWIN_DIR, "recipes.jsonl")) if l.strip()]
    conns = [json.loads(l) for l in open(os.path.join(TWIN_DIR, "connections.jsonl")) if l.strip()]
    sched = [json.loads(l) for l in open(os.path.join(TWIN_DIR, "schedulers.jsonl")) if l.strip()]
    return meta, recipes, conns, sched


def check_freshness(meta, allow_stale):
    """Print snapshot age on every answer; gate on >24h staleness."""
    snap = datetime.strptime(meta["snapshot_at"], "%Y-%m-%dT%H:%M:%S%z")
    age_h = (datetime.now(snap.tzinfo) - snap).total_seconds() / 3600
    env = meta.get("workato_env", "?")
    print(f"snapshot: {meta['snapshot_at']} env={env} age={age_h:.1f}h "
          f"(recipes={meta['counts']['recipes']}, connections={meta['counts']['connections']}, "
          f"running={meta['counts']['schedulers_running']})")
    if age_h > MAX_AGE_H and not allow_stale:
        print(f"TWIN STALE (>24h) — refresh with: twin-snapshot.py  (or pass --allow-stale to answer anyway)")
        sys.exit(1)
    return age_h


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.fromisoformat(s[:26])
    except ValueError:
        return None


def cmd_deps(meta, recipes, conns, sched, args):
    term = args.name.lower()
    # resolve: exact adapter/provider/application match, or connection-name substring
    matched_apps = {c["adapter"] for c in conns
                    if c.get("adapter") and (c["adapter"].lower() == term or term in c["name"].lower())}
    matched_conn_names = sorted({c["name"] for c in conns
                                 if c.get("adapter") in matched_apps and term in c["name"].lower()})

    hits = []
    for r in recipes:
        via_adapter = term in {a.lower() for a in r.get("adapters", [])} or term in {p.lower() for p in r.get("providers", [])}
        via_conn = term in {c.lower() for c in r.get("connection_names", [])}
        if via_adapter or via_conn or (matched_apps & set(r.get("providers", []))):
            hits.append(r)
    if not hits:
        print(f"no recipes reference '{args.name}' (searched adapters, DSL providers, connection names)")
        return
    print(f"\n'{args.name}' -> {len(hits)} recipe(s)"
          + (f" [connections resolved: {', '.join(matched_conn_names[:10])}{' ...' if len(matched_conn_names) > 10 else ''}]" if matched_conn_names else ""))
    hits.sort(key=lambda r: (not r["running"], r["name"] or ""))
    for r in hits[:60]:
        print(f"  {'RUNNING ' if r['running'] else 'stopped '} id={r['id']:<9} {r['name'][:70]:<70} folder={r['folder_id']}")
    if len(hits) > 60:
        print(f"  ... and {len(hits) - 60} more (use twin-query.py recipes --folder to slice)")
    print(f"\ntotal: {len(hits)} recipes ({sum(1 for r in hits if r['running'])} running)")


def cmd_stale(meta, recipes, conns, sched, args):
    now = datetime.now(timezone.utc)
    stale = []
    for r in recipes:
        ts = parse_ts(r.get("updated_at"))
        if ts and (now - ts).days >= args.days:
            stale.append((r, (now - ts).days))
    stale.sort(key=lambda x: -x[1])
    print(f"\nrecipes not updated in >= {args.days} days: {len(stale)} / {len(recipes)}")
    for r, d in stale[:25]:
        print(f"  {d:>5}d {'RUNNING ' if r['running'] else 'stopped '} id={r['id']:<9} {r['name'][:70]:<70} updated={r['updated_at'][:10]}")
    if len(stale) > 25:
        print(f"  ... and {len(stale) - 25} more")
    stale_running = [r for r, _ in stale if r["running"]]
    print(f"\nof those, still RUNNING (scheduler zombies): {len(stale_running)}")


def cmd_recipes(meta, recipes, conns, sched, args):
    hits = [r for r in recipes if r.get("folder_id") == args.folder]
    print(f"\nrecipes in folder {args.folder}: {len(hits)}")
    for r in sorted(hits, key=lambda r: r["name"] or ""):
        print(f"  {'RUNNING ' if r['running'] else 'stopped '} id={r['id']:<9} v{r['version']:<4} {r['name'][:70]}")


def cmd_running(meta, recipes, conns, sched, args):
    print(f"\nlive scheduler set (running=true): {len(sched)} recipe(s)")
    for r in sorted(sched, key=lambda r: r["name"] or ""):
        print(f"  id={r['id']:<9} {r['name'][:75]:<75} last_run={str(r.get('last_run_at'))[:16]}")


def cmd_summary(meta, recipes, conns, sched, args):
    from collections import Counter
    adapters = Counter(a for r in recipes for a in r.get("adapters", []))
    conn_apps = Counter(c.get("adapter") for c in conns)
    folders = Counter(r.get("folder_id") for r in recipes)
    print(f"""
=== estate summary (env={meta.get('workato_env')}) ===
recipes:          {len(recipes)}
  running:        {len(sched)}  (live scheduler set)
  stopped:        {len(recipes) - len(sched)}
connections:      {len(conns)}
  adapters used:  {len(conn_apps)} distinct
folders touched:  {len(folders)}

top adapters by recipe usage:
""" + "\n".join(f"  {a:<30} {n:>5} recipes" for a, n in adapters.most_common(15)) + "\n")


def main():
    ap = argparse.ArgumentParser(description="Query the Workato twin snapshot (offline).")
    ap.add_argument("--allow-stale", action="store_true", help="answer even if snapshot is >24h old")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("deps", help="which recipes use a connection or adapter")
    p.add_argument("name")
    p = sub.add_parser("stale", help="recipes not updated in N days")
    p.add_argument("--days", type=int, default=90)
    p = sub.add_parser("recipes", help="list recipes in a folder")
    p.add_argument("--folder", type=int, required=True)
    sub.add_parser("running", help="live scheduler set")
    sub.add_parser("summary", help="estate overview")

    args = ap.parse_args()
    meta, recipes, conns, sched = load_twin()
    check_freshness(meta, args.allow_stale)
    {"deps": cmd_deps, "stale": cmd_stale, "recipes": cmd_recipes,
     "running": cmd_running, "summary": cmd_summary}[args.cmd](meta, recipes, conns, sched, args)


if __name__ == "__main__":
    main()
