#!/usr/bin/env python3
"""env-diff.py — read-only cross-environment diff (dev wt 3535597 vs prod wt-prod 3535598).

Inventories BOTH Workato environments via the Developer CLI (wt / wt-prod,
read-only — never issues any write/create/update/delete/import/start/stop),
joins assets by folder-path + asset NAME (IDs differ across envs — never join
by ID), and classifies drift:

  MISSING_IN_PROD            dev asset with no same-name counterpart in prod
  CODE_DIFFERS               both exist, normalized code hashes differ
  NEWER_IN_DEV               code identical but dev updated_at > prod's
  ORPHANED_IN_PROD           prod-only asset (may be an intentional delete —
                             "confirm intent", NEVER auto-remediate)
  CONNECTION_MISSING_IN_PROD dev connection with no prod counterpart
  CONNECTION_REAUTH          connection exists in both but prod copy looks
                             unauthorized
  PROPERTY_DIVERGENCE        same property key, different value (or present
                             on one side only)

Normalization (the critical part): raw recipe `code` embeds environment-
specific IDs (connection ids, callee flow ids, data-table UUIDs, lookup ids,
field ids). Before hashing we build a cross-env id->name map from the two
inventories, walk the recipe, and substitute every mapped id token with a
"@<type>:<name>@" token; runtime/volatile fields (updated_at, version_no,
the recipe's own id, job counters...) are stripped. Equal normalized hashes
=> functionally identical code. Raw hashes are ALSO computed and reported
side-by-side so id-churn false positives stay visible.

Validation gate (--validate-promoted <recipe_name>): asserts a known-promoted
recipe normalizes to MATCHING hashes in both envs using fresh `wt recipes get`
code. A false diff there is a normalization bug, not a real diff — the script
says so loudly and prints the first divergence context.

Usage:
  env-diff.py [--project <folder-name-substring>] [--json] [--use-cache]
  env-diff.py --validate-promoted <recipe_name>

Cache: ~/.claude/knowledge/workato-health/env-diff-state.json is a derived,
rebuildable registry written on every live run; --use-cache reads it (never
authoritative). stdlib only; macOS system python3 safe.
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import re
import subprocess
import sys
from collections import OrderedDict

HOME = os.path.expanduser("~")
CACHE = os.path.join(HOME, ".claude", "knowledge", "workato-health", "env-diff-state.json")
PROFILES = {"dev": ["wt"], "prod": ["wt-prod"]}

# Envelope fields that are runtime/volatile metadata, never part of functional identity.
VOLATILE_KEYS = {
    "id", "user_id", "created_at", "updated_at", "version_no", "copy_count",
    "job_succeeded_count", "job_failed_count", "lifetime_task_count",
    "last_run_at", "last_job_started_at", "stopped_at", "stop_cause",
    "running", "webhook_url", "author_name", "trigger_closure",
    "project_id",  # env-specific numeric id; folder path already captures placement
}

REC_URL = "https://app.workato.com/recipes/{}"
CONN_URL = "https://app.workato.com/connections/{}"
FOLDER_URL = "https://app.workato.com/recipes?fid={}"


def sh(cmd, timeout=180):
    p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    if p.returncode != 0:
        raise RuntimeError("cmd failed rc=%s: %s\n%s" % (" ".join(cmd), p.returncode, p.stderr[-400:]))
    return p.stdout


def sh_json(prof, cmd):
    out = sh(PROFILES[prof] + cmd)
    try:
        return json.loads(out)
    except json.JSONDecodeError as e:
        raise RuntimeError("non-JSON from %s %s: %r" % (prof, " ".join(cmd), out[:200])) from e


def api_page(prof, path, list_key, page=1):
    """GET path with page param; returns (items, has_more) for both shapes:
    {"items": [...]} (recipes) and {"data": [...]} (data tables) and bare [...]."""
    sep = "&" if "?" in path else "?"
    d = sh_json(prof, ["api", "GET", "%s%spage=%d" % (path, sep, page), "--raw"])
    if isinstance(d, list):
        return d, len(d) >= 100
    items = d.get(list_key, [])
    return items, len(items) >= 100


def api_all(prof, path, list_key):
    out, page = [], 1
    prev_first = None
    while True:
        items, more = api_page(prof, path, list_key, page)
        if items:
            first = json.dumps(items[0], sort_keys=True, default=str)
            if first == prev_first:
                # page param silently ignored — stop, don't duplicate forever
                return out
            prev_first = first
        out.extend(items)
        if not more or page >= 200:
            return out
        page += 1


# ---------------------------------------------------------------- inventory

def folder_paths(folders):
    by_id = {f["id"]: f for f in folders}

    def path_of(fid):
        parts, seen = [], set()
        cur = fid
        while cur and cur in by_id and cur not in seen:
            seen.add(cur)
            parts.append(by_id[cur]["name"])
            cur = by_id[cur].get("parent_id")
        return " / ".join(reversed(parts))

    return {f["id"]: path_of(f["id"]) for f in folders}


def resolve_subfolders(prof, folders, referenced_ids):
    """The /api/folders list endpoint returns ONLY project-root folders; recipes
    and connections live in subfolders the list never shows. Fetch every
    referenced folder_id not in the list via GET /api/folders/<id> (threaded,
    read-only) so folder-path joins are real paths, not '?'."""
    known = {f["id"]: f for f in folders}
    missing = sorted({fid for fid in referenced_ids if fid and fid not in known})[:3000]
    if missing:
        print("  [%s] fetching %d subfolders not in folder list..." % (prof, len(missing)), file=sys.stderr)
        from concurrent.futures import ThreadPoolExecutor
        def get(fid):
            try:
                return fid, sh_json(prof, ["api", "GET", "/api/folders/%s" % fid, "--raw"])
            except (RuntimeError, json.JSONDecodeError):
                return fid, None
        with ThreadPoolExecutor(max_workers=8) as ex:
            for fid, f in ex.map(get, missing):
                if f and isinstance(f, dict) and f.get("id"):
                    known[f["id"]] = f
    return list(known.values())


def inventory(prof):
    print("  [%s] folders..." % prof, file=sys.stderr)
    folders = api_all(prof, "/api/folders?per_page=100", None)
    print("  [%s] recipes..." % prof, file=sys.stderr)
    recipes = api_all(prof, "/api/recipes?per_page=100", "items")
    print("  [%s] connections (%d)..." % (prof, 0), file=sys.stderr)
    conns = sh_json(prof, ["api", "GET", "/api/connections?per_page=100", "--raw"])
    print("  [%s] lookup tables..." % prof, file=sys.stderr)
    lookups = api_all(prof, "/api/lookup_tables?per_page=100", None)
    print("  [%s] data tables..." % prof, file=sys.stderr)
    dtables = api_all(prof, "/api/data_tables?per_page=100", "data")
    print("  [%s] properties..." % prof, file=sys.stderr)
    props = sh_json(prof, ["properties", "list", "--raw"])
    referenced = {r.get("folder_id") for r in recipes} | {c.get("folder_id") for c in conns}
    folders = resolve_subfolders(prof, folders, referenced)
    fpaths = folder_paths(folders)
    return {
        "folders": folders,
        "recipes": recipes,
        "connections": conns,
        "lookups": lookups,
        "dtables": dtables,
        "properties": props if isinstance(props, dict) else {},
        "folder_paths": fpaths,
    }


# ------------------------------------------------- normalization / hashing

def build_id_map(dev, prod):
    """Cross-env id -> '@type:name@' token map. Both envs feed the same map:
    each env's own ids resolve to the shared asset NAME, so identical assets
    normalize identically even though their ids differ."""
    m = {}

    def put(asset_id, token):
        s = str(asset_id)
        if not s or s in ("None", "null"):
            return
        if s.isdigit() and len(s) < 5:  # small numbers are data, not ids
            return
        if s in m and m[s] != token:
            m[s] = "@ambiguous@"  # collide: neutralize rather than mis-rename
        else:
            m[s] = token

    for inv in (dev, prod):
        for c in inv["connections"]:
            put(c.get("id"), "conn:%s" % c.get("name"))
        for r in inv["recipes"]:
            put(r.get("id"), "recipe:%s" % r.get("name"))
        for t in inv["lookups"]:
            put(t.get("id"), "lookup:%s" % t.get("name"))
        for t in inv["dtables"]:
            tid, nid, name = t.get("id"), t.get("numeric_id"), t.get("name")
            put(tid, "dtable:%s" % name)
            if nid:
                put(nid, "dtable:%s" % name)
            for f in t.get("schema") or []:
                put(f.get("field_id"), "dfield:%s.%s" % (name, f.get("name")))
        for f in inv["folders"]:
            put(f.get("id"), "folder:%s" % f.get("name"))
    return m


NUM_RE = re.compile(r"(?<!\d)\d{5,}(?!\d)")
UUID_RE = re.compile(r"(?<![0-9a-fA-F-])[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}"
                     r"-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}(?![0-9a-fA-F-])")


CTS_RE = re.compile(r"(?<=_)(1[5-8]\d{8})(?!\d)")  # unix-ts suffix in custom-connector names


def compile_re(id_map, dev=None, prod=None):
    """Split the id map into linear-lookup dicts (UUIDs first, then numeric runs).
    A single regex alternation over ~13k ids was quadratic and unusable on a
    6k-recipe estate; dict-lookup substitution is O(text). Also captures each
    env's workspace id (recipes carry it as user_id) — custom-connector app
    names embed it (`work_genie_connector_<ws>_<unixts>`), and the two envs'
    workspace ids + connector timestamps differ for identical code."""
    ws = set()
    for inv in (dev, prod):
        if not inv:
            continue
        ids = [r.get("user_id") for r in inv["recipes"] if r.get("user_id")]
        if ids:
            ws.add(str(max(set(ids), key=ids.count)))
    return {
        "uuid": {k: v for k, v in id_map.items() if not k.isdigit()},
        "num": {k: v for k, v in id_map.items() if k.isdigit()},
        "ws": ws,
    }


def scrub_schema_defaults(obj):
    """Recursively zero out `default` values on schema fields named *_id —
    per-env reference UUIDs/ids that the id->name map can't know (they point
    at OTHER assets' per-env UUIDs). Recurses into nested JSON strings too."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if (k in ("default", "value") and isinstance(obj.get("name"), str)
                    and obj["name"].endswith("_id") and isinstance(v, str)
                    and (len(v) >= 5 and (v.isdigit() or UUID_RE.fullmatch(v)))):
                out[k] = "@ref:%s@" % obj["name"]
            else:
                out[k] = scrub_schema_defaults(v)
        return out
    if isinstance(obj, list):
        return [scrub_schema_defaults(x) for x in obj]
    if isinstance(obj, str) and obj.startswith(("[", "{")):
        try:
            inner = json.loads(obj)
        except (json.JSONDecodeError, ValueError):
            return obj
        scrubbed = json.dumps(scrub_schema_defaults(inner), sort_keys=True, separators=(",", ":"))
        return scrubbed
    return obj


