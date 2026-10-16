#!/usr/bin/env python3
"""ops-collector.py — collection engine for Josh's Workato ops-visibility system.

Subcommands:
  derive-scope   Build ops-visibility/config.json from workato-health/owned-registry.json
                 (prod recipes as scope; --add-folder <env>:<folder_id> to extend).
  collect        One 15-min collection tick: sweep failed jobs (max 40 recipes,
                 oldest-scan first), dedup failures into records-*.jsonl, sample
                 traces of swallow-flagged recipes for swallowed errors, carry
                 forward / resolve open records, regenerate the dashboard.

Stdlib only, Python 3.9+. Never crashes on one bad recipe (logs to stderr, continues).
CLI primitives: wt jobs list / wt jobs get / wt recipes get (profiles josh-prod / josh-us).
"""

import argparse
import hashlib
import json
import os
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone

KNOWLEDGE = os.path.expanduser("~/.claude/knowledge")
OPS_DIR = os.path.join(KNOWLEDGE, "ops-visibility")
CACHE_DIR = os.path.join(OPS_DIR, "cache")
CONFIG_PATH = os.path.join(OPS_DIR, "config.json")
STATE_PATH = os.path.join(OPS_DIR, "state.json")
REGISTRY_PATH = os.path.join(KNOWLEDGE, "workato-health", "owned-registry.json")
ARCHIVE_PATH = os.path.join(OPS_DIR, "records-archive.jsonl")
DASHBOARD_SCRIPT = os.path.join(KNOWLEDGE, "scripts", "ops-dashboard.py")

MAX_SWEEP_PER_TICK = 120
CACHE_TTL_SECONDS = 24 * 3600
RESOLVE_AFTER_SWEEPS = 3
FIRST_SWEEP_LOOKBACK_HOURS = 24  # when no cursor exists, only ingest failures from the last 24h
SWALLOW_RECIPES_PER_TICK = 3
SWALLOW_JOBS_PER_RECIPE = 3
ERROR_TEXT_MAX = 300

PROFILES = {"prod": "josh-prod", "dev": "josh-us"}


def log(msg):
    sys.stderr.write("[ops-collector] %s\n" % msg)


def now_iso():
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def read_json(path, default=None):
    try:
        with open(path, "r") as f:
            return json.load(f)
    except (OSError, ValueError):
        return default


def write_json(path, data):
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        json.dump(data, f, indent=2)
        f.write("\n")
    os.replace(tmp, path)


def wt(args, profile, timeout=90):
    """Run a wt CLI command; return (ok, stdout, stderr)."""
    cmd = ["wt"] + args + ["--profile", profile]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
    except (subprocess.TimeoutExpired, OSError) as exc:
        return False, "", str(exc)
    if proc.returncode != 0:
        return False, proc.stdout, proc.stderr
    return True, proc.stdout, proc.stderr


def wt_raw_json(args, profile, timeout=90):
    """Run wt ... --raw and parse JSON from stdout (wt may print a warning line first).
    Returns (data, err): data is the parsed object or None on failure."""
    ok, out, err = wt(args, profile, timeout=timeout)
    if not ok:
        return None, err
    text = out.strip()
    # Defensive: find the first '{' or '[' in case wt prefixes human warnings.
    idx = min([i for i in (text.find("{"), text.find("[")) if i >= 0] or [-1])
    if idx < 0:
        return None, "no JSON in output: %s" % text[:200]
    try:
        return json.loads(text[idx:]), None
    except ValueError as exc:
        return None, "bad JSON: %s" % exc


# ---------------------------------------------------------------------------
# derive-scope
# ---------------------------------------------------------------------------

