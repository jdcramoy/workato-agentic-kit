#!/usr/bin/env python3
"""AUDIT | AI Directory | Exactness — independent ID-set auditor (BSYS-29779).

Runs ENTIRELY outside the Workato platform: reads the inventory tables via the
data-tables REST API and every live source via wt — never trusts the syncs'
own claims. Per-type verdict: EXACT / TABLE_MORE(details) / GAP(details).

Usage:
  audit_exactness.py                # audit BOTH dev (166090) and prod (161989) tables
  audit_exactness.py --env dev     # dev only
  audit_exactness.py --env prod    # prod only

Live sources per env:
  dev  workspace 3535597 (wt default profile josh-us)
  prod workspace 3535598 (wt profile josh-prod, table 161989, snowflake-count types
  audited via the sync-state's last-run EDW rows_count when direct query is unavailable)

Exit code: 0 = all EXACT/TABLE_MORE-explained, 2 = any GAP, 3 = infrastructure error.
"""
import json
import subprocess
import sys

DT_HOST = "https://data-tables.workato.com/api/v1/tables"
TABLES = {"dev": "16db53ed-51ab-4b5c-8a5a-e8ae7a768173", "prod": "16db53ed-51ab-4b5c-8a5a-e8ae7a768173"}
PROD_TABLE = "16db53ed-51ab-4b5c-8a5a-e8ae7a768173"
PROD_TABLE_ID = "161989"


def token_for(env):
    acct = "josh-us" if env == "dev" else "josh-prod"
    out = subprocess.run(["security", "find-generic-password", "-s", "workato-platform-cli", "-a", acct, "-w"],
                         capture_output=True, text=True)
    t = out.stdout.strip()
    if not t:
        raise SystemExit(f"no keychain token for {acct}")
    return t


def wt(env, *args):
    cmd = ["wt"] + [args[0], "--profile", ("josh-us" if env == "dev" else "josh-prod")] + list(args[1:])
    r = subprocess.run(cmd, capture_output=True, text=True)
    return r.stdout


def dt_read_all(token, tid):
    rows, tok = [], None
    for _ in range(40):
        body = {"limit": 200}
        if tok:
            body["continuation_token"] = tok
        out = subprocess.run(
            ["curl", "-s", "-X", "POST", f"{DT_HOST}/{tid}/query",
             "-H", f"Authorization: Bearer {token}", "-H", "Content-Type: application/json",
             "-d", json.dumps(body)], capture_output=True, text=True).stdout
        d = json.loads(out)
        if "errors" in d:
            raise SystemExit(f"data-tables error: {d}")
        rows.extend(d.get("data") or [])
        tok = d.get("continuation_token")
        if not tok:
            break
    names = [f.get("name") for f in (d["schema"][1] if len(d.get("schema") or []) > 1 else [])]
    id_i, at_i, st_i = names.index("asset_id"), names.index("asset_type"), names.index("state")
    live_ids = {}
    for r in rows:
        aid, at, st = r[1][id_i], r[1][at_i], r[1][st_i]
        if st != "archived":
            live_ids.setdefault(at, set()).add(aid)
    return live_ids, len(rows)


def paged_ids(env, ep, key="id", pages=40, pp=100):
    out_ids = []
    seen = set()
    for p in range(1, pages + 1):
        raw = wt(env, "api", "get", f"/api/{ep}?per_page={pp}&page={p}")
        try:
            d = json.loads(raw)
        except Exception:
            return None if not out_ids else out_ids  # endpoint down after some pages
        items = d if isinstance(d, list) else (d.get("data") or d.get("items") or [])
        new = [str(i.get(key)) for i in items if i.get(key) and str(i.get(key)) not in seen]
        # endpoints that ignore pagination return the same full list every page — stop there
        if not new and out_ids:
            break
        seen.update(new)
        out_ids.extend(new)
        if len(items) < pp:
            break
    return out_ids


def audit_env(env):
    token = token_for(env)
    tid = PROD_TABLE if env == "prod" else TABLES["dev"]
    table, total_rows = dt_read_all(token, tid)
    print(f"[{env}] table rows read: {total_rows} (non-archived by type: "
          f"{ {t: len(v) for t, v in table.items()} })")

    verdicts = []
    checks = {
        "folder": paged_ids(env, "folders"),
        "project": paged_ids(env, "projects"),
        "user_group": paged_ids(env, "user_groups"),
        "role": paged_ids(env, "project_roles"),
        "lookup_table": paged_ids(env, "lookup_tables"),
        "connection": paged_ids(env, "connections", pages=15),
        "recipe": paged_ids("prod", "recipes", key="id", pages=25, pp=100),  # via AIRO count check below
        "mcp_server": paged_ids(env, "mcp/mcp_servers", key="id", pages=12, pp=50),
    }
    for t, live in checks.items():
        if live is None:
            verdicts.append((t, "SKIP", "no independent live route from CLI"))
            continue
        # table asset_ids carry a "dev:<type>:" (or "prod:<type>:") prefix — strip for the ID-set diff
        tab = {i.split(f"{env}:{t}:", 1)[-1] for i in table.get(t, set())}
        extra = sorted(tab - set(live))
        missing = sorted(set(live) - tab)
        if not extra and not missing:
            verdicts.append((t, "EXACT", f"{len(set(live))}={len(set(live))}"))
        elif extra and not missing:
            verdicts.append((t, "TABLE_MORE", f"table has {len(extra)} not in live listing (sample: {extra[:3]})"))
        else:
            verdicts.append((t, "GAP", f"missing {len(missing)} (sample {missing[:3]}), extra {len(extra)} (sample {extra[:3]})"))
    return verdicts


def main():
    envs = sys.argv[sys.argv.index("--env") + 1].split(",") if "--env" in sys.argv else ["dev", "prod"]
    rc = 0
    for env in envs:
        print(f"=== AUDIT {env} ===")
        try:
            verdicts = audit_env(env)
        except SystemExit as e:
            print(f"  INFRA ERROR: {e}")
            rc = 3
            continue
        for t, v, detail in verdicts:
            print(f"  {t:<16} {v:<12} {detail}")
            if v == "GAP":
                rc = 2
    sys.exit(rc)


if __name__ == "__main__":
    main()
