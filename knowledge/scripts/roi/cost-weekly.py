#!/usr/bin/env python3
# cost-weekly.py — repeatable weekly cost attribution for Josh's Claude Code traffic
# (turns the one-off "$3,371/7d segmentation" in
#  knowledge/reviews/harness-cost-benefit-2026-10-11.md into a re-runnable script).
#
# Zero-LLM, stdlib only. Read-only on transcripts; the only writes are the
# output JSON below. Run: python3 cost-weekly.py [--weeks 8] [--out path]
# Rate override: ROI_RATE_PER_M env (default 0.325 $/M billed-equivalent).
#   0.325 = gateway My-spend actual $1,467 (Oct 1-14 2026) / 4,519M billed-equiv
#   over the same window (1,350M uncached + 0.1*29,600M cached + 4*52.2M output).
#   Prior default 1.34 was calibrated against the Usage-per-user est_cost_usd
#   column, de-authorized 2026-10-14 (est ran ~2.7-3.3x hot vs My-spend billing).
#
# BILLED-EQUIVALENT MODEL (same as the addendum):
#   billed_equiv = uncached_input + 0.10 * cache_read + 4.0 * output
#   cache_creation_input_tokens are counted as uncached input (1x) — the
#   addendum's daily table did not price writes separately; documented here
#   so the choice is auditable.
#   dollars = billed_equiv / 1e6 * ROI_RATE_PER_M
#
# BUCKET RULES (cwd + keyword heuristics, applied per session in this order —
# mirrors the addendum's classification; documented so they're auditable):
#
# 1. FLEET RUN — the session is a fleet job spawn. Fleet jobs (launchd ->
#    knowledge/config/fleet/run-job.sh) always spawn claude with cwd
#    ~/Documents/workbench and a first user prompt beginning with a bracket
#    tag matching a known job prompt (jobs/*.prompt first line "[name ...]").
#    Rule: first real user message starts with '[' AND cwd is workbench
#    (with a token-prefixed-tag fallback when the jobs dir is absent).
# 2. HARNESS IMPROVEMENT — meta-work on the agent harness itself: cwd under
#    ~/.claude or ~/Documents/Claude, OR the session's first user text hits a
#    harness keyword (harness, brain-gardener, dream report, garden report,
#    usage-ledger, cost-benefit, claim ledger, watchdog, session-shadow,
#    launchd, fleet validation, INDEX.md, knowledge tree).
# 3. WORKATO PROJECT WORK — delivery work: cwd under ~/Documents/Workday,
#    ~/Documents/workbench, ~/orca/, or any path containing workato/gw-semantic/
#    workday, OR first user text mentions Workato delivery terms (workato,
#    recipe, airo, genie, bsys, GW Semantic, wsdl, data table, connector, jira).
# 4. OTHER — anything else (codex, tmp scratch, one-offs).
#
# Caveats inherited from the addendum, restated honestly:
#   - cwd+keyword bucketing is heuristic; workbench non-fleet interactive
#     sessions can mix general ops into WORKATO.
#   - Fleet runs glm-5.3-flash (cheapest lane); uniform $/billed-equiv
#     across models overstates fleet's dollar share.
#   - Week attribution is per-TURN timestamp (not per-session), so resumed
#     sessions split cleanly across weeks — the addendum's daily table used
#     whole-session spans and was approximate; this is not.
#   - Local Claude Code transcripts only (no other clients' usage).

import json
import os
import re
import sys
import glob
from collections import defaultdict
from datetime import datetime, timezone, timedelta

PROJECTS_DIR = os.path.expanduser("~/.claude/projects")
OUT_PATH = os.path.expanduser("~/.claude/knowledge/roi/data/cost-weekly.json")
FLEET_JOBS_DIR = os.path.expanduser("~/.claude/knowledge/config/fleet/jobs")

RATE = float(os.environ.get("ROI_RATE_PER_M", "0.325"))
CACHE_DISCOUNT = 0.10
OUT_MULTIPLIER = 4.0

