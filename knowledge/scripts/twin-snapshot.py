#!/usr/bin/env python3
"""Twin snapshot: capture the Workato estate into knowledge/twin/v1/ as an
offline-queryable twin (frontier build contract, 2026-10-11).

Writes (ownership block — never write outside it):
  ~/.claude/knowledge/twin/v1/recipes.jsonl
  ~/.claude/knowledge/twin/v1/connections.jsonl
  ~/.claude/knowledge/twin/v1/schedulers.jsonl   (recipes with running=true)
  ~/.claude/knowledge/twin/v1/meta.json          {"snapshot_at","workato_env","counts"}

Auth: shells out to `wt api` (~/.local/bin/wt) which resolves WORKATO_API_TOKEN
env or the macOS keychain entry workato-platform-cli stores (see
fusion-run.py request() pattern). Dev profile default; --env prod prints a
WARNING and requires --confirm.

Usage:
  twin-snapshot.py                  # snapshot DEV (default)
  twin-snapshot.py --env prod --confirm
"""
import argparse, json, os, subprocess, sys, time

TWIN_DIR = os.path.expanduser("~/.claude/knowledge/twin/v1")
WT = os.path.expanduser("~/.local/bin/wt")
PER_PAGE = 100
PROFILES = {"dev": "josh-us", "prod": "josh-prod"}


def wt_api(method, path, env):
    """One wt api passthrough call; returns parsed JSON or dies with stderr."""
    cmd = [WT, "api", "--profile", PROFILES[env], "--raw", method, path]
    p = subprocess.run(cmd, capture_output=True, text=True)
    if p.returncode != 0:
        sys.exit(f"wt api {method} {path} failed (rc={p.returncode}): {p.stderr.strip()[:300]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        sys.exit(f"wt api {method} {path} returned non-JSON output (first 200): {p.stdout[:200]}")


def paginate(path, env):
    """Yield items from a /api/... list endpoint paginating page=1..N."""
    page = 1
    while True:
        d = wt_api("GET", f"{path}{'&' if '?' in path else '?'}per_page={PER_PAGE}&page={page}", env)
        if isinstance(d, list):  # endpoints that ignore pagination (connections)
            yield from d
            return
        items = d.get("items") or []
        yield from items
        count = d.get("count")
        if not items or len(items) < PER_PAGE or (count is not None and page * PER_PAGE >= count):
            return
        page += 1


def providers_from_code(code):
    """Collect every step `provider` string in a recipe DSL (code is a JSON
    string of the recipe tree). Returns [] when code is absent/unparseable."""
    if isinstance(code, str) and code:
        try:
            code = json.loads(code)
        except (ValueError, TypeError):
            return []
    out = set()

    def walk(o):
        if isinstance(o, dict):
            pv = o.get("provider")
            if isinstance(pv, str):
                out.add(pv)
            for v in o.values():
                walk(v)
        elif isinstance(o, list):
            for v in o:
                walk(v)

    if isinstance(code, (dict, list)):
        walk(code)
    return sorted(out)


def main():
    ap = argparse.ArgumentParser(description="Snapshot the Workato estate into the twin (knowledge/twin/v1).")
    ap.add_argument("--env", choices=["dev", "prod"], default="dev", help="Workato environment (default: dev)")
    ap.add_argument("--confirm", action="store_true", help="Required with --env prod")
    args = ap.parse_args()

    if args.env == "prod" and not args.confirm:
        print("""
********************************************************************************
WARNING: --env prod snapshots the LIVE PRODUCTION Workato workspace
(profile josh-prod, workspace 3535598). This is NOT dev.
Re-run with:  twin-snapshot.py --env prod --confirm
********************************************************************************""")
        sys.exit(1)

    env = args.env
    t0 = time.time()
    os.makedirs(TWIN_DIR, exist_ok=True)

    # --- connections first (needed to resolve provider -> connection names) ---
    print(f"[twin] fetching connections ({env}) ...")
    conns = list(paginate("/api/connections?per_page=100", env))
    app_to_names = {}
    for c in conns:
        app_to_names.setdefault(c.get("application"), []).append(c.get("name"))

    # --- recipes (paginated; 6333 in dev = ~64 pages) ---
    print(f"[twin] fetching recipes, per_page={PER_PAGE} ({env}) ... this is the slow part")
    n_recipes = 0
    path_r = os.path.join(TWIN_DIR, "recipes.jsonl")
    with open(path_r, "w") as f:
        for r in paginate("/api/recipes?per_page=100", env):
            apps = sorted({a for a in (r.get("action_applications") or []) if a} |
                          ({r["trigger_application"]} if r.get("trigger_application") else set()))
            provs = providers_from_code(r.get("code"))
            conn_names = sorted({n for p in provs for n in app_to_names.get(p, [])})
            row = {"id": r["id"], "name": r.get("name"), "folder_id": r.get("folder_id"),
                   "running": bool(r.get("running")), "version": r.get("version_no"),
                   "updated_at": r.get("updated_at"), "last_run_at": r.get("last_run_at"),
                   "adapters": apps, "providers": provs, "connection_names": conn_names}
            f.write(json.dumps(row) + "\n")
            n_recipes += 1
            if n_recipes % 500 == 0:
                print(f"[twin]   {n_recipes} recipes ...")

    # --- schedulers: the live set ---
    n_sched = 0
    with open(path_r) as f, open(os.path.join(TWIN_DIR, "schedulers.jsonl"), "w") as fs:
        for line in f:
            row = json.loads(line)
            if row["running"]:
                fs.write(line)
                n_sched += 1

    # --- connections.jsonl ---
    with open(os.path.join(TWIN_DIR, "connections.jsonl"), "w") as f:
        for c in conns:
            f.write(json.dumps({"id": c.get("id"), "name": c.get("name"),
                                "adapter": c.get("application"),
                                "provider": c.get("application"),
                                "authorized_status": c.get("authorization_status"),
                                "updated_at": c.get("updated_at")}) + "\n")

    # --- meta.json (written last = twin exists only when complete) ---
    meta = {"snapshot_at": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
            "workato_env": env,
            "counts": {"recipes": n_recipes, "connections": len(conns),
                       "schedulers_running": n_sched},
            "wall_s": round(time.time() - t0, 1)}
    with open(os.path.join(TWIN_DIR, "meta.json"), "w") as f:
        json.dump(meta, f, indent=2)

    print(f"""
[twin] snapshot complete ({meta['wall_s']}s, env={env})
  recipes:             {n_recipes}
  connections:         {len(conns)}
  schedulers running:  {n_sched}
  written to:          {TWIN_DIR}""")

    if env == "prod":
        print("""
********************************************************************************
WARNING: this twin captured PRODUCTION. twin-query.py answers will say env=prod
until the next dev snapshot. Do not confuse the two.
********************************************************************************""")


if __name__ == "__main__":
    main()
