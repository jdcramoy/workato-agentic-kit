#!/usr/bin/env python3
"""Manifest v3: all 11 toolkit skills + the MCP server selected (auto-attach
on import), plus the session dependencies — mirror-the-UI shapes, anchor 32205279."""
import json, subprocess

d = json.loads(subprocess.run(["wt", "manifests", "assets", "--include-all"],
                              capture_output=True, text=True).stdout)
assets = d["result"]["assets"]
by = {(a["type"], a["id"]): a for a in assets}

ANCHOR = "MCP | BT Managed MCP/Enhanced Google Slides by Workato MCP"

def mirror_ui(a):
    a = dict(a)
    fol = a.get("folder") or ""
    if fol.startswith(ANCHOR + "/"):
        a["folder"] = fol[len(ANCHOR) + 1:]
    z = a.get("zip_name") or ""
    if z.startswith(ANCHOR + "/"):
        a["zip_name"] = z[len(ANCHOR) + 1:]
    a.pop("state", None)
    a.pop("deps", None)
    return a

def pick(a, keys):
    return {k: a[k] for k in keys if k in a and a[k] is not None}

SKILL_KEYS = ["id", "name", "type", "version", "folder", "absolute_path", "root_folder",
              "unreachable", "zip_name", "handle", "provider_id", "provider_type"]

rows = []
# 1) all 11 toolkit skills — SELECTED
want = ["Measure Slide", "Inspect Render", "Fit_Text_To_Box", "Fit_Box_To_Text",
        "Build_Slide_From_Spec", "Apply Text Role", "Snapshot Slide", "Restore Slide",
        "Lint_Deck", "Build_Chart_From_Spec", "Update_Chart"]
seen = set()
for a in assets:
    if a.get("type") == "agentic_skill" and any(w == (a.get("name") or "") or w in (a.get("name") or "") for w in want):
        key = a["id"]
        if key in seen:
            continue
        seen.add(key)
        r = mirror_ui(a)
        rows.append(pick(r, SKILL_KEYS) | {"checked": True})

# 2) the MCP server — SELECTED (auto-attaches tool bindings on import)
srv = mirror_ui(by[("mcp_server", 16704)])
rows.append(pick(srv, ["id", "name", "type", "version", "folder", "absolute_path",
                       "root_folder", "unreachable", "zip_name", "handle"]) | {"checked": True})

# 3) session dependencies — SELECTED (unchanged from v2)
for rid in (83295991, 82864228, 74622357, 74622358):
    r = mirror_ui(by[("recipe", rid)])
    rows.append(pick(r, ["id", "name", "type", "version", "folder", "absolute_path",
                         "root_folder", "unreachable", "zip_name", "include_test_cases"]) | {"checked": True})
for tid in (135007, 157628):
    r = mirror_ui(by[("workato_db_table", tid)])
    rows.append(pick(r, ["id", "name", "type", "version", "folder", "absolute_path",
                         "root_folder", "unreachable", "zip_name", "include_data"]) | {"checked": True})
r = mirror_ui(by[("connection", 19872138)])
rows.append(pick(r, ["id", "name", "type", "version", "folder", "absolute_path",
                     "root_folder", "unreachable", "zip_name", "provider"]) | {"checked": True})
for aid in (1332342, 976079, 1115156):
    r = mirror_ui(by[("custom_adapter", aid)])
    rows.append(pick(r, ["id", "name", "type", "version", "folder", "absolute_path",
                         "root_folder", "unreachable", "zip_name"]) | {"checked": True})
for pid in (20270815, 20270816, 20270898):
    r = mirror_ui(by[("project_property", pid)])
    rows.append(pick(r, ["id", "name", "type", "version", "folder", "absolute_path",
                         "root_folder", "unreachable", "zip_name"]) | {"checked": True})

payload = {"export_manifest": {"name": "BSYS-29908 Layout Quality Toolkit - living manifest (dev)",
                               "folder_id": 32205279, "assets": rows}}
json.dump(payload, open("/tmp/manifest-v3.json", "w"), indent=1)
print("rows:", len(rows))
for r in rows:
    print(" ", r["type"], "|", r["name"][:44], "| folder:", repr(r.get("folder")))