HARNESS_CWD_PREFIXES = (
    os.path.expanduser("~/.claude"),
    os.path.expanduser("~/Documents/Claude"),
)
HARNESS_KEYWORDS = (
    "harness", "brain-gardener", "gardener", "dream report", "garden report",
    "usage-ledger", "cost-benefit", "claim ledger", "watchdog", "session-shadow",
    "launchd", "fleet-validation", "index.md", "knowledge tree",
)
WORKATO_CWD_MARKERS = ("workato", "gw-semantic", "workday")
WORKATO_CWD_PREFIXES = (
    os.path.expanduser("~/Documents/Workday"),
    os.path.expanduser("~/Documents/workbench"),
    os.path.expanduser("~/orca"),
)
WORKATO_KEYWORDS = (
    "workato", "recipe", "airo", "genie", "bsys", "gw semantic", "gw-semantic",
    "wsdl", "data table", "data_table", "connector", "jira",
)


def week_start(dt):
    """ISO week start (Monday) as a date, from an aware datetime."""
    d = dt.astimezone(timezone.utc).date()
    return d - timedelta(days=d.weekday())


def iso_week_key(date_obj):
    y, w, _ = date_obj.isocalendar()
    return "%04d-W%02d" % (y, w)


def load_fleet_tags():
    """Leading bracket tags from fleet job prompts, e.g. '[cortex-coordinator-pulse]'."""
    tags = set()
    if os.path.isdir(FLEET_JOBS_DIR):
        for p in glob.glob(os.path.join(FLEET_JOBS_DIR, "*.prompt")):
            try:
                with open(p, errors="ignore") as f:
                    head = f.read(200).lstrip()
                m = re.match(r"\[([A-Za-z0-9_-]+)", head)
                if m:
                    tags.add(m.group(1).lower())
            except OSError:
                pass
    return tags


FLEET_TAGS = load_fleet_tags()


def bucket_session(cwd, first_user_text):
    text = (first_user_text or "").lower()
    # 1. FLEET
    if cwd and os.path.normpath(cwd) == os.path.expanduser("~/Documents/workbench"):
        stripped = text.lstrip()
        if stripped.startswith("["):
            tag = re.match(r"\[([A-Za-z0-9_-]+)", stripped)
            if tag and (tag.group(1).lower() in FLEET_TAGS or re.match(r"^[a-z0-9-]+-[a-z0-9-]+$", tag.group(1))):
                return "FLEET"
        # fallback: any fleet job tag appearing verbatim near the prompt head
        for t in FLEET_TAGS:
            if t and t in text[:200]:
                return "FLEET"
    # 2. HARNESS
    if cwd and any(os.path.normpath(cwd).startswith(os.path.normpath(p)) for p in HARNESS_CWD_PREFIXES):
        return "HARNESS"
    if any(k in text for k in HARNESS_KEYWORDS):
        return "HARNESS"
    # 3. WORKATO
    lc = (cwd or "").lower()
    if any(m in lc for m in WORKATO_CWD_MARKERS) or any(
        os.path.normpath(cwd).startswith(os.path.normpath(p)) for p in WORKATO_CWD_PREFIXES
    ):
        return "WORKATO"
    if any(k in text for k in WORKATO_KEYWORDS):
        return "WORKATO"
    return "OTHER"


def parse_ts(s):
    if not s:
        return None
    try:
        return datetime.strptime(s[:19], "%Y-%m-%dT%H:%M:%S").replace(tzinfo=timezone.utc)
    except ValueError:
        return None


def first_user_text_of(msg):
    """Extract stripped text from a user-message content field ('' if none)."""
    content = msg.get("content")
    if isinstance(content, str):
        txt = content
    elif isinstance(content, list):
        txt = " ".join(
            c.get("text", "") for c in content if isinstance(c, dict) and c.get("type") == "text"
        )
    else:
        txt = ""
    return txt.strip()


def new_session(d, path):
    return {
        "bucket": None, "first_ts": d.get("timestamp"),
        "weeks": defaultdict(lambda: [0, 0]), "cwd": d.get("cwd"),
        "path": path, "user_seen": False, "first_user_text": "",
    }


