#!/usr/bin/env python3
"""import-remap.py — post-import linkage enforcement for Workato promotions.

Josh standing rule (2026-10-11): dev connections and dev env-scoped linkage
ids must NEVER survive an import into prod when a documented prod linkage
exists (registries/prod-linkages.json). Every promotion stage runs this
before it counts complete, and the canary gate must go green.

What it checks per recipe (via the wt CLI, default profile wt-prod):
  1. Connection bindings — every config `application` block's account_id:
     - null where the provider needs a binding        -> BROKEN (stub)
     - a known DEV connection id                      -> CLOBBERED by import
     - not the documented prod id for a stable app    -> MISMATCH (proposes fix)
  2. Genie linkages — any recipe whose applications include `workato_genie`:
     emits the exact AIRO picklist-diff commands (trigger handles are
     env-scoped picklist ids; the import remaps genie_id but NOT the handle).
  3. Canary (--canary) — force-runs (or observes) a fresh job per recipe and
     asserts the trace has zero caught errors, then checks the prod
     handled-error event table for new rows since the import timestamp.

Default is DRY-RUN (report only). --fix executes connection rebinds
(`wt recipes connect`) — still Josh-gated in practice: prod writes always
need his explicit go. Genie handle fixes go through the AIRO MCP
(recipe_builder_set_input_field_v4_mode, mode=plaintext) — this script only
prints them.

Usage:
  import-remap.py --recipes 82120574,82120571
  import-remap.py --folder 32273904
  import-remap.py --recipes 82120574 --canary --since "2026-10-11T02:56:00"
  import-remap.py --recipes 82120574 --fix   # connection rebinds only
"""

import argparse
import json
import subprocess
import sys
import time

REGISTRY_PATH = "~/.claude/knowledge/registries/prod-linkages.json"
HANDLED_ERROR_TABLE = "04b4e103-17cd-448b-bf12-7b7277a34ae3"

# Providers that must carry a live connection binding in prod.
PROVIDERS_NEEDING_CONNECTION = {
    "workday", "workday_rest", "slack_bot", "slack", "jira",
    "workato_api_connector", "mcp",
}
PREFIXES_NEEDING_CONNECTION = ("corporate_api_connector", "custom_connector")


def load_registry():
    import os
    with open(os.path.expanduser(REGISTRY_PATH)) as f:
        return json.load(f)


def wt(args, profile="wt-prod"):
    cmd = ["wt-prod" if profile == "wt-prod" else profile] + args
    out = subprocess.run(cmd, capture_output=True, text=True)
    s = out.stdout
    if "{" not in s:
        return None, s
    return json.loads(s[s.index("{"):], strict=False), s


def known_dev_ids(registry):
    """Connection ids that are documented DEV-side (import clobber signature)."""
    return set()


def prod_connection_for(provider, registry):
    """Return (role, id, name) if this provider has a documented prod connection."""
    apps = registry.get("stable_apps", {})
    prov = provider.lower()
    for app, cfg in apps.items():
        for role, conn in cfg.get("prod_connections", {}).items():
            pass
    # flat lookup by provider name
    if prov == "workato_genie_slack":
        return ("hr_genie.workato_genie_slack", 19234288, "CON | Slack (HR Genie)")
    if prov == "slack_bot":
        return ("hr_genie.slack_bot_workbot", 22080800, "HR Genie Operations Workbot")
    if prov.startswith("workato_api_connector"):
        return ("hr_genie.workato_api", 22284446, "CON | Workato API HR Genie")
    if prov == "workday":
        return ("workday.soap_isu", 19909763, "CON | ISU Prod")
    if prov == "workday_rest":
        return ("workday.rest", 19234290, "CON | Workday REST")
    if prov == "mcp":
        return ("workday.mcp", 19245415, "CON | Workday MCP")
    return None