def normalize_recipe(recipe_env, id_map, rx):
    """Return canonical normalized text of one recipe envelope for hashing."""
    env = dict(recipe_env)
    for k in list(env):
        if k in VOLATILE_KEYS or k.startswith("version_"):
            env.pop(k, None)  # version_* = provenance (author/comment), not function
    code = env.pop("code", None)
    if isinstance(code, str):
        try:
            code = json.loads(code)
        except (json.JSONDecodeError, TypeError):
            code = {"__unparsed_code__": code}
    code = scrub_schema_defaults(code)
    env["code"] = code
    text = json.dumps(env, sort_keys=True, separators=(",", ":"))
    if rx is not None:
        # UUIDs first (a UUID's digit groups could otherwise match NUM_RE).
        if rx["uuid"]:
            text = UUID_RE.sub(lambda m: rx["uuid"].get(m.group(0), m.group(0)), text)
        if rx["num"]:
            text = NUM_RE.sub(lambda m: rx["num"].get(m.group(0), m.group(0)), text)
        if rx.get("ws"):
            text = re.sub(r"(?<!\d)(" + "|".join(re.escape(w) for w in rx["ws"]) + r")(?!\d)",
                          "@workspace@", text)
        text = CTS_RE.sub("@cts@", text)  # custom-connector unix-ts suffix
    return text


