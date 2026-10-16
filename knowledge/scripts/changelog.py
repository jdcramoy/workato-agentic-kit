#!/usr/bin/env python3
"""changelog.py — per-project change report from the build ledger + live estate.

Delta 1 of the env-diff/promotion-tracking spec (knowledge/specs/
env-diff-promotion-tracking.md). Derive-on-demand, zero new state:

  changelog.py --project <folder-substring | BSYS-ticket> --since YYYY-MM-DD [--json]

Scope resolution:
  - Folder substring (case-insensitive) against `wt folders list` (dev ws
    3535597) — matched folders AND all their descendant folders.
  - BSYS-xxxxx ticket: ledger rows with that ticket -> recipe ids -> folders.
    Epic/summary correlation to folder names via normalized token overlap;
    weak or conflicting correlation goes to FLAGGED MISMATCHES, never silently
    grouped (Josh's ruling: folder = deployment truth, epic = governance).

Sections (markdown default, --json for the machine contract):
  NEW ASSETS            first ledger touch ever falls inside the window
  UPDATED ASSETS        ledger rows in window, first touch predates window
  CONNECTIONS & TABLES TOUCHED   classified from window ledger commands
  CHANGED WITH NO LEDGER ENTRY   recipe updated_at in window, zero ledger
                        rows in window -> catches out-of-harness edits
  FLAGGED MISMATCHES    ticket<->folder and epic<->folder problems

Attribution: primary = ledger rows with recipe_id == recipe. Command-mention
rows (the id appears in the command text but recipe_id is null) are used only
as fallback attribution when a recipe has zero primary rows in the window —
grep-style mentions are too noisy to outrank the typed field.

Ledger parsing HARD-FAILS on corrupt lines (exit 2 with the line number) —
never skips them. Read-only: the only subprocess calls are `wt api GET ...`.

Reads: ~/.claude/knowledge/build-ledger.jsonl (required),
       ~/.claude/knowledge/garden-reports/recipes-index.jsonl (optional
       weekly cache; falls back to live wt reads when absent/stale).
"""
import argparse
import datetime as dt
import json
import os
import re
import subprocess
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
LEDGER = HOME / ".claude" / "knowledge" / "build-ledger.jsonl"
INDEX = HOME / ".claude" / "knowledge" / "garden-reports" / "recipes-index.jsonl"
WT = os.environ.get("WT_BIN", "wt")
RECIPE_URL = "https://app.workato.com/recipes/{id}"

TICKET_RE = re.compile(r"^BSYS-\d+$", re.I)

# command-classification patterns for CONNECTIONS & TABLES TOUCHED
CONN_RE = re.compile(r"connection", re.I)
DTABLE_RE = re.compile(r"data_table|/api/data_tables|\bwt\s+dt\b", re.I)
LOOKUP_RE = re.compile(r"lookup", re.I)

STOPWORDS = {
    "the", "a", "an", "and", "or", "of", "to", "in", "for", "on", "with",
    "wt", "api", "get", "post", "head", "python3", "json", "sys", "import",
    "echo", "grep", "head", "raw", "bin", "local", "orchestrator", "report",
    "recipes", "recipe", "list", "manifests", "packages", "folders",
}


def e(msg):
    sys.stderr.write(f"changelog: {msg}\n")


def die(msg, code=2):
    e(msg)
    sys.exit(code)


def iso_now():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ---------------------------------------------------------------- wt helpers

def wt_api(path, query=None, timeout=60):
    """One read-only `wt api GET` call; returns parsed JSON or dies."""
    cmd = [WT, "api", "GET", path, "--raw"]
    for q in query or []:
        cmd += ["--query", q]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except FileNotFoundError:
        die(f"`{WT}` not found — the wt CLI is required for live reads")
    except subprocess.TimeoutExpired:
        die(f"`wt api GET {path}` timed out after {timeout}s")
    if p.returncode != 0:
        die(f"`wt api GET {path}` failed (rc={p.returncode}): {p.stderr.strip()[:300]}")
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        die(f"`wt api GET {path}` returned non-JSON output")


