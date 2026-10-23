#!/usr/bin/env python3
"""external-edit-sweep.py — deterministic Job 4 sweep for the workato-watchdog
(finding watchdog-external-managed-alert-false-positive-class, built 2026-10-23).

The watchdog's external-edit detection ("recipe updated_at moved + no
build-ledger row") used to page EVERY externally-maintained recipe as an
unknown-actor edit. The [DRIFT FIX] project 10593549 (folder 35202337) is
managed:external BY DESIGN — its 10-09 backfill rows (BSYS-29462) are marked
managed:"external" and harness mutations never appear for it, so every Joel
Ang UI repair paged as an unexplained edit (83234662 / 82928217 / 82896390,
adjudicated human work in BSYS-29829 — dispatch-20261022-235738.log).

Classification per in-scope recipe (updated_at vs the baseline sidecar):

  quiet                    no update since the baseline (refreshed each sweep)
  harness-managed          updated, and a harness mutation row (kind
                           airo-mutation, not external_backfill) since baseline
  external-managed-update  updated, no harness mutation, but the recipe carries
                           a managed:"external" ledger row — EXPECTED class,
                           informational, never an unknown-actor page
  unexplained-external-edit  updated, no harness mutation, no managed:external
                           row — the genuine P2 alert class

Every alert body links the Activity Audit Log attribution runbook
(knowledge/projects/drift-fix/bsys-29828-overnight-incident-findings-2026-10-21.md,
proven in BSYS-29829) instead of paging an unknown actor.

The baseline sidecar (workato-health/external-managed-baseline.json) is
refreshed on EVERY sweep for all scoped recipes — this replaces the stale
backfill rows' last_updated:"2026-10-08" as the comparison point without
hand-editing the append-only build ledger (in-place ledger edits race the
atomic writers; the sidecar is the freshness map instead).

Read-only against Workato (wt recipes get). Writes only the sidecar.

Usage:
  external-edit-sweep.py [--recipes id1,id2,...] [--window-hours 48] [--json]
  (no --recipes: scope = every recipe with a managed:external ledger row)
"""
import argparse, json, os, subprocess, sys, datetime as dt

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
LEDGER = os.path.join(K, "build-ledger.jsonl")
BASELINE = os.path.join(K, "workato-health", "external-managed-baseline.json")
WT = os.environ.get("WT_BIN", os.path.expanduser("~/.local/bin/wt"))
PROFILE = {"dev": "josh-us", "prod": "josh-prod"}
RUNBOOK = os.path.join(K, "projects", "drift-fix",
                       "bsys-29828-overnight-incident-findings-2026-10-21.md")
RUNBOOK_URL = ("file://" + RUNBOOK + " (Activity Audit Log attribution method, "
               "proven in BSYS-29829)")

HARNESS_MUTATION_KINDS = {"airo-mutation"}          # harness write rows
BACKFILL_TOOL = "external_backfill"                 # inventory rows, not writes
# Externally-maintained folders (BSYS-29462 named the [DRIFT FIX] project
# 10593549 / folder 35202337 in-scope). Membership by FOLDER, not by backfill
# row alone: net-new externally-created recipes (e.g. 83234662, built by Joel
# Ang 10-21, after the 10-09 backfill) have no managed:external ledger row but
# belong to the class by construction.
EXTERNAL_FOLDERS = {"35202337"}


def parse_ts(s):
    """Epoch seconds for '...Z' (UTC) or '...-07' (Workato PT) ISO shapes."""
    import re as _re
    s = str(s or "").strip()
    if not s:
        return None
    s = _re.sub(r"([+-]\d{2})$", r"\g<1>:00", s)
    s = _re.sub(r"Z$", "+00:00", s)
    for fmt in ("%Y-%m-%dT%H:%M:%S.%f%z", "%Y-%m-%dT%H:%M:%S%z"):
        try:
            return dt.datetime.strptime(s, fmt).timestamp()
        except ValueError:
            continue
    try:
        return dt.datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(
            tzinfo=dt.timezone.utc).timestamp()
    except ValueError:
        return None


