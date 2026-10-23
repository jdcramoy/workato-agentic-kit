#!/usr/bin/env python3
"""spend-refresh.py — keep the AI spend ledger current between manual gateway pulls.

Anchors on the billing-grade gateway actuals (the manual My-spend pull, e.g.
"2026-10-01 to 2026-10-14" at $1,467.07), calibrates a blended $/billed-equiv
rate from the overlap with local session telemetry, then projects the days
AFTER the actuals window end using that rate. Writes the projection back as a
clearly-marked projected window so spend-ingest / ai-spend / the console stay
current without waiting for the next manual pull.

Idempotent: replaces its own projected window each run; the manual actuals
windows are never modified. A new manual pull supersedes the projection
naturally (overlap rule: any projected window overlapping a real window is
dropped first).

Run: python3 spend-refresh.py [--dry-run]
Output: updates data/gateway-actuals.json (windows + derived_monthly).
"""
import glob
import json
import os
import sys
from datetime import datetime, date, timedelta, timezone

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi")
GA_PATH = os.path.join(ROI, "data", "gateway-actuals.json")
PROJECTS_DIR = os.path.join(HOME, ".claude", "projects")
CACHE_DISCOUNT = 0.10
OUT_MULTIPLIER = 4.0
LABOR_DAY_RATE = 600.0  # unused here; documented constant of the ROI family


def parse_ts(s):
    try:
        return datetime.fromisoformat(str(s).replace("Z", "+00:00"))
    except Exception:
        return None


def billed_equiv_by_day():
    """Per-UTC-day billed-equivalent tokens from local session transcripts.
    Same usage fields and formula as cost-weekly.py (audited there)."""
    import time
    by_day = {}
    files = glob.glob(os.path.join(PROJECTS_DIR, "*", "*.jsonl"))
    for path in files:
        try:
            if os.path.getmtime(path) < (time.time() - 40 * 86400):
                continue  # cheap prefilter: nothing older than 40d matters
        except OSError:
            continue
        try:
            with open(path, errors="ignore") as f:
                for line in f:
                    if '"usage"' not in line:
                        continue
                    try:
                        d = json.loads(line)
                    except Exception:
                        continue
                    msg = d.get("message") or {}
                    usage = msg.get("usage")
                    if not usage:
                        continue
                    ts = parse_ts(d.get("timestamp"))
                    if ts is None:
                        continue
                    day = ts.strftime("%Y-%m-%d")
                    inp = (usage.get("input_tokens") or 0) + (usage.get("cache_creation_input_tokens") or 0)
                    cache = usage.get("cache_read_input_tokens") or 0
                    out = usage.get("output_tokens") or 0
                    be = inp + CACHE_DISCOUNT * cache + OUT_MULTIPLIER * out
                    if be > 0:
                        by_day[day] = by_day.get(day, 0.0) + be
        except (OSError, UnicodeDecodeError):
            continue
    return by_day


def window_days(win):
    """'2026-10-01 to 2026-10-14' -> [date, date] inclusive."""
    try:
        a, b = win.split(" to ")
        return date.fromisoformat(a), date.fromisoformat(b)
    except Exception:
        return None, None