def sha(s):
    return hashlib.sha256(s.encode("utf-8", "replace")).hexdigest()[:16]


def parse_ts(ts):
    if not ts:
        return None
    try:
        t = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
        if t.tzinfo is None:
            t = t.replace(tzinfo=dt.timezone.utc)
        return t
    except ValueError:
        return None


# ---------------------------------------------------------------- diffing

def join_key(folder_path, name):
    return (folder_path.lower().strip(), name.lower().strip())


def classify(dev, prod, scope):
    id_map = build_id_map(dev, prod)
    rx = compile_re(id_map, dev, prod)

    scope_re = re.compile(re.escape(scope), re.I) if scope else None

    def in_scope(fpath):
        return True if not scope_re else bool(scope_re.search(fpath or ""))

    out = OrderedDict((k, []) for k in (
        "missing_in_prod", "code_differs", "newer_in_dev", "orphaned_in_prod",
        "connection_missing_in_prod", "connection_reauth", "property_divergence"))

    d_fp = dev["folder_paths"]
    p_fp = prod["folder_paths"]

    # -- recipes: strict folder-path + name join --------------------------------
    d_rec, p_rec = {}, {}
    for r in dev["recipes"]:
        d_rec[join_key(d_fp.get(r.get("folder_id"), "?"), r.get("name", ""))] = r
    for r in prod["recipes"]:
        p_rec[join_key(p_fp.get(r.get("folder_id"), "?"), r.get("name", ""))] = r

    for key, dr in sorted(d_rec.items()):
        fp, name = key
        if not in_scope(fp):
            continue
        pr = p_rec.get(key)
        d_url = REC_URL.format(dr["id"])
        if pr is None:
            out["missing_in_prod"].append({
                "type": "recipe", "name": dr.get("name"), "folder_path": fp,
                "dev_id": dr["id"], "prod_id": None,
                "url": d_url, "dev_updated_at": dr.get("updated_at")})
            continue
        norm_d = normalize_recipe(dr, id_map, rx)
        norm_p = normalize_recipe(pr, id_map, rx)
        raw_eq = (dr.get("code") or "") == (pr.get("code") or "")
        norm_eq = norm_d == norm_p
        entry = {
            "type": "recipe", "name": dr.get("name"), "folder_path": fp,
            "dev_id": dr["id"], "prod_id": pr["id"],
            "url": d_url, "prod_url": REC_URL.format(pr["id"]),
            "dev_updated_at": dr.get("updated_at"), "prod_updated_at": pr.get("updated_at"),
            "dev_version": dr.get("version_no"), "prod_version": pr.get("version_no"),
            "raw_hashes_equal": raw_eq,
            "dev_hash": sha(norm_d), "prod_hash": sha(norm_p),
            "normalized_hashes_equal": norm_eq,
        }
        if not norm_eq:
            out["code_differs"].append(entry)
        elif parse_ts(dr.get("updated_at")) and parse_ts(pr.get("updated_at")) \
                and parse_ts(dr.get("updated_at")) > parse_ts(pr.get("updated_at")):
            out["newer_in_dev"].append(entry)

    for key, pr in sorted(p_rec.items()):
        fp, name = key
        if key in d_rec or not in_scope(fp):
            continue
        out["orphaned_in_prod"].append({
            "type": "recipe", "name": pr.get("name"), "folder_path": fp,
            "dev_id": None, "prod_id": pr["id"], "url": REC_URL.format(pr["id"]),
            "prod_updated_at": pr.get("updated_at"),
            "note": "prod-only — confirm intent (may be an intentional delete; never auto-remove)"})

    # -- folders ----------------------------------------------------------------
    d_folders = {join_key(d_fp.get(f["id"], "?"), f["name"]): f for f in dev["folders"]
                 if in_scope(d_fp.get(f["id"], "?"))}
    p_folders = {join_key(p_fp.get(f["id"], "?"), f["name"]): f for f in prod["folders"]
                 if in_scope(p_fp.get(f["id"], "?"))}
    for key, f in sorted(d_folders.items()):
        if key not in p_folders:
            out["missing_in_prod"].append({
                "type": "folder", "name": f["name"], "folder_path": key[0],
                "dev_id": f["id"], "prod_id": None, "url": FOLDER_URL.format(f["id"])})
    for key, f in sorted(p_folders.items()):
        if key not in d_folders:
            out["orphaned_in_prod"].append({
                "type": "folder", "name": f["name"], "folder_path": key[0],
                "dev_id": None, "prod_id": f["id"], "url": FOLDER_URL.format(f["id"]),
                "note": "prod-only — confirm intent"})

    # -- connections ------------------------------------------------------------
    d_conn, p_conn = {}, {}
    for c in dev["connections"]:
        fp = d_fp.get(c.get("folder_id"), "?")
        if in_scope(fp):
            d_conn[join_key(fp, c.get("name", ""))] = c
    for c in prod["connections"]:
        fp = p_fp.get(c.get("folder_id"), "?")
        if in_scope(fp):
            p_conn[join_key(fp, c.get("name", ""))] = c

    for key, dc in sorted(d_conn.items()):
        fp, name = key
        pc = p_conn.get(key)
        if pc is None:
            out["connection_missing_in_prod"].append({
                "type": "connection", "name": dc.get("name"), "adapter": dc.get("application"),
                "folder_path": fp, "dev_id": dc["id"], "prod_id": None,
                "url": CONN_URL.format(dc["id"])})
        else:
            bad = (pc.get("authorization_status") not in (None, "success")
                   or (pc.get("authorized_at") in (None, "") and pc.get("connection_lost_at")))
            if bad:
                out["connection_reauth"].append({
                    "type": "connection", "name": pc.get("name"), "adapter": pc.get("application"),
                    "folder_path": fp, "dev_id": dc["id"], "prod_id": pc["id"],
                    "url": CONN_URL.format(pc["id"]),
                    "prod_authorization_status": pc.get("authorization_status"),
                    "prod_authorized_at": pc.get("authorized_at"),
                    "prod_connection_lost_at": pc.get("connection_lost_at")})
    for key, pc in sorted(p_conn.items()):
        if key not in d_conn:
            out["orphaned_in_prod"].append({
                "type": "connection", "name": pc.get("name"), "adapter": pc.get("application"),
                "folder_path": key[0], "dev_id": None, "prod_id": pc["id"],
                "url": CONN_URL.format(pc["id"]), "note": "prod-only — confirm intent"})

    # -- lookup + data tables: name join (no folder_id exposed by these APIs) ----
    def table_class(d_list, p_list, ttype):
        d_by = {t.get("name", "").lower(): t for t in d_list}
        p_by = {t.get("name", "").lower(): t for t in p_list}

        def norm_schema(t):
            try:
                sch = json.loads(t["schema"]) if isinstance(t.get("schema"), str) else (t.get("schema") or [])
                cols = [{k: v for k, v in f.items() if k in ("name", "type", "label", "sticky", "optional")}
                        for f in sch]
                return json.dumps(cols, sort_keys=True)
            except (json.JSONDecodeError, AttributeError, TypeError):
                return json.dumps(t.get("schema"), sort_keys=True, default=str)

        for n, t in sorted(d_by.items()):
            if n not in p_by:
                out["missing_in_prod"].append({
                    "type": ttype, "name": t.get("name"), "folder_path": None,
                    "dev_id": t.get("id"), "prod_id": None, "url": None})
            elif norm_schema(t) != norm_schema(p_by[n]):
                out["code_differs"].append({
                    "type": ttype, "name": t.get("name"), "folder_path": None,
                    "dev_id": t.get("id"), "prod_id": p_by[n].get("id"),
                    "url": None, "detail": "schema differs",
                    "dev_hash": sha(norm_schema(t)), "prod_hash": sha(norm_schema(p_by[n]))})
        for n, t in sorted(p_by.items()):
            if n not in d_by:
                out["orphaned_in_prod"].append({
                    "type": ttype, "name": t.get("name"), "folder_path": None,
                    "dev_id": None, "prod_id": t.get("id"), "url": None,
                    "note": "prod-only — confirm intent"})

    table_class(dev["lookups"], prod["lookups"], "lookup_table")
    table_class(dev["dtables"], prod["dtables"], "data_table")

    # -- properties -------------------------------------------------------------
    # Workspace-level, NOT folder-scopable: only reported on unscoped runs.
    if not scope:
        d_props, p_props = dev["properties"], prod["properties"]
        for k in sorted(set(d_props) | set(p_props)):
            dv, pv = d_props.get(k), p_props.get(k)
            if dv != pv:
                out["property_divergence"].append({
                    "type": "property", "name": k,
                    "dev_value": scrub_value(dv), "prod_value": scrub_value(pv),
                    "note": "missing in prod" if pv is None else
                            ("missing in dev" if dv is None else "value differs")})

    return out


