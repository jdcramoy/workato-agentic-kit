#!/usr/bin/env python3
"""precursor-radar.py — z-score anomaly watch over Workato health sweeps.

Reads ~/.claude/knowledge/workato-health/sweeps/*.jsonl (format: one JSON object
per line with {"ts","id","server","verdict","name","flags","detail"}; some files
also carry selection manifests with no ts — those rows are skipped) and builds
four daily indicator series:

  job-failures       sum of per-recipe failure deltas, "fails=N (was M)" -> max(0, N-M)
  failed-recipes     rows with verdict == "new-failures"
  connection-errors  rows whose name/detail mention auth/connection error tokens
                     (401/403, connection, unauthorized, service unavailable, timeout, auth)
  restarts           recipe transitions not-running -> ok between consecutive sweeps

For each indicator: z-score of the latest day over a trailing-90-day window
(clamped to available history). z = (latest - mean) / population_std over the
window. Alarm when z > 2 and latest > 0.

Honesty rule: an alarm on < 14 distinct days of history is noise — it is shown
as PROVISIONAL and NOT submitted. The window target is 90 days; the current
sweep archive starts 2026-10-08, so with only a few days of history the
expected honest result is "insufficient data".

When an alarm fires, one prediction is appended to knowledge/predictions/
predictions.jsonl with agent "precursor-radar", using the documented
wt-health:sweeps resolver so brier-resolve.py can settle it later.

Exit codes: 0 normal (including insufficient data), 1 on error.
"""
import argparse, glob, json, os, re, subprocess, sys, time
from collections import defaultdict
from datetime import date, timedelta

SWEEPS = os.path.expanduser("~/.claude/knowledge/workato-health/sweeps")
LEDGER = os.path.expanduser("~/.claude/knowledge/predictions/predictions.jsonl")
WINDOW_DAYS = 90
MIN_DAYS_FOR_ALARM = 14
CONN_TOKENS = ("401", "403", "connection", "unauthorized",
               "service unavailable", "timeout", "auth")
INDICATORS = ("job-failures", "failed-recipes", "connection-errors", "restarts")
Z_THRESHOLD = 2.0


def load_series():
    series = {k: defaultdict(float) for k in INDICATORS}
    days_seen = set()
    skipped = 0
    files = sorted(glob.glob(os.path.join(SWEEPS, "*.jsonl")))
    if not files:
        return series, days_seen, skipped, 0
    last_verdict = {}
    for fn in files:
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(fn))
        try:
            lines = open(fn).read().splitlines()
        except OSError:
            continue
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                skipped += 1
                continue
            ts = str(r.get("ts") or "")
            d = ts[:10] if ts[:4].isdigit() else (m.group(1) if m else None)
            if not d:
                skipped += 1
                continue  # selection manifests and other non-sweep rows
            days_seen.add(d)
            verdict = r.get("verdict", "")
            detail = r.get("detail") or ""
            name = str(r.get("name") or "")
            rid = str(r.get("id"))

            mm = re.search(r"fails=(\d+) \(was (\d+)\)", detail)
            if mm:
                series["job-failures"][d] += max(0, int(mm.group(1)) - int(mm.group(2)))
            if verdict == "new-failures":
                series["failed-recipes"][d] += 1
            low = (detail + " " + name).lower()
            if any(t in low for t in CONN_TOKENS):
                series["connection-errors"][d] += 1
            prev = last_verdict.get(rid)
            if prev == "not-running" and verdict == "ok":
                series["restarts"][d] += 1
            last_verdict[rid] = verdict
    return series, days_seen, skipped, len(files)


def zscore(values, latest):
    n = len(values)
    mean = sum(values) / n
    var = sum((v - mean) ** 2 for v in values) / n
    std = var ** 0.5
    if std == 0:
        return 0.0, mean, std
    return (latest - mean) / std, mean, std