def main():
    dry = "--dry-run" in sys.argv
    ga = json.load(open(GA_PATH))
    windows = ga.setdefault("windows", [])

    # 1. anchor = the billing-grade edge. Windows merged by a previous run
    # carry actual_usd + actuals_through (the true billing edge); pristine
    # manual windows anchor on their own end.
    actuals_end = None
    actuals = None
    for w in windows:
        edge = w.get("actuals_through")
        a, b = window_days(w.get("window", ""))
        if edge:
            try:
                b = date.fromisoformat(edge)
            except Exception:
                b = None
        if not b or w.get("projected") and not edge:
            continue  # a pure projection never anchors
        if actuals_end is None or b > actuals_end:
            actuals_end = b
            actuals = w
    if actuals is None:
        print("no manual actuals window found; nothing to anchor on")
        return

    # a merged (previously projected) entry carries actual_usd at ENTRY level;
    # its combined usd must never re-enter the projection base
    actual_usd = float(actuals.get("actual_usd") or (actuals.get("joshua_cramoy") or {}).get("usd") or 0)

    # 2. per-day billed-equiv from telemetry
    by_day = billed_equiv_by_day()

    # 3. calibrate: rate = actual usd / transcript billed-equiv over the SAME days
    a_start, a_end = window_days(actuals.get("window", ""))[0], actuals_end
    overlap_be = 0.0
    d = a_start
    while d and a_end and d <= a_end:
        overlap_be += by_day.get(d.isoformat(), 0.0)
        d += timedelta(days=1)
    if overlap_be <= 0:
        print("no transcript coverage in the actuals window; cannot calibrate")
        return
    rate = actual_usd / overlap_be  # $ per billed-equiv token

    # 4. project every day after the actuals end that has telemetry
    drop = set()
    keep_start = actuals_end + timedelta(days=1)
    today = datetime.now(timezone.utc).date()
    proj_start, proj_end = None, None
    proj_be = 0.0
    d = keep_start
    while d <= today:
        if d.isoformat() in by_day:
            if proj_start is None:
                proj_start = d
            proj_end = d
            proj_be += by_day[d.isoformat()]
        d += timedelta(days=1)
    proj_days = (proj_end - proj_start).days + 1 if proj_start else 0

    proj_usd = round(proj_be * rate, 2)

    # MONTH-TO-DATE MERGE: rewrite the actuals window as one entry spanning
    # actual start -> projection end, actual dollars + projected dollars
    # combined. Consumers (console tiles) read one window and get the true
    # month-to-date; the actual/projected split stays in the entry + the
    # derived_monthly block. A new manual pull replaces this entry wholesale.
    a_start = window_days(actuals.get("window", ""))[0]
    mtd_entry = {
        "window": f"{a_start.isoformat()} to {proj_end.isoformat()}",
        "joshua_cramoy": {
            # requests stay ACTUALS-ONLY: telemetry has no gateway request count
            "requests": (actuals.get("joshua_cramoy") or {}).get("requests"),
            "usd": round(actual_usd + proj_usd, 2),
            # per-model split = actuals through the billing edge (the projected
            # days are blended telemetry; never fabricate a per-model split)
            "per_model": (actuals.get("joshua_cramoy") or {}).get("per_model") or {},
            "billed_equiv_tokens": round(overlap_be + proj_be),
        },
        "projected": True,
        "actual_usd": actual_usd,
        "actuals_through": actuals_end.isoformat(),
        "projected_usd": proj_usd,
        "projection_note": (f"actual ${actual_usd} through {actuals_end.isoformat()} "
                            f"+ projected ${proj_usd} at "
                            f"{round(rate * 1e6, 4)} $/M billed-equiv "
                            f"(transcript-calibrated); superseded by the next "
                            f"manual My-spend pull"),
    }
    fresh_windows = [w for w in windows if not w.get("projected")
                     and window_days(w.get("window", ""))[1] != actuals_end]
    fresh_windows.append(mtd_entry)

    # 5. month-to-date roll for derived_monthly consumers
    month = proj_end.strftime("%Y-%m") if proj_end else None
    derived = ga.setdefault("derived_monthly", {})
    if month:
        # single source of truth: drop any other month_to_date spellings
        for k in [k for k in derived if k.endswith("_month_to_date") and k != f"{month}_month_to_date"]:
            del derived[k]
        derived[f"{month}_month_to_date"] = {
            "usd": round(actual_usd + proj_usd, 2),
            "actuals_through": actuals_end.isoformat(),
            "projected_through": proj_end.isoformat(),
            "actual_usd": actual_usd,
            "projected_usd": proj_usd,
        }

    ga["windows"] = fresh_windows
    ga["spend_refresh"] = {
        "generated_at": datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "calibrated_rate_per_m": round(rate * 1e6, 4),
        "projected_days": proj_days,
        "projected_usd": proj_usd,
    }

    if dry:
        print(json.dumps({"proj_window": mtd_entry["window"], "proj_usd": proj_usd,
                          "rate_per_m": round(rate * 1e6, 4)}, indent=1))
        return
    bak = GA_PATH + ".bak-manual"
    if not os.path.exists(bak):
        # first projection: preserve the pristine manual pull
        import shutil
        shutil.copy2(GA_PATH, bak)
    with open(GA_PATH, "w") as f:
        json.dump(ga, f, indent=1)
    print(f"projected {mtd_entry['window']}: +${proj_usd} at "
          f"{round(rate * 1e6, 4)} $/M billed-equiv")


if __name__ == "__main__":
    main()