def load_folders():
    """All dev folders (paged). Returns {id: {'id','name','parent_id',
    'project_id'}}. NOTE: this listing OMITS most subfolders (live-verified
    2026-10-10: 1,053 of 1,209 recipe folder_ids are absent from it) — it is
    usable for name matching only; scope membership goes through
    recipe.project_id, which every recipe carries directly."""
    folders = {}
    page = 1
    while True:
        resp = wt_api("/api/folders", query=["per_page=100", f"page={page}"])
        items = resp if isinstance(resp, list) else resp.get("items", [])
        if not items:
            break
        for f in items:
            folders[f["id"]] = {"id": f["id"], "name": f.get("name") or "",
                                "parent_id": f.get("parent_id"),
                                "project_id": f.get("project_id")}
        if len(items) < 100:
            break
        page += 1
    return folders


def load_projects():
    """All dev projects (paged) — the app/service grouping unit the spec
    names. Returns {id: {'id','name','folder_id'}}."""
    projects = {}
    page = 1
    while True:
        resp = wt_api("/api/projects", query=[f"page={page}"])
        items = resp if isinstance(resp, list) else resp.get("items", [])
        if not items:
            break
        for p in items:
            projects[p["id"]] = {"id": p["id"], "name": p.get("name") or "",
                                 "folder_id": p.get("folder_id")}
        if len(items) < 100:
            break
        page += 1
    return projects


def folder_name(fid, folders):
    """Folder name with on-demand direct GET — the /api/folders listing
    omits some subfolders (live-verified: folder 33036555 'Operational
    Monitoring' absent from all listing pages, present via direct GET)."""
    if fid in folders:
        return folders[fid]["name"]
    resp = wt_api(f"/api/folders/{fid}")
    if isinstance(resp, dict) and resp.get("id"):
        folders[resp["id"]] = {"id": resp["id"],
                               "name": resp.get("name") or "",
                               "parent_id": resp.get("parent_id"),
                               "project_id": resp.get("project_id")}
        return folders[resp["id"]]["name"]
    return str(fid)


def all_recipes():
    """The full dev recipe inventory (paged live read, one `page` param per
    call). Workato's Developer API supports folder_id/updated_after filters,
    but the wt passthrough silently drops query filters once more than two
    --query args are given (live-verified 2026-10-10: 3 params -> unfiltered
    6,316-item response), so ALL filtering is done client-side over one
    complete inventory pass instead of trusting server-side filters."""
    out = {}
    page = 1
    while True:
        resp = wt_api("/api/recipes", query=[f"page={page}"])
        items = resp.get("items", []) if isinstance(resp, dict) else resp
        for r in items:
            out[r["id"]] = r
        if not items or len(items) < 100:
            break
        page += 1
    return out


def recipes_in_scope(allr, project_ids, folder_ids):
    """Recipes belonging to the scoped projects (project_id — carried on
    every recipe, immune to the folders-listing gaps) or directly to the
    scoped folder ids."""
    return [r for r in allr.values()
            if r.get("project_id") in project_ids
            or r.get("folder_id") in folder_ids]


def recipe_get(recipe_id):
    """Live single-recipe read; None if the recipe no longer exists."""
    cmd = [WT, "api", "GET", f"/api/recipes/{recipe_id}", "--raw"]
    try:
        p = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if p.returncode != 0:
        return None
    try:
        return json.loads(p.stdout)
    except json.JSONDecodeError:
        return None


# ------------------------------------------------------------------ ledger

def load_index():
    """Optional weekly corpus index (recipes-index.jsonl). Cache only —
    absent/stale is fine, live wt reads are the source of truth. Returns
    {recipe_id: row} or {}."""
    if not INDEX.exists():
        return {}
    out = {}
    with INDEX.open("r", errors="replace") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                die(f"CORRUPT index line {lineno} in {INDEX}: {line[:120]!r}")
            if not isinstance(r, dict):
                die(f"CORRUPT index line {lineno}: not a JSON object")
            if r.get("recipe_id"):
                out[r["recipe_id"]] = r
    return out


def load_ledger():
    """Parse the build ledger. HARD-FAIL on any corrupt line (never skip)."""
    if not LEDGER.exists():
        die(f"build ledger not found: {LEDGER}")
    rows = []
    with LEDGER.open("r", errors="strict") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError as exc:
                die(f"CORRUPT ledger line {lineno} in {LEDGER} ({exc}); "
                    f"refusing to skip: {line[:120]!r}")
            if not isinstance(row, dict):
                die(f"CORRUPT ledger line {lineno}: not a JSON object: {line[:120]!r}")
            rows.append(row)
    return rows


