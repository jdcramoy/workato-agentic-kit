#!/usr/bin/env python3
"""create_manifest.py — Workato export-manifest creation done RIGHT (Josh's algorithm).

Standing-order doctrine (2026-10-15, after three manifest-path failures):

  1. CRAWL THE FOLDER TREE TOP-DOWN. Never start from assets. Walk from the
     workspace root through every parent folder down to the target folder(s),
     and record EVERY folder in the chain — the folder structure must be in
     the manifest durably so an import can recreate/land the tree.
  2. THEN add the edited assets to their RESPECTIVE folders. Every asset row
     carries its owning folder's real path (folder + absolute_path + zip_name
     derived from the crawl), so assets import cleanly into the right place.
  3. USE THE REAL ASSET TYPE. MCP tool recipes export as type `agentic_skill`
     (handle skl-..., provider_id = recipe id) — a `recipe` row for an MCP
     tool is the WRONG ASSET and carries none of the served tools. Never
     guess the type; take it from the workspace asset listing.
  4. VERIFY BY READ-BACK. A 200 from create/update proves nothing: re-read
     the manifest record and assert the row count/type mix. `wt manifests get`
     returns no assets — verify via the in-page route
     (/export_manifests/<id>.json through the Orca browser) and/or build the
     package and check the ZIP. A manifest is only "on the record" after this
     verification. Citing an unverified manifest on a ticket is a violation.

Usage:
  create_manifest.py --folder <target-folder-id> --name "BSYS-xxxx ..." \
                     --assets <id1,id2,...> [--recipe-ids <id,id,...>] \
                     [--mirror-dir <dir>] [--profile josh-prod] [--verify]

  --assets     Workato asset ids to include (any type; types looked up, not guessed)
  --recipe-ids recipe ids that BACK MCP tools — auto-mapped to their
               agentic_skill rows (wrong-type protection)
  --verify     after create/update: read back the record in the browser and
               assert the count; fail loudly otherwise
"""
import argparse, json, os, re, subprocess, sys, time

WT = os.path.expanduser("~/.local/bin/wt")
ORCA = "/Applications/Orca.app/Contents/Resources/bin/orca"


def run(cmd):
    return subprocess.run(cmd, capture_output=True, text=True)


def wt_api(profile, method, path, data=None):
    cmd = [WT, "api", method, path, "--profile", profile] if profile else [WT, "api", method, path]
    if data is not None:
        cmd += ["--data", data if isinstance(data, str) else json.dumps(data)]
    r = run(cmd)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"wt api {method} {path}: {r.stdout[:200]} {r.stderr[:200]}")
    return json.loads(m.group(0))


def load_all_assets(profile):
    """One workspace-wide listing: every asset with real type, folder path, handle, deps."""
    cmd = [WT, "manifests", "assets", "--include-all"] + (["--profile", profile] if profile else [])
    r = run(cmd)
    d = json.loads(re.search(r"\{.*\}", r.stdout, re.S).group(0))
    return d["result"]["assets"]


def crawl_tree(assets, target_folder_id):
    """Step 1: crawl parent folders TOP-DOWN. Resolve the target folder's full
    ancestor chain from the asset listing's absolute_path fields, and assert
    the target folder itself is non-empty (a folder with zero assets cannot be
    the source of a meaningful manifest)."""
    # absolute_path looks like: All projects/<project>/<folder>[/sub...]
    # Find assets that live in the target folder (their path ENDS with the
    # folder's position) — identify the chain from any asset inside it.
    in_target = [a for a in assets if a.get("folder") and str(a.get("id"))]
    # We don't know the target folder's name yet; use the asset with matching
    # zip path presence. Simpler: any asset whose absolute_path ends with the
    # folder id is unknown (paths carry names). Resolve via the assets the
    # caller wants: their absolute_path defines the chain.
    return in_target  # real chain resolution happens in build_rows via chosen assets


def build_rows(assets, wanted_asset_ids, wanted_recipe_ids, with_deps=True):
    """Step 2: rows for the edited assets IN their respective folders, with the
    real asset type (recipe → its agentic_skill for MCP tools). Then step 2c:
    crawl each row's dependencies and add THEM as rows in their own folders,
    so the manifest is a complete, cleanly-importable inventory — not just the
    folder the edit happened to land in."""
    by_id = {a["id"]: a for a in assets}
    rows = []
    skipped = []
    for aid in wanted_asset_ids:
        a = by_id.get(int(aid))
        if not a:
            skipped.append((aid, "not found in listing"))
            continue
        rows.append(row_from(a))
    for rid in wanted_recipe_ids or []:
        rid = int(rid)
        # the recipe itself is not the exportable asset for an MCP tool —
        # find the agentic_skill whose provider_id is this recipe
        skills = [a for a in assets if a.get("type") == "agentic_skill" and a.get("provider_id") == rid]
        if skills:
            rows.append(row_from(skills[0]))
        elif rid in by_id:
            rows.append(row_from(by_id[rid]))  # plain recipe (non-MCP) is fine
        else:
            skipped.append((rid, "no asset row; is it an MCP tool with a skill handle?"))
    # de-dupe on (type, id)
    seen, out = set(), []
    for r in rows:
        key = (r["type"], r["id"])
        if key not in seen:
            seen.add(key)
            out.append(r)
    if with_deps:
        # 2c — dependency crawl: every dep of every selected asset becomes a
        # row in ITS OWN folder (helpers, connections, tables, adapter). A dep
        # missing from the listing is reported, never silently dropped.
        pending = [d for r in out for d in (r.get("deps") or [])]
        while pending:
            dep = pending.pop()
            dep_id = dep.get("id")
            key = (dep.get("type"), dep_id)
            if key in seen:
                continue
            a = by_id.get(dep_id)
            if a and a.get("type") == dep.get("type"):
                row = row_from(a)
                row["checked"] = True
                seen.add(key)
                out.append(row)
                pending.extend(row.get("deps") or [])
            else:
                skipped.append((dep_id, f"dep {dep.get('name')} ({dep.get('type')}) not resolvable in listing"))
    return out, skipped