def scrub_value(v, cap=80):
    """Property values can embed secrets (tokens), including nested inside
    JSON-ish strings. Redact any 32+ char credential-shaped run, then truncate."""
    if v is None:
        return None
    s = str(v)
    s = re.sub(r"[A-Za-z0-9_\-]{32,}", "<redacted>", s)
    if len(s) > cap:
        return s[:cap] + "...<truncated len=%d>" % len(s)
    return s


# ------------------------------------------------------------------ output

def md_report(res, scope, generated_at):
    L = ["# Workato env-diff — dev vs prod", "",
         "Generated: %s · Scope: %s · READ-ONLY (dev wt 3535597 / prod 3535598)" % (
             generated_at, scope or "whole estate"), ""]

    def sec(title, entries, render):
        L.append("## %s (%d)" % (title, len(entries)))
        if not entries:
            L.append("_none_", "")
            L.append("")
            return
        for e in entries:
            L.append(render(e))
        L.append("")

    def rec_render(e):
        parts = ["**%s**" % e["name"], "— dev %s" % (e.get("dev_id") or "-"),
                 "prod %s" % (e.get("prod_id") or "-")]
        if e.get("url"):
            parts.append(e["url"])
        if e.get("prod_url"):
            parts.append(e["prod_url"])
        if "folder_path" in e and e["folder_path"]:
            parts.append("folder: %s" % e["folder_path"])
        extra = []
        for k in ("dev_updated_at", "prod_updated_at", "dev_version", "prod_version",
                  "raw_hashes_equal", "dev_hash", "prod_hash", "adapter",
                  "prod_authorization_status", "detail", "note", "type"):
            if k in e and e[k] is not None and k != "type":
                extra.append("%s=%s" % (k, e[k]))
        return "- " + " · ".join(parts) + ("\n  - " + "; ".join(extra) if extra else "")

    sec("MISSING_IN_PROD", res["missing_in_prod"], rec_render)
    sec("CODE_DIFFERS", res["code_differs"], rec_render)
    sec("NEWER_IN_DEV (code identical, dev touched more recently)", res["newer_in_dev"], rec_render)
    sec("ORPHANED_IN_PROD (prod-only — confirm intent, never auto-remove)", res["orphaned_in_prod"], rec_render)
    sec("CONNECTION_MISSING_IN_PROD", res["connection_missing_in_prod"], rec_render)
    sec("CONNECTION_REAUTH (prod copy looks unauthorized)", res["connection_reauth"], rec_render)
    sec("PROPERTY_DIVERGENCE", res["property_divergence"],
        lambda e: "- **%s** — dev=%r prod=%r (%s)" % (e["name"], e.get("dev_value"), e.get("prod_value"), e.get("note")))
    return "\n".join(L)


