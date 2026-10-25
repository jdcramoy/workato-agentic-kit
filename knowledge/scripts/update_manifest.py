#!/usr/bin/env python3
"""update_manifest.py — add/replace rows on an EXISTING export manifest (BSYS living manifest).

Companion to create_manifest.py: reuse its row-building (real types, folder chains,
dependency crawl) but push via `wt manifests update <id>` instead of creating a
duplicate manifest. Same doctrine: rows carry real UI names and real asset types.

Usage:
  update_manifest.py --id 371156 --name "BSYS-xxxx ..." \
      --assets <id1,id2,...> [--recipe-ids <id,id,...>] [--mirror-dir <dir>] [--verify]
"""
import argparse, importlib.util, json, os, re, subprocess, sys

CREATE_SCRIPT = os.path.expanduser("~/.claude/knowledge/scripts/create_manifest.py")
WT = os.path.expanduser("~/.local/bin/wt")
ORCA = "/Applications/Orca.app/Contents/Resources/bin/orca"

spec = importlib.util.spec_from_file_location("create_manifest", CREATE_SCRIPT)
cm = importlib.util.module_from_spec(spec)
spec.loader.exec_module(cm)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--id", required=True, help="existing manifest id to update")
    ap.add_argument("--name", required=True)
    ap.add_argument("--folder", required=True, help="anchor folder id (unchanged, but required by the payload)")
    ap.add_argument("--assets", help="comma-separated asset ids (any type; looked up)")
    ap.add_argument("--recipe-ids", help="recipe ids backing MCP tools (mapped to agentic_skill)")
    ap.add_argument("--dep-recipe-ids", help="cross-project dependency recipe ids")
    ap.add_argument("--mirror-dir", required=True)
    ap.add_argument("--profile", default="")
    ap.add_argument("--verify", action="store_true")
    args = ap.parse_args()

    assets = cm.load_all_assets(args.profile)
    rows, skipped, dep_ids = cm.build_rows(
        assets,
        (args.assets or "").split(",") if args.assets else [],
        (args.recipe_ids or "").split(",") if args.recipe_ids else [],
        dep_recipe_ids=(args.dep_recipe_ids or "").split(",") if args.dep_recipe_ids else [],
    )
    if not rows:
        raise RuntimeError("no rows built — check the asset/recipe ids")
    cm.assert_folder_chain(rows, dep_ids)
    if skipped:
        print("SKIPPED (fix these):", json.dumps(skipped))

    payload = {"export_manifest": {"name": args.name, "folder_id": int(args.folder), "assets": rows}}
    tmp = "/tmp/update-manifest-payload.json"
    json.dump(payload, open(tmp, "w"))
    cmd = [WT, "manifests", "update", args.id, "--file", tmp] + (["--profile", args.profile] if args.profile else [])
    r = subprocess.run(cmd, capture_output=True, text=True)
    m = re.search(r"\{.*\}", r.stdout, re.S)
    if not m:
        raise RuntimeError(f"manifest update failed: {r.stdout[:300]} {r.stderr[:300]}")

    mid = args.id
    if args.verify:
        js = (f"(async () => {{ const csrf = decodeURIComponent((document.cookie.split('; ').find(c => c.startsWith('XSRF-TOKEN-V2=')) || '').split('=').slice(1).join('='));"
              f"const r = await fetch('/export_manifests/{mid}.json', {{headers: {{'X-CSRF-TOKEN': csrf, 'X-Requested-With': 'XMLHttpRequest'}}}});"
              "const j = await r.json(); return JSON.stringify({n: (j.result.assets || []).length, types: [...new Set((j.result.assets || []).map(a => a.type))]}); })()")
        rr = subprocess.run([ORCA, "eval", "--expression", js, "--json"], capture_output=True, text=True)
        env = json.loads(rr.stdout)
        res = json.loads(env["result"]["result"])
        if res["n"] != len(rows):
            raise RuntimeError(f"VERIFICATION FAILED: manifest {mid} serves {res['n']} rows, expected {len(rows)}.")
        print(f"read-back verified: {res['n']} rows")

    from collections import Counter
    slug = re.sub(r"[^a-z0-9]+", "-", args.name.lower()).strip("-")[:60]
    mirror = os.path.join(args.mirror_dir, f"{slug}.manifest.json")
    os.makedirs(os.path.dirname(mirror), exist_ok=True)
    json.dump({"id": int(mid), "name": args.name, "assets": rows, "verified": args.verify}, open(mirror, "w"), indent=2)
    print(json.dumps({"manifest_id": int(mid), "rows": len(rows),
                      "types": dict(Counter(x["type"] for x in rows)), "mirror": mirror}, indent=2))


if __name__ == "__main__":
    main()