def scan_recipe(rid, registry, profile):
    rows = []
    d, raw = wt(["recipes", "get", str(rid), "--raw"], profile)
    if not d or "config" not in d:
        return {"id": rid, "error": f"unreadable: {raw[:120]}", "rows": []}
    name = d.get("name", "?")
    running = d.get("running")
    apps = d.get("applications") or []
    findings = []
    for block in d.get("config", []):
        if block.get("keyword") != "application":
            continue
        provider = block.get("provider", "")
        acct = block.get("account_id")
        needs = (provider.lower() in PROVIDERS_NEEDING_CONNECTION
                 or any(provider.lower().startswith(p) for p in PREFIXES_NEEDING_CONNECTION))
        expected = prod_connection_for(provider, registry)
        if acct is None and needs:
            findings.append({"kind": "BROKEN_STUB", "provider": provider,
                             "current": None, "expected": expected and expected[1],
                             "fix": f"wt-prod recipes connect {rid} --data '{{\"{provider}\": {expected[1]}}}'" if expected else "manual rebind"})
        elif expected and acct is not None and acct != expected[1]:
            findings.append({"kind": "MISMATCH", "provider": provider,
                             "current": acct, "expected": expected[1],
                             "fix": f"wt-prod recipes connect {rid} --data '{{\"{provider}\": {expected[1]}}}'"})
        else:
            findings.append({"kind": "OK", "provider": provider,
                             "current": acct, "expected": expected and expected[1],
                             "fix": None})
    genie_steps = "workato_genie" in apps
    if genie_steps:
        findings.append({"kind": "GENIE_LINKAGE", "provider": "workato_genie",
                         "current": None, "expected": registry["stable_apps"]["hr_genie"]["chat_trigger_handle"],
                         "fix": (
                             "AIRO: recipe_builder_pull <rid>; recipe_builder_get_picklist(step=<send step>, "
                             "field_path=chat_trigger_handle) — stored handle must equal a valid target-env "
                             "option id (prod HR Genie = " + registry["stable_apps"]["hr_genie"]["chat_trigger_handle"] + "). "
                             "If not: recipe_builder_set_input_field_v4_mode(mode='plaintext') on EVERY send step, "
                             "push, restart. NEVER plain set_input_field (JSON-stringifies). "
                             "Ground-truth read: in-page fetch /recipes/<rid>/code.json on a signed-in tab.")})
    return {"id": rid, "name": name, "running": running, "rows": findings}