def load_cache():
    with open(CACHE) as f:
        d = json.load(f)
    if not d.get("generated_at") or "classes" not in d:
        raise RuntimeError("cache at %s is not a valid env-diff registry (rebuild with a live run)" % CACHE)
    return d


def first_divergence(norm_d, norm_p, ctx=240):
    i = next((i for i, (a, b) in enumerate(zip(norm_d, norm_p)) if a != b), min(len(norm_d), len(norm_p)))
    lo = max(0, i - ctx // 2)
    return "at char %d\n  dev ...%s...\n  prod ...%s..." % (i, norm_d[lo:lo + ctx], norm_p[lo:lo + ctx])


def validate_promoted(name, dev, prod, id_map, rx):
    """Fresh `wt recipes get` on BOTH envs, normalize, compare. get-code is the
    authoritative per-recipe code (the list API returns a slightly leaner shape)."""
    def find(inv):
        n = name.lower().strip()
        hits = [r for r in inv["recipes"] if r.get("name", "").lower().strip() == n]
        return hits[0] if hits else None

    dr, pr = find(dev), find(prod)
    report = {"recipe_name": name,
              "dev_id": dr["id"] if dr else None,
              "prod_id": pr["id"] if pr else None}
    if not dr or not pr:
        report["verdict"] = "FAIL"
        report["reason"] = "recipe not found in %s" % ("dev" if not dr else "prod")
        return report, 2

    def fresh(prof, rid):
        d = sh_json(prof, ["recipes", "get", str(rid), "--raw"])
        return d

    gd, gp = fresh("dev", dr["id"]), fresh("prod", pr["id"])
    raw_d, raw_p = gd.get("code") or "", gp.get("code") or ""
    nd = normalize_recipe(gd, id_map, rx)
    np_ = normalize_recipe(gp, id_map, rx)
    report["dev_url"] = REC_URL.format(dr["id"])
    report["prod_url"] = REC_URL.format(pr["id"])
    report["dev_updated_at"] = dr.get("updated_at")
    report["prod_updated_at"] = pr.get("updated_at")
    report["raw_hash_dev"] = sha(raw_d)
    report["raw_hash_prod"] = sha(raw_p)
    report["raw_hashes_equal"] = raw_d == raw_p
    report["normalized_hash_dev"] = sha(nd)
    report["normalized_hash_prod"] = sha(np_)
    report["normalized_hashes_equal"] = nd == np_

    if nd == np_:
        report["verdict"] = "PASS"
        if raw_d != raw_p:
            report["note"] = ("raw hashes differ but normalized hashes MATCH — the raw diff is "
                              "environment-specific ID churn, which is exactly what normalization exists for")
    else:
        report["verdict"] = "FAIL"
        report["diagnosis"] = first_divergence(nd, np_)
        report["loud_warning"] = (
            "NORMALIZATION-GATE FAILURE: this recipe was believed identical across envs. "
            "If it is genuinely identical, the normalizer is missing an ID-bearing field or "
            "volatile key — treat this as a normalization BUG and fix the normalizer before "
            "trusting any CODE_DIFFERS result. Cross-check the raw code manually at %s and %s"
            % (report["dev_url"], report["prod_url"]))
    return report, (0 if report["verdict"] == "PASS" else 1)


def main():
    ap = argparse.ArgumentParser(description="read-only dev vs prod Workato diff (name+folder-path join, normalized code hashes)")
    ap.add_argument("--project", help="scope to folders whose path contains this substring")
    ap.add_argument("--json", action="store_true", help="machine contract output")
    ap.add_argument("--use-cache", action="store_true",
                    help="read the derived registry at %s instead of live reads" % CACHE)
    ap.add_argument("--validate-promoted", metavar="RECIPE_NAME",
                    help="self-test: assert this known-promoted recipe's normalized hashes MATCH in both envs")
    args = ap.parse_args()

    if args.use_cache:
        d = load_cache()
        if args.validate_promoted:
            print("--validate-promoted requires a live run (cache is never authoritative)", file=sys.stderr)
            return 3
        if args.json:
            print(json.dumps(d, indent=1))
        else:
            print(md_report(d["classes"], d["scope"], d["generated_at"]))
        return 0

    print("Inventorying both envs (read-only)...", file=sys.stderr)
    dev, prod = inventory("dev"), inventory("prod")
    print("dev: %d recipes / %d folders / %d conns / %d lookups / %d dtables" % (
        len(dev["recipes"]), len(dev["folders"]), len(dev["connections"]),
        len(dev["lookups"]), len(dev["dtables"])), file=sys.stderr)
    print("prod: %d recipes / %d folders / %d conns / %d lookups / %d dtables" % (
        len(prod["recipes"]), len(prod["folders"]), len(prod["connections"]),
        len(prod["lookups"]), len(prod["dtables"])), file=sys.stderr)

    id_map = build_id_map(dev, prod)
    rx = compile_re(id_map, dev, prod)

    result = {
        "generated_at": dt.datetime.now(dt.timezone.utc).isoformat(timespec="seconds"),
        "scope": args.project,
        "classes": classify(dev, prod, args.project),
    }

    os.makedirs(os.path.dirname(CACHE), exist_ok=True)
    with open(CACHE, "w") as f:
        json.dump(result, f, indent=1)

    if args.validate_promoted:
        rep, rc = validate_promoted(args.validate_promoted, dev, prod, id_map, rx)
        print(json.dumps(rep, indent=1))
        return rc

    if args.json:
        print(json.dumps(result, indent=1))
    else:
        print(md_report(result["classes"], args.project, result["generated_at"]))
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RuntimeError as e:
        print("ERROR: %s" % e, file=sys.stderr)
        sys.exit(4)