def load_ledger():
    """(mutation_rows_by_rid, external_rids). Corrupt line = hard fail."""
    mut, ext = {}, set()
    with open(LEDGER, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError as exc:
                raise SystemExit(f"CORRUPT ledger line {lineno}: {exc}")
            rid = str(r.get("recipe_id") or "")
            if not rid:
                continue
            if r.get("managed") == "external":
                ext.add(rid)
            if r.get("kind") in HARNESS_MUTATION_KINDS and \
                    r.get("tool") != BACKFILL_TOOL:
                mut.setdefault(rid, []).append(r)
    return mut, ext


def wt_recipes_get(rid, server="dev", timeout=25):
    cmd = [WT, "recipes", "get", rid, "--raw", "--profile",
           PROFILE.get(server, "josh-us")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not r.stdout.strip().startswith("{"):
            return None
        return json.loads(r.stdout)
    except (subprocess.TimeoutExpired, ValueError):
        return None


def classify(rid, live_updated_at, mut_rows, is_external, baseline, window_h):
    """Pure classification — unit-testable without Workato.

    Returns (verdict, harness_mutations_since_baseline).
    """
    up = parse_ts(live_updated_at)
    if up is None:
        return "unverifiable", 0
    base = parse_ts((baseline.get(rid) or {}).get("updated_at", ""))
    if base is None:
        # first sight (or pre-fix sweep): fall back to the observation window
        base = dt.datetime.now(dt.timezone.utc).timestamp() - window_h * 3600
    since = [r for r in mut_rows if parse_ts(r.get("ts", "")) and
             parse_ts(r["ts"]) > base]
    if up <= base:
        return "quiet", 0
    if since:
        return "harness-managed", len(since)
    if is_external:
        return "external-managed-update", 0
    return "unexplained-external-edit", 0


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--recipes", default="", help="comma-separated recipe ids")
    ap.add_argument("--window-hours", type=int, default=48)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    mut, ext = load_ledger()
    scope = [r.strip() for r in args.recipes.split(",") if r.strip()] or sorted(ext)
    try:
        loaded = json.load(open(BASELINE))
        # envelope shape written below: {"updated": ..., "recipes": {rid: ...}}
        baseline = loaded.get("recipes", {}) if isinstance(loaded, dict) else {}
    except Exception:
        baseline = {}

    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, pages = [], []
    for rid in scope:
        server = "dev"
        data = wt_recipes_get(rid, server)
        if data is None:
            server = "prod"
            data = wt_recipes_get(rid, server)
        if data is None:
            rows.append({"ts": now, "id": rid, "verdict": "unverifiable",
                         "detail": "wt recipes get failed (dev+prod)"})
            continue
        is_external = rid in ext or str(data.get("folder_id")) in EXTERNAL_FOLDERS
        verdict, n_mut = classify(rid, data.get("updated_at"), mut.get(rid, []),
                                  is_external, baseline, args.window_hours)
        row = {"ts": now, "id": rid, "server": server,
               "name": data.get("name", ""),
               "updated_at": data.get("updated_at"),
               "managed_external": is_external,
               "verdict": verdict,
               "harness_mutations_since_baseline": n_mut,
               "url": f"https://app.workato.com/recipes/{rid}"}
        if verdict == "unexplained-external-edit":
            row["alert"] = (
                f"P2 UNEXPLAINED EXTERNAL EDIT: recipe {rid} "
                f"https://app.workato.com/recipes/{rid} moved to "
                f"{data.get('updated_at')} with no build-ledger mutation and "
                f"no managed:external row — attribute via Activity Audit Log "
                f"before paging: {RUNBOOK_URL}")
            pages.append(row)
        elif verdict == "external-managed-update":
            row["note"] = ("expected class (managed:external by design, "
                           "BSYS-29462) — informational, attribution via "
                           f"Activity Audit Log runbook: {RUNBOOK_URL}")
        rows.append(row)
        # refresh the baseline sidecar EVERY sweep for every scoped recipe —
        # the replacement for the stale backfill last_updated (2026-10-08)
        baseline[rid] = {"updated_at": data.get("updated_at"),
                         "checked_ts": now, "verdict": verdict}

    os.makedirs(os.path.dirname(BASELINE), exist_ok=True)
    json.dump({"updated": now, "recipes": baseline}, open(BASELINE, "w"), indent=1)

    counts = {}
    for r in rows:
        counts[r["verdict"]] = counts.get(r["verdict"], 0) + 1
    line = (f"external-edit sweep: {len(rows)} scoped -> {counts} | "
            f"{len(pages)} unexplained P2 page(s)")
    if args.json:
        print(json.dumps({"ts": now, "counts": counts, "rows": rows,
                          "runbook": RUNBOOK_URL}, indent=1))
    else:
        print(line)
        for p in pages:
            print(p["alert"])
    return 0 if not pages else 2  # exit 2 = genuine unexplained pages exist


if __name__ == "__main__":
    sys.exit(main())