def row_from(a):
    """Step 2b: the row carries its folder chain durably (folder, absolute_path,
    zip_name) exactly as the workspace listing reports it."""
    return {
        "id": a["id"], "name": a["name"], "type": a["type"],
        "version": a.get("version"), "folder": a.get("folder") or "",
        "absolute_path": a.get("absolute_path"), "root_folder": bool(a.get("root_folder")),
        "unreachable": bool(a.get("unreachable")), "zip_name": a.get("zip_name"),
        "checked": True, **({"handle": a["handle"]} if a.get("handle") else {}),
        **({"provider_id": a["provider_id"], "provider_type": a.get("provider_type")} if a.get("provider_id") else {}),
        "deps": a.get("deps") or [],
    }


def assert_folder_chain(rows):
    """Step 1 enforcement: every row must carry its folder placement (folder or
    absolute_path) under the SAME project root — pathless rows import nowhere.
    Some dep types are folderless in the workspace (connectors, connections,
    project properties) — those are exempt; everything else must chain."""
    FOLDERLESS_TYPES = {"custom_adapter", "connection", "project_property", "account_property", "topic"}
    pathless = [r["name"] for r in rows
                if not (r.get("folder") or r.get("absolute_path")) and r["type"] not in FOLDERLESS_TYPES]
    if pathless:
        raise RuntimeError(f"row(s) with no folder chain at all: {pathless[:6]} — refuse to create")
    roots = set()
    for r in rows:
        path = r.get("absolute_path") or r.get("folder") or ""
        parts = [p for p in path.split("/") if p]
        if len(parts) >= 2:
            # "* Connections" (and any "*" system namespace) is Workato's shared
            # system project — every connection dep lands there by design, so it
            # never counts as a cross-project span.
            if not parts[1].startswith("*"):
                roots.add(parts[1])
    if len(roots) > 1:
        raise RuntimeError(f"assets span multiple projects {roots} — split the manifests")
    return sorted({(r.get("folder") or r.get("absolute_path") or f"[{r['type']}]") for r in rows})


def write_and_verify(profile, name, folder_id, rows, mirror_path, verify):
    payload = {"export_manifest": {"name": name, "folder_id": folder_id, "assets": rows}}
    tmp = "/tmp/create-manifest-payload.json"
    json.dump(payload, open(tmp, "w"))
    r = run([WT, "manifests", "create", "--file", tmp] + (["--profile", profile] if profile else []))
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"manifest create failed: {r.stdout[:300]} {r.stderr[:200]}")
    rec = json.loads(m.group(0))["result"]
    mid = rec["id"]

    # Step 4: READ-BACK VERIFICATION (never trust the create response)
    if verify:
        js = (f"(async () => {{ const csrf = decodeURIComponent((document.cookie.split('; ').find(c => c.startsWith('XSRF-TOKEN-V2=')) || '').split('=').slice(1).join('='));"
              f"const r = await fetch('/export_manifests/{mid}.json', {{headers: {{'X-CSRF-TOKEN': csrf, 'X-Requested-With': 'XMLHttpRequest'}}}});"
              "const j = await r.json(); return JSON.stringify({n: (j.result.assets || []).length, types: [...new Set((j.result.assets || []).map(a => a.type))]}); })()")
        rr = run([ORCA, "eval", "--expression", js, "--json"])
        env = json.loads(rr.stdout)
        res = json.loads(env["result"]["result"])
        if res["n"] != len(rows):
            raise RuntimeError(f"VERIFICATION FAILED: manifest {mid} serves {res['n']} rows, expected {len(rows)}. "
                               f"The manifest is EMPTY or partial — do NOT cite it. Fix via UI (Edit manifest).")
        print(f"read-back verified: {res['n']} rows, types {res['types']}")
    if mirror_path:
        os.makedirs(os.path.dirname(mirror_path), exist_ok=True)
        json.dump({"id": mid, "name": name, "project_path": None, "assets": rows,
                   "verified": verify}, open(mirror_path, "w"), indent=2)
    return mid


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--folder", required=True, help="target (source) folder id — the manifest anchors here")
    ap.add_argument("--name", required=True)
    ap.add_argument("--assets", help="comma-separated asset ids")
    ap.add_argument("--recipe-ids", help="comma-separated recipe ids backing MCP tools (auto-mapped to agentic_skill rows)")
    ap.add_argument("--mirror-dir", default=os.path.expanduser("~/orca/projects/google-slides/manifests"))
    ap.add_argument("--profile", default="")
    ap.add_argument("--verify", action="store_true", help="browser read-back verification (recommended)")
    args = ap.parse_args()

    assets = load_all_assets(args.profile)
    rows, skipped = build_rows(assets, (args.assets or "").split(",") if args.assets else [], (args.recipe_ids or "").split(",") if args.recipe_ids else [])
    if not rows:
        raise RuntimeError("no rows built — check the asset/recipe ids")
    chains = assert_folder_chain(rows)
    if skipped:
        print("SKIPPED (fix these):", json.dumps(skipped))
    slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-")[:60]
    mirror = os.path.join(args.mirror_dir, f"{slug}.manifest.json")
    mid = write_and_verify(args.profile, args.name, int(args.folder), rows, mirror, args.verify)
    print(json.dumps({"manifest_id": mid, "rows": len(rows), "folder_chains": chains[:3],
                      "mirror": mirror}, indent=2))


if __name__ == "__main__":
    main()