def cmd_derive_scope(args):
    registry = read_json(REGISTRY_PATH, {})
    recipes = registry.get("recipes", [])
    prod_ids = sorted({str(r["id"]) for r in recipes
                       if "prod" in (r.get("servers") or [])})
    dev_ids = sorted({str(r["id"]) for r in recipes
                      if "dev" in (r.get("servers") or [])})

    config = read_json(CONFIG_PATH, {}) or {}
    config["prod"] = config.get("prod") or {}
    config["dev"] = config.get("dev") or {}
    config["prod"]["recipe_ids"] = prod_ids
    config["dev"]["recipe_ids"] = dev_ids

    if args.add_folder:
        if ":" not in args.add_folder:
            log("--add-folder must be <env>:<folder_id> (e.g. prod:32312723)")
            return 2
        env, folder_id = args.add_folder.split(":", 1)
        env = env.strip().lower()
        if env not in ("prod", "dev"):
            log("--add-folder env must be 'prod' or 'dev'")
            return 2
        folders = config[env].get("folder_ids") or []
        if folder_id not in folders:
            folders.append(folder_id)
        config[env]["folder_ids"] = folders

    write_json(CONFIG_PATH, config)
    print("derive-scope: %s" % CONFIG_PATH)
    print("  prod recipes in scope: %d%s" % (len(prod_ids), ("  " + ", ".join(prod_ids[:10]) + (" ..." if len(prod_ids) > 10 else "")) if prod_ids else ""))
    print("  dev recipes in scope:  %d" % len(dev_ids))
    for env in ("prod", "dev"):
        fids = config[env].get("folder_ids") or []
        if fids:
            print("  %s folder_ids: %s" % (env, ", ".join(fids)))
    return 0


# ---------------------------------------------------------------------------
# cache: recipe metadata (name, folder_id, project_id, code, swallow_flag)
# ---------------------------------------------------------------------------

SWALLOW_KEYWORDS = ("error_handler", "monitor", "rescue", "handle_error", "on_error_continue")


def compute_swallow_flag(code):
    """Static flag: recipe code contains error-handling blocks that continue
    execution. Conservative — needs an explicit keyword hit."""
    if not isinstance(code, str):
        return False
    low = code.lower()
    return any(kw in low for kw in SWALLOW_KEYWORDS)


def cache_path(env, recipe_id):
    return os.path.join(CACHE_DIR, "%s-%s.json" % (env, recipe_id))


def get_recipe_meta(env, recipe_id):
    """Load cached recipe metadata (24h TTL) or fetch fresh via wt recipes get."""
    cp = cache_path(env, recipe_id)
    cached = read_json(cp)
    if cached and cached.get("fetched_at"):
        try:
            age = time.time() - datetime.strptime(cached["fetched_at"], "%Y-%m-%dT%H:%M:%SZ") \
                .replace(tzinfo=timezone.utc).timestamp()
            if 0 <= age < CACHE_TTL_SECONDS:
                return cached
        except ValueError:
            pass
    data, err = wt_raw_json(["recipes", "get", recipe_id, "--raw"], PROFILES[env])
    if data is None or not isinstance(data, dict):
        log("recipes get %s (%s) failed: %s" % (recipe_id, env, (err or "unknown")[:200]))
        return cached  # stale cache is better than nothing
    meta = {
        "fetched_at": now_iso(),
        "id": str(data.get("id") or recipe_id),
        "name": data.get("name") or ("recipe %s" % recipe_id),
        "folder_id": str(data.get("folder_id") or ""),
        "project_id": str(data.get("project_id") or ""),
        "running": bool(data.get("running")),
        "code_len": len(data.get("code") or "") if isinstance(data.get("code"), str) else 0,
        "swallow_flag": compute_swallow_flag(data.get("code")),
    }
    os.makedirs(CACHE_DIR, exist_ok=True)
    write_json(cp, meta)
    return meta


# ---------------------------------------------------------------------------
# error normalization -> signature
# ---------------------------------------------------------------------------

_NUM_PATTERNS = [
    re.compile(r"\b[0-9a-fA-F]{8}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{4}-[0-9a-fA-F]{12}\b"),  # uuid
    re.compile(r"\b20\d{2}-\d{2}-\d{2}[T ]\d{2}:\d{2}:\d{2}[^\s]*"),  # iso timestamps
    re.compile(r"\b\d{10,}\b"),   # epoch millis
    re.compile(r"\b\d{4,}\b"),    # long numeric ids
    re.compile(r"\b0x[0-9a-fA-F]+\b"),
    re.compile(r"\d+"),           # remaining bare numbers
]