def window_rows(rows, since):
    """Rows on/after `since` (ts[:10] lexicographic on ISO dates)."""
    return [r for r in rows if str(r.get("ts", ""))[:10] >= since]


def primary_rows(rows, recipe_id):
    return [r for r in rows if r.get("recipe_id") == recipe_id]


def mention_rows(rows, recipe_id):
    """Fallback attribution: the id appears in the command text."""
    needle = str(recipe_id)
    return [r for r in rows
            if r.get("recipe_id") is None and needle in str(r.get("command", "") or "")]


def row_ts(r):
    return str(r.get("ts", ""))


def row_tickets(rs):
    return sorted({str(r["ticket"]) for r in rs if r.get("ticket")})


# ------------------------------------------------- epic/folder correlation

def normalize_tokens(text):
    """Lowercase, split on non-alphanumerics, drop stopwords + pure numbers."""
    out = set()
    for tok in re.split(r"[^a-z0-9]+", str(text or "").lower()):
        if len(tok) > 2 and tok not in STOPWORDS and not tok.isdigit():
            out.add(tok)
    return out


def correlate_tokens_to_folders(tokens, folders):
    """Josh's ruling: correlate epic/summary text to folder names by
    normalized token overlap + substring matching (stdlib only).

    Returns (scored, ambiguous) where scored is a descending list of
    (folder_id, name, overlap_count) for folders with >=1 token hit, and
    ambiguous is True when the top two scores tie or overlap is very thin.
    """
    scored = []
    for fid, f in folders.items():
        ftoks = normalize_tokens(f["name"])
        # token overlap
        overlap = len(tokens & ftoks)
        # substring match: a long folder-name token contained in the query
        # text or vice versa
        for tok in tokens:
            for ftok in ftoks:
                if len(tok) >= 4 and len(ftok) >= 4 and (tok in ftok or ftok in tok):
                    overlap += 0.5
        if overlap > 0:
            scored.append((fid, f["name"], overlap))
    scored.sort(key=lambda x: -x[2])
    ambiguous = False
    if scored:
        top = scored[0][2]
        ties = [s for s in scored if s[2] >= top * 0.99]
        if len(ties) > 1 or top < 1.5:
            ambiguous = True
    return scored, ambiguous


def _idx_stub(rid, idx):
    """Corpus-index view of a recipe (folder_id/name only), or None."""
    r = idx.get(rid)
    if not r:
        return None
    return {"id": rid, "folder_id": r.get("folder_id"),
            "name": r.get("name"), "updated_at": r.get("updated_at")}


# ------------------------------------------------------------------ model

def asset_entry(rid, name, tickets, last_ts, extra=None):
    entry = {
        "id": rid,
        "name": name,
        "url": RECIPE_URL.format(id=rid),
        "tickets": tickets,
        "last_event_ts": last_ts,
    }
    if extra:
        entry.update(extra)
    return entry


def classify_command(r):
    """-> category or None for CONNECTIONS & TABLES TOUCHED."""
    cmd = str(r.get("command", "") or "") + " " + str(r.get("tool", "") or "")
    if CONN_RE.search(cmd):
        return "connection"
    if LOOKUP_RE.search(cmd):
        return "lookup_table"
    if DTABLE_RE.search(cmd):
        return "data_table"
    return None


def conn_entry(r, category):
    evidence = str(r.get("command", "") or "")
    if not evidence:
        evidence = " ".join(
            s for s in (str(r.get("tool", "") or ""),
                        str(r.get("asset_name", "") or "")) if s
        ).strip() or "(no command text)"
    entry = {
        "type": category,
        # collapse whitespace: ledger command strings contain newlines and
        # markdown headers that would otherwise break the report layout
        "evidence": " ".join(evidence.split())[:160],
        "ts": row_ts(r),
        "ticket": r.get("ticket"),
    }
    if r.get("recipe_id"):
        entry["recipe_id"] = r["recipe_id"]
        entry["recipe_url"] = RECIPE_URL.format(id=r["recipe_id"])
    return entry


# ------------------------------------------------------------------ main