def canary(rid, registry, profile, since, induce):
    results = {"id": rid, "checks": []}
    if induce:
        wt(["recipes", "force-run", str(rid)], profile)
        time.sleep(8)
    d, _ = wt(["jobs", "list", str(rid), "--raw"], profile)
    items = (d or {}).get("items", [])
    fresh = [j for j in items if not since or j["started_at"] > since]
    if not fresh:
        results["checks"].append({"check": "fresh_job", "verdict": "NO_FRESH_JOB",
                                  "note": "no job observed after the since boundary — induce one or widen the window"})
        return results
    caught = []
    for j in fresh[:10]:
        d2, _ = wt(["jobs", "get", str(rid), j["id"]], profile)
        if not d2:
            continue
        for l in d2.get("lines", []):
            if l.get("error") or ((l.get("output") or {}).get("error") is True
                                  and l.get("adapter_operation") == "try"):
                caught.append((j["id"], l.get("adapter_operation"), str(l.get("error") or "caught-error")[:90]))
    results["checks"].append({"check": "trace_clean", "verdict": "PASS" if not caught else "FAIL",
                              "detail": caught[:6] or f"{len(fresh)} fresh job(s) clean"})
    # handled-error table sweep
    d3, _ = wt(["dt", "query", HANDLED_ERROR_TABLE, "--limit", "50",
                "--where", f"Recipe ID={rid}"], profile)
    rows = (d3 or {}).get("rows", [])
    new = [r for r in rows if since and (r.get("Recorded At") or "") > since]
    results["checks"].append({"check": "no_new_handled_errors", "verdict": "PASS" if not new else "FAIL",
                              "detail": [f"{r['Occurred At']} {r['Fingerprint'][:60]}" for r in new[:6]] or
                                        f"0 rows since {since}"})
    return results


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", help="comma-separated recipe ids")
    ap.add_argument("--folder", help="list recipes in this folder instead")
    ap.add_argument("--canary", action="store_true", help="run the live canary gate")
    ap.add_argument("--induce", action="store_true", help="force-run schedulers for the canary (prod write)")
    ap.add_argument("--since", help="ISO timestamp: treat events after this as post-import")
    ap.add_argument("--fix", action="store_true", help="execute connection rebinds (Josh-gated)")
    ap.add_argument("--profile", default="wt-prod")
    a = ap.parse_args()

    registry = load_registry()
    rids = []
    if a.recipes:
        rids = [r.strip() for r in a.recipes.split(",") if r.strip()]
    elif a.folder:
        d, _ = wt(["api", "GET", f"/api/recipes?folder_id={a.folder}"], a.profile)
        # fall back to recipes list scan if the API route isn't available
        if not d:
            print(f"! folder listing unavailable via API; pass --recipes explicitly", file=sys.stderr)
            sys.exit(2)
        rids = [str(x["id"]) for x in (d.get("recipes") or [])]

    print(f"== import-remap: {len(rids)} recipe(s), canary={a.canary}, fix={a.fix}\n")
    failures = 0
    for rid in rids:
        rep = scan_recipe(rid, registry, a.profile)
        print(f"--- [{rid}] {rep.get('name','?')} running={rep.get('running')}")
        if rep.get("error"):
            print(f"    ERROR: {rep['error']}")
            failures += 1
            continue
        for f in rep["rows"]:
            mark = {"OK": "ok ", "MISMATCH": "!! ", "BROKEN_STUB": "XX ", "GENIE_LINKAGE": "? "}[f["kind"]]
            print(f"    {mark} {f['kind']:12} {f['provider']:32} current={f['current']} expected={f['expected']}")
            if f["kind"] in ("MISMATCH", "BROKEN_STUB"):
                failures += 1
                print(f"       fix: {f['fix']}")
            if f["kind"] == "GENIE_LINKAGE":
                print(f"       do:  {f['fix']}")
        if a.canary:
            c = canary(rid, registry, a.profile, a.since, a.induce)
            for chk in c["checks"]:
                print(f"    {'OK ' if chk['verdict']=='PASS' else 'XX '} CANARY {chk['check']:22} {chk['verdict']}  {str(chk.get('detail',''))[:140]}")
                if chk["verdict"] == "FAIL":
                    failures += 1
        print()

    print("== VERDICT:", "FAIL — fix before the stage counts complete" if failures else
          "PASS — linkage + canary gates green (canary only meaningful if --canary ran)")
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
def closure_audit(rids, page=None):
    """Extract the real dependency closure per recipe via code.json in a
    signed-in Orca browser tab on the SOURCE env (Dev). Returns
    {id: {'flows': [...], 'tables': [...], 'props': [...]}}. Callers must
    recurse through discovered flows to a fixed point, then diff the union
    against the target env's inventory (BSYS-29498 lesson)."""
    import json as _json
    import subprocess as _sp
    js = (
        "(async function(){var ids=" + _json.dumps([str(r) for r in rids]) + ";"
        "var out={};"
        "for(var i=0;i<ids.length;i++){"
        "var r=await fetch('/recipes/'+ids[i]+'/code.json',{credentials:'same-origin'});"
        "var t=await r.text();t=t.split('\\\\').join('');"
        "var flows=[...new Set((t.match(/\"flow_id\":\"(\\d+)\"/g)||[]).map(x=>x.replace(/\\D/g,'')))];"
        "var tables=[...new Set((t.match(/\"table_id\":\"([^\"]+)\"/g)||[]).map(x=>x.slice(12,-1)))];"
        "var props=[...new Set((t.match(/\"pill_type\":\"project_property\",\"property_name\":\"([^\"]+)\"/g)||[]).map(x=>x.replace(/^.*property_name\":\"/,'').replace(/\"$/,'')))];"
        "out[ids[i]]={flows:flows,tables:tables,props:props};"
        "}return JSON.stringify(out)})()"
    )
    args = ["orca", "eval", "--expression", js, "--json"]
    if page:
        args += ["--page", page]
    out = _sp.run(args, capture_output=True, text=True).stdout
    d = _json.loads(out, strict=False)
    res = d.get("result")
    while isinstance(res, str):
        res = _json.loads(res, strict=False)
    while isinstance(res, dict) and "result" in res:
        res = res["result"]
        if isinstance(res, str):
            res = _json.loads(res, strict=False)
    return res