def append_prediction(claim, confidence, resolve_by, resolver_query):
    os.makedirs(os.path.dirname(LEDGER), exist_ok=True)
    existing = []
    if os.path.exists(LEDGER):
        with open(LEDGER) as f:
            existing = [json.loads(l) for l in f if l.strip()]
    hi = 0
    for r in existing:
        m = re.match(r"prd-(\d+)$", str(r.get("id", "")))
        if m:
            hi = max(hi, int(m.group(1)))
    row = {"id": f"prd-{hi + 1:03d}", "ts": time.strftime("%Y-%m-%dT%H:%M:%S%z"),
           "agent": "precursor-radar", "claim": claim, "confidence": confidence,
           "resolve_by": resolve_by, "resolver_query": resolver_query,
           "consequential": False, "status": "open"}
    with open(LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")
    return row["id"]


def main():
    ap = argparse.ArgumentParser(description="Precursor radar: z-score alarms over "
                                 "Workato health sweep data (z > 2 fires a precursor "
                                 "alarm; sufficient history only).")
    ap.add_argument("--window", type=int, default=WINDOW_DAYS,
                    help=f"trailing window in days (default {WINDOW_DAYS})")
    ap.add_argument("--min-days", type=int, default=MIN_DAYS_FOR_ALARM,
                    help=f"minimum distinct days before an alarm is actionable "
                         f"(default {MIN_DAYS_FOR_ALARM})")
    ap.add_argument("--z", type=float, default=Z_THRESHOLD, help="alarm threshold")
    ap.add_argument("--no-submit", action="store_true",
                    help="print alarms without appending predictions")
    args = ap.parse_args()

    series, days_seen, skipped, nfiles = load_series()
    all_days = sorted(days_seen)
    if not all_days:
        print("insufficient data: no sweep rows found under workato-health/sweeps/")
        print("needed: nightly workato-health.py sweeps (JSONL with ts/verdict/detail)")
        return 0

    latest_day = all_days[-1]
    cutoff = date.fromisoformat(latest_day) - timedelta(days=args.window - 1)
    print(f"precursor-radar — window {args.window}d ending {latest_day}; "
          f"{nfiles} sweep files, {len(all_days)} distinct days of history, "
          f"{skipped} non-sweep rows skipped")

    insufficient = len(all_days) < args.min_days
    if insufficient:
        print(f"INSUFFICIENT HISTORY: {len(all_days)} days available, "
              f"{args.min_days} required before an alarm is actionable "
              f"(window target {args.window}d). z-scores below are computed but "
              "provisional; no predictions will be submitted from them.")

    alarms = []
    for ind in INDICATORS:
        wdays = [d for d in all_days if date.fromisoformat(d) >= cutoff]
        vals = [series[ind].get(d, 0.0) for d in wdays]  # zero-fill empty days
        latest = vals[-1] if vals else 0.0
        if len(vals) < 2:
            print(f"\n{ind}: no series (need >=2 days with data in window)")
            continue
        z, mean, std = zscore(vals, latest)
        flag = ""
        if z > args.z and latest > 0:
            flag = "PROVISIONAL ALARM" if insufficient else "ALARM"
            if not insufficient:
                alarms.append((ind, latest, z, mean))
            else:
                print(f"\n{ind}: latest={latest:g} mean={mean:.2f} std={std:.2f} z={z:+.2f} "
                      f"— {flag} suppressed (insufficient history)")
                continue
        print(f"\n{ind}: latest={latest:g} mean={mean:.2f} std={std:.2f} z={z:+.2f} {flag}".rstrip())

    for ind, latest, z, mean in alarms:
        due = (date.fromisoformat(latest_day) + timedelta(days=7)).isoformat()
        claim = (f"precursor {ind} spiked: latest day {latest:g} vs window mean "
                 f"{mean:.2f} (z={z:.2f}) on {latest_day} — elevated levels persist "
                 f"through {due}")
        rq = f"wt-health:sweeps:indicator={ind}:expect=above-baseline"
        if args.no_submit:
            print(f"\nwould submit (—no-submit set): {claim}")
        else:
            pid = append_prediction(claim, 0.6, due, rq)
            print(f"\nalarm submitted as {pid} (conf 0.6, resolve_by {due}, resolver {rq})")

    if not alarms and not insufficient:
        print("\nno indicator above z=2 — no precursor alarms")
    print("\ndata note: connection-error signal in sweeps is sparse; the sweeps "
          "only carry verdict/detail per watched recipe. A true connection-error "
          "count needs the connection collector to write per-day auth-failure "
          "rows into workato-health/ (currently only state.json failed_counts "
          "and sweep verdicts exist).")
    return 0


if __name__ == "__main__":
    sys.exit(main() or 0)