def resolve_scope(arg, rows, folders, projects, allr, idx):
    """-> (project_ids, folder_ids, matched_names, flags, ticket_arg)

    Scope membership is PROJECT-based (spec: folder/project = the app/service
    unit; the epic is governance, not deployment truth). Folder-substring
    matches contribute their project_id; direct folder ids are also kept for
    folders with no project mapping."""
    flags = []
    ticket_arg = None
    low = arg.strip().lower()

    if TICKET_RE.match(arg):
        ticket_arg = arg.upper()
        # ledger rows with this exact ticket -> recipe ids -> projects
        trows = [r for r in rows
                 if str(r.get("ticket", "")).upper() == ticket_arg]
        rids = {r["recipe_id"] for r in trows if r.get("recipe_id")}
        tprojects, tfolders = set(), set()
        for rid in rids:
            live = allr.get(rid) or _idx_stub(rid, idx) or recipe_get(rid)
            if live and (live.get("project_id") or live.get("folder_id")):
                if live.get("project_id"):
                    tprojects.add(live["project_id"])
                if live.get("folder_id"):
                    tfolders.add(live["folder_id"])
            else:
                flags.append({
                    "type": "ticket_recipe_unresolved",
                    "detail": f"ticket {ticket_arg} touched recipe {rid} "
                              f"({RECIPE_URL.format(id=rid)}) which no longer "
                              f"resolves live — kept out of scope",
                })
        # epic/summary correlation: tokens from ledger text mentioning the
        # ticket, vs project/folder names (Josh's ruling: flag, never
        # silently group)
        tokens = normalize_tokens(" ".join(
            str(r.get("command", "") or "") + " " + str(r.get("asset_name", "") or "")
            for r in rows if ticket_arg.lower() in
            (str(r.get("command", "") or "").lower() + str(r.get("ticket", "") or "").lower())))
        scored, ambiguous = correlate_tokens_to_folders(tokens, {**projects, **folders})
        tnames = sorted({folder_name(f, folders) for f in tfolders})
        if not scored and not tprojects and not tfolders:
            flags.append({
                "type": "epic_folder_no_correlation",
                "detail": f"{ticket_arg} has no ledger recipe_id rows and its "
                          f"ledger text correlated to zero projects — scope is empty",
            })
        elif ambiguous:
            names = ", ".join(f"{n} ({s:g})" for _, n, s in scored[:5]) or "none"
            flags.append({
                "type": "epic_folder_ambiguous",
                "detail": f"{ticket_arg} token correlation is ambiguous "
                          f"(thin or tied): {names}. Scope comes from ledger "
                          f"recipe_id rows only.",
            })
        elif scored and scored[0][0] not in tprojects and scored[0][0] not in tfolders:
            flags.append({
                "type": "epic_folder_mismatch",
                "detail": f"{ticket_arg} ledger recipes live in project(s) "
                          f"{sorted(projects[p]['name'] for p in tprojects if p in projects) or tnames}, "
                          f"but its text correlates best to "
                          f"{scored[0][1]} — verify the ticket is in the right project",
            })
        return tprojects, tfolders, [f"{ticket_arg} (via ledger ticket rows)"], flags, ticket_arg

    proj_matches = [p for p in projects.values() if low in p["name"].lower()]
    fold_matches = [f for f in folders.values() if low in f["name"].lower()]
    if not proj_matches and not fold_matches:
        close = ", ".join(
            p["name"] for p in sorted(projects.values(), key=lambda x: x["name"])
            if low[:4] and low[:4] in p["name"].lower())[:400]
        die(f"no dev project/folder name contains '{arg}' and it is not a "
            f"BSYS-xxxxx ticket. Closest project names: {close or '(none)'}")

    project_ids = {p["id"] for p in proj_matches}
    folder_ids = {f["id"] for f in fold_matches}
    # a folder match without its own project mapping stays folder-scoped;
    # folder matches WITH a project_id roll up to the project
    for f in fold_matches:
        if f.get("project_id"):
            project_ids.add(f["project_id"])
    names = sorted({p["name"] for p in proj_matches}
                   | {f["name"] for f in fold_matches})
    n_matched = len(proj_matches) + len(fold_matches)
    if n_matched > 1:
        flags.append({
            "type": "folder_multi_match",
            "detail": f"'{arg}' matched {n_matched} project(s)/folder(s): "
                      + ", ".join(names) + " — all included",
        })
    return project_ids, folder_ids, names, flags, None