def normalize_error(text):
    """Strip IDs/timestamps/numbers so identical failures dedup to one sig."""
    if not text:
        return "unknown-error"
    t = text.strip()
    t = re.sub(r"\s+", " ", t)
    for pat in _NUM_PATTERNS:
        t = pat.sub("#", t)
    t = re.sub(r"(#{2,})", "#", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t[:200] or "unknown-error"


def make_sig(env, recipe_id, normalized_error):
    raw = "%s|%s|%s" % (env, recipe_id, normalized_error)
    return hashlib.sha1(raw.encode("utf-8")).hexdigest()[:12]


# ---------------------------------------------------------------------------
# record store (records-*.jsonl + records-archive.jsonl)
# ---------------------------------------------------------------------------

def records_glob_paths():
    paths = []
    try:
        for fn in os.listdir(OPS_DIR):
            if re.match(r"^records-\d{4}-\d{2}-\d{2}\.jsonl$", fn):
                paths.append(os.path.join(OPS_DIR, fn))
    except OSError:
        pass
    return sorted(paths)


def load_open_records():
    """Union of all records-*.jsonl lines, keyed by sig (latest last_seen wins).
    Resolved records are excluded (they live in records-archive.jsonl)."""
    store = {}
    for path in records_glob_paths():
        try:
            with open(path, "r") as f:
                for line in f:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except ValueError:
                        continue
                    if not rec.get("sig") or rec.get("resolved"):
                        continue
                    existing = store.get(rec["sig"])
                    if not existing or (rec.get("last_seen") or "") >= (existing.get("last_seen") or ""):
                        rec["sweeps_since_seen"] = existing.get("sweeps_since_seen", 0) \
                            if existing and rec.get("sig") in store else rec.get("sweeps_since_seen", 0)
                        store[rec["sig"]] = rec
        except OSError:
            continue
    return store


def append_archive(rec):
    with open(ARCHIVE_PATH, "a") as f:
        f.write(json.dumps(rec) + "\n")


def write_records_file(store):
    """Rewrite today's records file with all OPEN records (carry-forward +
    today's updates), sorted prod-first then count desc."""
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    path = os.path.join(OPS_DIR, "records-%s.jsonl" % today)
    out = []
    for rec in store.values():
        if rec.get("resolved"):
            continue
        slim = {k: v for k, v in rec.items() if k not in ("sweeps_since_seen",)}
        out.append(slim)
    out.sort(key=lambda r: (
        0 if r.get("env") == "prod" else 1,
        {"open": 0, "sent-to-triage": 1, "diagnosed": 2}.get(r.get("status"), 3),
        -(r.get("count") or 0),
        r.get("sig") or "",
    ))
    tmp = path + ".tmp"
    with open(tmp, "w") as f:
        for rec in out:
            f.write(json.dumps(rec) + "\n")
    os.replace(tmp, path)
    return path


# ---------------------------------------------------------------------------
# job list parsing (defensive around the actual wt output shape)
# ---------------------------------------------------------------------------

def parse_jobs_list(data):
    """Return list of job dicts from a `wt jobs list --raw` payload."""
    if isinstance(data, dict):
        items = data.get("items") or []
        if isinstance(items, list):
            return [it for it in items if isinstance(it, dict)]
    if isinstance(data, list):
        return [it for it in data if isinstance(it, dict)]
    return []


def job_error_text(job):
    """Best available error text. error_parts.message is the real message;
    the flat `error` field can be a job title echo."""
    parts = job.get("error_parts")
    if isinstance(parts, dict):
        msg = parts.get("message") or parts.get("error_type") or ""
        if msg:
            return str(msg)
    return str(job.get("error") or job.get("title") or "unknown-error")


def job_ts(job):
    return job.get("completed_at") or job.get("started_at") or ""


def job_is_newer(job, cursor_ts):
    """Is this job newer than the last-seen cursor timestamp?
    Jobs without timestamps are treated as not newer (skip, defensive)."""
    if not cursor_ts:
        return True
    ts = job_ts(job)
    if not ts:
        return False
    return ts > cursor_ts


# ---------------------------------------------------------------------------
# swallowed-error trace sampling
# ---------------------------------------------------------------------------

def trace_showed_error_path(trace):
    """Conservative: only say an error path ran when the trace clearly shows
    non-empty error_details on an executed line (job still succeeded)."""
    lines = trace.get("lines") if isinstance(trace, dict) else None
    if not isinstance(lines, list):
        return False, "trace has no lines"
    for line in lines:
        if not isinstance(line, dict):
            continue
        details = line.get("error_details")
        if details and (not isinstance(details, dict) or details):
            return True, "line-level error_details present in succeeded trace"
    return False, "no clear error-path marker in trace"


def sample_swallowed(env, recipe_id, meta):
    """Pull up to SWALLOW_JOBS_PER_RECIPE succeeded jobs and detect error-path
    execution. Returns list of (job, reason, trace)."""
    profile = PROFILES[env]
    data, err = wt_raw_json(
        ["jobs", "list", recipe_id, "--status", "succeeded", "--raw"], profile)
    if data is None:
        log("jobs list succeeded %s (%s) failed: %s" % (recipe_id, env, (err or "")[:200]))
        return []
    jobs = [j for j in parse_jobs_list(data) if j.get("status") == "succeeded"]
    results = []
    for job in jobs[:SWALLOW_JOBS_PER_RECIPE]:
        jid = str(job.get("id") or "")
        if not jid:
            continue
        trace, err = wt_raw_json(["jobs", "get", recipe_id, jid, "--raw"], profile)
        if trace is None or not isinstance(trace, dict):
            # be conservative: cannot inspect trace -> do NOT flag
            log("jobs get %s/%s (%s) failed: %s" % (recipe_id, jid, env, (err or "")[:150]))
            continue
        found, reason = trace_showed_error_path(trace)
        if found:
            results.append((job, "error-handler-continue", trace))
    return results


# --- source attribution (Josh 2026-10-09: swallowed captures belong to the
# SOURCE recipe that failed, not the monitor/listener that caught it) ---

MONITOR_NAME_PAT = re.compile(
    r"listener|backstop|monitor|recipeops|watchdog|failure alert", re.I)


def resolve_swallow_source(env, monitor_rid, trace):
    """Return (source_recipe_id, source_recipe_name, resolved) for a captured
    swallow. Self-attributed when the capturing recipe isn't a monitor;
    otherwise the monitor's trace names the source (its trigger fires on the
    source's failed job). Conservative: unresolved -> resolved=False."""
    meta = get_recipe_meta(env, monitor_rid) or {}
    name = meta.get("name") or ""
    if not MONITOR_NAME_PAT.search(name or ""):
        return str(monitor_rid), name, True
    blob = json.dumps(trace)
    # candidate source recipe ids referenced in the trace payload
    cands = re.findall(r'"recipe_id"\s*:\s*"?(\d{6,10})', blob)
    counts = {}
    for c in cands:
        if c != str(monitor_rid):
            counts[c] = counts.get(c, 0) + 1
    for cand, _n in sorted(counts.items(), key=lambda kv: -kv[1]):
        cmeta = get_recipe_meta(env, cand) or {}
        cname = cmeta.get("name") or ""
        if cname and not MONITOR_NAME_PAT.search(cname):
            return cand, cname, True
    return "", "", False


# ---------------------------------------------------------------------------
# collect
# ---------------------------------------------------------------------------

INVENTORY_TTL = 6 * 3600  # seconds; full re-enumeration cadence


def expand_project_scope(env, env_cfg):
    """recipe_ids discovered via config env's project_ids, from a cached
    full /api/recipes enumeration (paginated by ?page= — offset is IGNORED
    by this endpoint and silently returns page 1; wt trap T-collect-001)."""
    project_ids = set(str(p) for p in (env_cfg.get("project_ids") or []))
    if not project_ids:
        return []
    profile = "josh-prod" if env == "prod" else "josh-us"
    inv_path = os.path.join(CACHE_DIR, "%s-recipe-inventory.json" % env)
    inv = read_json(inv_path) or {}
    import time as _time
    fresh = inv and (inv.get("ts") or 0) > _time.time() - INVENTORY_TTL
    if not fresh:
        found = {}
        page = 1
        while True:
            try:
                resp, err = wt_raw_json(["api", "GET",
                                         "/api/recipes?per_page=100&page=%d" % page,
                                         "--profile", profile], profile)
                if resp is None:
                    raise RuntimeError(err or "empty response")
            except Exception as exc:
                log("inventory page %s failed: %r (using stale cache if any)" % (page, exc))
                break
            items = resp.get("items", resp if isinstance(resp, list) else [])
            if not items:
                break
            ids_now = set(str(r["id"]) for r in items)
            if ids_now & set(found):  # server repeating pages — stop
                break
            for r in items:
                found[str(r["id"])] = str(r.get("project_id") or "")
            if len(items) < 100:
                break
            page += 1
            _time.sleep(0.5)
        if found:
            inv = {"ts": _time.time(), "projects": found}
            write_json(inv_path, inv)
    projects = inv.get("projects") or {}
    return [rid for rid, pid in projects.items() if pid in project_ids]


def cmd_collect(args):
    config = read_json(CONFIG_PATH, {}) or {}
    state = read_json(STATE_PATH, {}) or {}
    store = load_open_records()

    # ---- build the sweep list: all scoped recipes, oldest last_scan first ----
    sweep = []
    for env in ("prod", "dev"):
        env_cfg = config.get(env) or {}
        ids = env_cfg.get("recipe_ids") or []
        folder_ids = set(env_cfg.get("folder_ids") or [])
        for rid in ids:
            sweep.append((env, str(rid)))
        # project-scoped recipes: discovered dynamically from the project
        # inventory (cached), so new recipes in a monitored project are
        # picked up without config edits
        for rid in expand_project_scope(env, env_cfg):
            if (env, rid) not in sweep:
                sweep.append((env, rid))
        # folder-scoped recipes live in state (discovered lazily) — include those
        for rid, st in state.items():
            if st.get("env") == env and str(st.get("folder_id") or "") in folder_ids \
                    and (env, str(rid)) not in sweep:
                sweep.append((env, str(rid)))
    sweep.sort(key=lambda pair: (state.get(pair[1], {}).get("last_scan") or ""))

    budget = sweep[:MAX_SWEEP_PER_TICK]

    stats = {"swept": 0, "new": 0, "updated": 0, "swallowed": 0, "errors": 0, "resolved": 0}
    seen_sigs_this_tick = set()
    swallow_candidates = []

    for env, rid in budget:
        st = state.setdefault(rid, {"env": env})
        st.setdefault("env", env)
        try:
            meta = get_recipe_meta(env, rid)
            if meta:
                st["name"] = meta.get("name") or st.get("name")
                st["folder_id"] = meta.get("folder_id") or st.get("folder_id") or ""
                st["project_id"] = meta.get("project_id") or st.get("project_id") or ""
                st["swallow_flag"] = bool(meta.get("swallow_flag"))
            profile = PROFILES[env]
            data, err = wt_raw_json(
                ["jobs", "list", rid, "--status", "failed", "--raw"], profile)
            if data is None:
                log("jobs list failed for recipe %s (%s): %s" % (rid, env, (err or "")[:200]))
                stats["errors"] += 1
                st["last_scan"] = now_iso()
                continue

            jobs = parse_jobs_list(data)
            failed_ids = {str(j.get("id") or "") for j in jobs}
            cursor_ts = st.get("last_seen_job_ts") or ""
            cursor_id = st.get("last_seen_job_id") or ""

            first_sweep = not cursor_ts and not cursor_id
            if first_sweep:
                cutoff = (datetime.now(timezone.utc) -
                          timedelta(hours=FIRST_SWEEP_LOOKBACK_HOURS)) \
                    .strftime("%Y-%m-%dT%H:%M:%S")
            else:
                cutoff = None

            newest_ts = cursor_ts
            newest_id = cursor_id
            processed_here = set()

            for job in jobs:
                jid = str(job.get("id") or "")
                if jid:
                    if jid == cursor_id:
                        break  # reached the cursor — everything before it already seen
                    if not job_is_newer(job, cursor_ts):
                        continue
                    if first_sweep and cutoff and (job_ts(job) or "") < cutoff:
                        continue
                    if jid in processed_here:
                        continue
                    processed_here.add(jid)

                    ts = job_ts(job)
                    if ts > newest_ts:
                        newest_ts, newest_id = ts, jid

                    text = job_error_text(job)[:ERROR_TEXT_MAX]
                    normalized = normalize_error(text)
                    sig = make_sig(env, rid, normalized)
                    seen_sigs_this_tick.add(sig)

                    rec = store.get(sig)
                    seen_ts = ts or now_iso()
                    if rec:
                        rec["count"] = (rec.get("count") or 1) + 1
                        # never regress first/last_seen; keep the newest job
                        if seen_ts > (rec.get("last_seen") or ""):
                            rec["last_seen"] = seen_ts
                        if seen_ts < (rec.get("first_seen") or seen_ts):
                            rec["first_seen"] = seen_ts
                        if seen_ts >= (rec.get("last_seen") or ""):
                            rec["job_id"] = jid
                            rec["job_url"] = "https://app.workato.com/recipes/%s/job/%s" % (rid, jid)
                        rec["sweeps_since_seen"] = 0
                        stats["updated"] += 1
                    else:
                        store[sig] = {
                            "sig": sig, "env": env, "recipe_id": rid,
                            "recipe_name": (meta or {}).get("name") or st.get("name") or ("recipe %s" % rid),
                            "folder_id": (meta or {}).get("folder_id") or st.get("folder_id") or "",
                            "project_id": (meta or {}).get("project_id") or st.get("project_id") or "",
                            "job_id": jid,
                            "job_url": "https://app.workato.com/recipes/%s/job/%s" % (rid, jid),
                            "error": text, "swallowed": False, "swallow_reason": None,
                            "first_seen": ts or now_iso(), "last_seen": ts or now_iso(),
                            "count": 1, "status": "open", "diagnosis": None,
                            "sweeps_since_seen": 0,
                        }
                        stats["new"] += 1

            # resolution check: open record for this recipe not seen this tick
            # for RESOLVE_AFTER_SWEEPS consecutive sweeps AND its job is not in
            # the latest failed list -> archive as resolved
            for sig, rec in list(store.items()):
                if rec.get("resolved") or rec.get("recipe_id") != rid or rec.get("env") != env:
                    continue
                if sig in seen_sigs_this_tick:
                    continue
                rec["sweeps_since_seen"] = rec.get("sweeps_since_seen", 0) + 1
                if rec["sweeps_since_seen"] >= RESOLVE_AFTER_SWEEPS \
                        and str(rec.get("job_id") or "") not in failed_ids:
                    rec["resolved"] = True
                    rec["resolved_ts"] = now_iso()
                    append_archive(rec)
                    store.pop(sig)
                    stats["resolved"] += 1

            if (meta or {}).get("swallow_flag"):
                swallow_candidates.append((env, rid, st, meta))

            st["last_seen_job_id"] = newest_id
            st["last_seen_job_ts"] = newest_ts
            st["last_scan"] = now_iso()
            stats["swept"] += 1
        except Exception as exc:  # never crash the tick on one bad recipe
            log("recipe %s (%s) sweep error: %r" % (rid, env, exc))
            stats["errors"] += 1
            st["last_scan"] = now_iso()

    # ---- swallowed-error trace sampling: max N flagged recipes per tick ----
    # rotate by picking the flagged candidates least recently sampled
    swallow_candidates.sort(key=lambda t: (t[2].get("last_swallow_scan") or ""))
    for env, rid, st, meta in swallow_candidates[:SWALLOW_RECIPES_PER_TICK]:
        try:
            for job, reason, trace in sample_swallowed(env, rid, meta):
                jid = str(job.get("id") or "")
                ts = job_ts(job) or now_iso()
                text = str(job.get("error") or job.get("title") or
                           "error path executed in succeeded job")[:ERROR_TEXT_MAX]
                normalized = normalize_error("swallowed:" + text)
                sig = make_sig(env, rid, normalized)
                seen_sigs_this_tick.add(sig)
                src_id, src_name, resolved = resolve_swallow_source(env, rid, trace)
                rec = store.get(sig)
                if rec:
                    rec["count"] = (rec.get("count") or 1) + 1
                    rec["last_seen"] = ts
                    rec["sweeps_since_seen"] = 0
                    if not rec.get("source_recipe_id") and src_id:
                        rec["source_recipe_id"] = src_id
                        rec["source_recipe_name"] = src_name
                        rec["source_resolved"] = resolved
                    stats["updated"] += 1
                else:
                    is_monitor = bool(MONITOR_NAME_PAT.search(meta.get("name") or ""))
                    subject_id, subject_name = rid, (meta.get("name") or ("recipe %s" % rid))
                    if is_monitor and src_id and src_name and resolved:
                        subject_id, subject_name = src_id, src_name
                    store[sig] = {
                        "sig": sig, "env": env, "recipe_id": subject_id,
                        "recipe_name": subject_name,
                        "captured_by": (meta.get("name") or "") if is_monitor else None,
                        "captured_by_id": str(rid) if is_monitor else None,
                        "source_recipe_id": src_id or None,
                        "source_recipe_name": src_name or None,
                        "source_resolved": resolved,
                        "folder_id": meta.get("folder_id") or "",
                        "project_id": meta.get("project_id") or "",
                        "job_id": jid,
                        "job_url": "https://app.workato.com/recipes/%s/job/%s" % (rid, jid),
                        "error": text, "swallowed": True, "swallow_reason": reason,
                        "first_seen": ts, "last_seen": ts,
                        "count": 1, "status": "open", "diagnosis": None,
                        "sweeps_since_seen": 0,
                    }
                    stats["new"] += 1
                stats["swallowed"] += 1
            st["last_swallow_scan"] = now_iso()
        except Exception as exc:
            log("swallow sampling %s (%s) error: %r" % (rid, env, exc))

    # ---- persist state + records + dashboard ----
    write_json(STATE_PATH, state)
    records_path = write_records_file(store)

    dash_note = ""
    try:
        proc = subprocess.run([sys.executable, DASHBOARD_SCRIPT, "generate"],
                              capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            dash_note = " (dashboard regenerate failed: %s)" % proc.stderr.strip()[:150]
        else:
            dash_note = " (dashboard regenerated)"
    except Exception as exc:
        dash_note = " (dashboard regenerate error: %r)" % exc

    summary = ("tick: swept=%d new=%d updated=%d swallowed=%d resolved=%d errors=%d%s"
               % (stats["swept"], stats["new"], stats["updated"],
                  stats["swallowed"], stats["resolved"], stats["errors"], dash_note))
    print(summary)
    return 0


# ---------------------------------------------------------------------------

def cmd_backfill_sources(args):
    """One-off (repeatable) pass: attribute existing swallowed records to their
    source recipes via the capturing monitor's job trace (Josh 2026-10-09)."""
    store = load_open_records()
    patched, unresolved = 0, 0
    for sig, rec in store.items():
        if not rec.get("swallowed") or rec.get("source_recipe_id"):
            continue
        env = rec.get("env")
        rid = str(rec.get("recipe_id") or "")
        jid = str(rec.get("job_id") or "")
        if not (env and rid and jid):
            continue
        trace, err = wt_raw_json(["jobs", "get", rid, jid, "--raw"], PROFILES[env])
        if trace is None or not isinstance(trace, dict):
            log("backfill %s: trace unavailable (%s)" % (sig, (err or "")[:100]))
            unresolved += 1
            continue
        src_id, src_name, resolved = resolve_swallow_source(env, rid, trace)
        if src_id:
            rec["captured_by"] = rec.get("recipe_name")
            rec["captured_by_id"] = rid
            rec["source_recipe_id"] = src_id or None
            rec["source_recipe_name"] = src_name or None
            rec["source_resolved"] = resolved
            if src_id and src_name and resolved:
                # card subject = source recipe; job_url STAYS on the monitor's
                # job (the evidence lives there; the jid belongs to that recipe)
                rec["recipe_id"] = src_id
                rec["recipe_name"] = src_name
                rec["recipe_url"] = "https://app.workato.com/recipes/%s" % src_id
            patched += 1
        else:
            rec["source_resolved"] = False
            unresolved += 1
    write_records_file(store)
    try:
        subprocess.run([sys.executable, DASHBOARD_SCRIPT, "generate"],
                       capture_output=True, timeout=60)
    except Exception as exc:
        log("dashboard regenerate error: %r" % exc)
    print("backfill-sources: patched=%d unresolved=%d" % (patched, unresolved))
    return 0


def main(argv=None):
    parser = argparse.ArgumentParser(description="ops-visibility collector")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p_scope = sub.add_parser("derive-scope", help="build config.json from owned-registry.json")
    p_scope.add_argument("--add-folder", metavar="ENV:FOLDER_ID",
                         help="add a folder scope, e.g. prod:32312723")
    p_scope.set_defaults(func=cmd_derive_scope)

    p_collect = sub.add_parser("collect", help="run one collection tick")
    p_collect.set_defaults(func=cmd_collect)

    p_backfill = sub.add_parser("backfill-sources",
                                help="re-attribute existing swallowed records to source recipes")
    p_backfill.set_defaults(func=cmd_backfill_sources)

    args = parser.parse_args(argv)
    os.makedirs(CACHE_DIR, exist_ok=True)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