def main():
    weeks = 8
    out_path = OUT_PATH
    argv = sys.argv[1:]
    if "--weeks" in argv:
        weeks = int(argv[argv.index("--weeks") + 1])
    if "--out" in argv:
        out_path = argv[argv.index("--out") + 1]

    now = datetime.now(timezone.utc)
    cutoff = week_start(now) - timedelta(weeks=weeks - 1)

    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    # cheap prefilter: skip files not touched since the window opened
    cutoff_epoch = datetime.combine(cutoff, datetime.min.time(), tzinfo=timezone.utc).timestamp()
    files = [f for f in files if os.path.getmtime(f) >= cutoff_epoch]

    sessions = {}  # sid -> accumulators

    for path in files:
        try:
            with open(path, errors="ignore") as f:
                for line in f:
                    if '"usage"' not in line and '"type":"user"' not in line and '"type": "user"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except json.JSONDecodeError:
                        continue
                    is_user = d.get("type") == "user" and not d.get("isSidechain")
                    msg = d.get("message") or {}
                    usage = msg.get("usage")
                    if not usage and not is_user:
                        continue
                    sid = d.get("sessionId") or d.get("session_id") or os.path.basename(path)[:-6]
                    s = sessions.get(sid)
                    if s is None:
                        s = sessions[sid] = new_session(d, path)
                    if d.get("timestamp") and (s["first_ts"] is None or d["timestamp"] < s["first_ts"]):
                        s["first_ts"] = d.get("timestamp")
                    if is_user and not s["user_seen"]:
                        txt = first_user_text_of(msg)
                        if txt and not txt.startswith("<"):
                            s["user_seen"] = True
                            s["first_user_text"] = txt[:2000]
                    if not usage:
                        continue
                    ts = parse_ts(d.get("timestamp"))
                    wk_date = week_start(ts) if ts else None
                    wk = iso_week_key(wk_date) if wk_date else None
                    if wk and wk_date < cutoff:
                        continue
                    inp = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
                    cache = usage.get("cache_read_input_tokens") or 0
                    out = usage.get("output_tokens") or 0
                    be = inp + CACHE_DISCOUNT * cache + OUT_MULTIPLIER * out
                    if wk:
                        s["weeks"][wk][0] += be
                        s["weeks"][wk][1] += 1
        except (OSError, UnicodeDecodeError):
            continue

    # finalize buckets
    for sid, s in sessions.items():
        if s["bucket"] is None:
            s["bucket"] = bucket_session(s["cwd"], s["first_user_text"])

    # weekly rollup
    all_weeks = sorted({wk for s in sessions.values() for wk in s["weeks"]})
    weekly = {}
    for wk in all_weeks:
        entry = {"total_usd": 0.0, "sessions": 0, "turns": 0, "by_bucket_usd": {}, "by_bucket_sessions": {}}
        for s in sessions.values():
            if wk in s["weeks"]:
                be, turns = s["weeks"][wk]
                usd = be / 1e6 * RATE
                entry["total_usd"] = round(entry["total_usd"] + usd, 2)
                entry["sessions"] += 1
                entry["turns"] += turns
                b = s["bucket"]
                entry["by_bucket_usd"][b] = round(entry["by_bucket_usd"].get(b, 0.0) + usd, 2)
                entry["by_bucket_sessions"][b] = entry["by_bucket_sessions"].get(b, 0) + 1
        weekly[wk] = entry

    # top-10 most expensive sessions over the whole window
    tops = []
    for sid, s in sessions.items():
        be = sum(v[0] for v in s["weeks"].values())
        if be <= 0:
            continue
        tops.append({
            "session_id": sid,
            "bucket": s["bucket"],
            "first_ts": s["first_ts"],
            "usd": round(be / 1e6 * RATE, 2),
            "turns": sum(v[1] for v in s["weeks"].values()),
        })
    tops.sort(key=lambda t: -t["usd"])

    result = {
        "generated_at": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "rate_per_m_billed_equiv": RATE,
        "billed_equiv_formula": "uncached_in(incl cache_creation @1x) + 0.10*cache_read + 4.0*output",
        "window_weeks": weeks,
        "window_start_monday": cutoff.strftime("%Y-%m-%d"),
        "files_scanned": len(files),
        "sessions_total": len(sessions),
        "weekly": weekly,
        "top10_sessions": tops[:10],
    }

    os.makedirs(os.path.dirname(out_path), exist_ok=True)
    with open(out_path, "w") as f:
        json.dump(result, f, indent=2)

    # stdout: compact weekly table
    print("week      sessions  turns      $ (by bucket)")
    for wk in all_weeks:
        e = weekly[wk]
        buckets = " ".join("%s=%.0f" % (b, v) for b, v in sorted(e["by_bucket_usd"].items()))
        print("%s  %5d  %8d  %9.0f  %s" % (wk, e["sessions"], e["turns"], e["total_usd"], buckets))
    print("\nwrote %s" % out_path)


if __name__ == "__main__":
    main()