def build_report(arg, since, json_mode):
    rows = load_ledger()
    folders = load_folders()
    projects = load_projects()
    allr = all_recipes()   # id -> recipe dict, full live inventory
    idx = load_index()     # optional weekly cache, never authoritative
    win = window_rows(rows, since)

    project_ids, folder_ids, scope_names, flags, ticket_arg = \
        resolve_scope(arg, rows, folders, projects, allr, idx)

    # recipes in scope, from the live inventory (project-based; folder ids
    # as fallback for folders with no project mapping)
    scoped = recipes_in_scope(allr, project_ids, folder_ids)
    scope_rids = {r["id"] for r in scoped}

    # window ledger rows attributable to scoped recipes (primary + fallback)
    scoped_win = [r for r in win if r.get("recipe_id") in scope_rids]
    # for ticket-scoped runs, also include the ticket's rows even if the
    # recipe fell outside the live snapshot
    if ticket_arg:
        seen = {r.get("recipe_id") for r in scoped_win}
        for r in win:
            if str(r.get("ticket", "")).upper() == ticket_arg and r.get("recipe_id") not in seen:
                scoped_win.append(r)
                seen.add(r.get("recipe_id"))

    # NEW vs UPDATED per recipe
    new_entries, updated_entries = [], []
    for rid in sorted(scope_rids):
        prow = primary_rows(rows, rid)
        wrows = [r for r in prow if row_ts(r)[:10] >= since]
        if not wrows:
            # fallback attribution: command-mention rows in window
            frows = [r for r in mention_rows(win, rid)]
            if frows:
                wrows = frows
        if not wrows:
            continue
        allp = prow or mention_rows(rows, rid)
        first_ts = min((row_ts(r) for r in allp), default="")
        live = allr.get(rid) or {}
        name = live.get("name")
        if not name:
            stub = _idx_stub(rid, idx)
            name = (stub or {}).get("name") or (recipe_get(rid) or {}).get("name") \
                or f"recipe {rid}"
        entry = asset_entry(rid, name, row_tickets(wrows),
                            max((row_ts(r) for r in wrows), default=""))
        if first_ts and first_ts[:10] >= since:
            entry["first_event_ts"] = first_ts
            new_entries.append(entry)
        else:
            updated_entries.append(entry)

    # CONNECTIONS & TABLES TOUCHED
    conn_entries, seen_conn = [], set()
    for r in scoped_win:
        cat = classify_command(r)
        if not cat:
            continue
        e_ = conn_entry(r, cat)
        key = (cat, e_["evidence"], e_["ts"])
        if key not in seen_conn:
            seen_conn.add(key)
            conn_entries.append(e_)
    conn_entries.sort(key=lambda x: x["ts"])

    # CHANGED WITH NO LEDGER ENTRY — grouped by project (the deployment unit)
    no_ledger = []
    for r in sorted(scoped, key=lambda x: (x.get("project_id") or 0, x["id"])):
        rid = r["id"]
        upd = str(r.get("updated_at", ""))[:10]
        if upd < since:
            continue
        if primary_rows(rows, rid) or mention_rows(win, rid):
            continue
        pid = r.get("project_id")
        gname = projects.get(pid, {}).get("name") if pid else None
        if not gname and r.get("folder_id"):
            gname = folder_name(r["folder_id"], folders)
        no_ledger.append(asset_entry(
            rid, r.get("name") or f"recipe {rid}", [], upd,
            extra={"folder": gname or str(pid or r.get("folder_id") or "?")}))

    # ticket<->scope mismatch flag: recipes attributed to this scope but
    # whose ledger tickets also touch recipes OUTSIDE it. Out-of-scope
    # recipes are resolved from the live inventory first; missing ones need
    # a per-id live read, capped to keep the run bounded.
    if scope_rids and not ticket_arg:
        tickets_here = set()
        for rid in scope_rids:
            tickets_here |= set(row_tickets(primary_rows(rows, rid)))
        for t in sorted(tickets_here):
            other_rids = {r["recipe_id"] for r in rows
                          if str(r.get("ticket", "")) == t
                          and r.get("recipe_id")
                          and r["recipe_id"] not in scope_rids}
            other_names = set()
            unresolved = 0
            for oid in sorted(other_rids):
                live = allr.get(oid) or (recipe_get(oid) if len(other_rids) <= 20 else None)
                if live and (live.get("project_id") not in project_ids
                             or live.get("project_id") is None):
                    pname = projects.get(live.get("project_id"), {}).get("name")
                    if not pname and live.get("folder_id"):
                        pname = folder_name(live["folder_id"], folders)
                    if pname:
                        other_names.add(pname)
                elif live is None:
                    unresolved += 1
            if other_names:
                flags.append({
                    "type": "ticket_folder_span",
                    "detail": f"ticket {t} touches recipes in this project AND "
                              f"in other project(s): {', '.join(sorted(other_names))}",
                })
            elif unresolved:
                flags.append({
                    "type": "ticket_span_unresolved",
                    "detail": f"ticket {t} also references {unresolved} recipe(s) "
                              f"that no longer resolve live (deleted or "
                              f"pre-window) — span check incomplete for it",
                })

    sections = {
        "new": new_entries,
        "updated": updated_entries,
        "connections_tables": conn_entries,
        "no_ledger_entry": no_ledger,
        "flagged": flags,
    }

    payload = {
        "generated_at": iso_now(),
        "project": arg,
        "scope_projects": scope_names,
        "since": since,
        "sections": sections,
    }

    if json_mode:
        # contract: {"project","since","sections":{new,updated,
        # connections_tables,no_ledger_entry,flagged}} — extra keys allowed,
        # contract keys always present.
        print(json.dumps(payload, indent=2, default=str))
        return 0

    # ---------------- markdown ----------------
    out = []
    out.append(f"# CHANGELOG — {arg} (since {since})")
    out.append("")
    out.append(f"generated {payload['generated_at']} | scope projects: "
               + (", ".join(payload["scope_projects"]) or "(none)"))
    out.append("")

    def render_assets(title, entries, note=None):
        out.append(f"## {title}")
        if note:
            out.append(f"_{note}_")
        if not entries:
            out.append("(none)")
        for ent in entries:
            tix = ", ".join(ent["tickets"]) if ent.get("tickets") else "no ticket"
            first = f"; first touch {ent['first_event_ts']}" \
                    if ent.get("first_event_ts") else ""
            out.append(f"- {ent['name']} (id {ent['id']}) "
                       f"<{ent['url']}> — ticket: {tix} — "
                       f"last event: {ent.get('last_event_ts', '?')}{first}")
        out.append("")

    render_assets("NEW ASSETS", new_entries,
                  "first ledger touch inside the window")
    render_assets("UPDATED ASSETS", updated_entries,
                  "ledger rows in window, asset predates the window")

    out.append("## CONNECTIONS & TABLES TOUCHED")
    if not conn_entries:
        out.append("(none)")
    for e_ in conn_entries:
        who = f" recipe {e_['recipe_id']} <{e_['recipe_url']}>" if e_.get("recipe_id") else ""
        out.append(f"- {e_['type']} — {e_['evidence']} — {e_['ts']} "
                   f"— ticket: {e_.get('ticket') or 'none'}{who}")
    out.append("")

    out.append("## CHANGED WITH NO LEDGER ENTRY")
    out.append("_(live updated_at in window, zero ledger rows — possible "
               "out-of-harness edit)_")
    if not no_ledger:
        out.append("(none)")
    for ent in no_ledger:
        out.append(f"- {ent['name']} (id {ent['id']}) <{ent['url']}> — "
                   f"project: {ent.get('folder', '?')} — "
                   f"updated_at: {ent.get('last_event_ts', '?')} — no ticket")
    out.append("")

    out.append("## FLAGGED MISMATCHES")
    if not flags:
        out.append("(none)")
    for f in flags:
        out.append(f"- [{f['type']}] {f['detail']}")
    out.append("")

    print("\n".join(out))
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="per-project Workato changelog from the build ledger")
    ap.add_argument("--project", required=True,
                    help="dev folder name substring or BSYS-xxxxx ticket/epic")
    ap.add_argument("--since", required=True, metavar="YYYY-MM-DD",
                    help="window start (inclusive)")
    ap.add_argument("--json", action="store_true",
                    help="emit the machine contract instead of markdown")
    args = ap.parse_args()
    try:
        dt.date.fromisoformat(args.since)
    except ValueError:
        die(f"--since must be YYYY-MM-DD, got {args.since!r}")
    return build_report(args.project, args.since, args.json)


if __name__ == "__main__":
    sys.exit(main())
