#!/usr/bin/env python3
"""counterfactual.py — "what would it cost to HIRE to match this pace?"

Zero-LLM, stdlib only. Reads roi/data/velocity-raw.json (BSYS resolution
history) and computes:

  - Josh's burst pace (points/month since his AI-era inflection month)
  - the conventional-builder pace from the SAME data (75th percentile of
    builders' monthly points, 2025+ window where points coverage is good;
    builders with >=6 active months). Cross-checks against the theoretical
    1pt=1day ceiling (~21 working days/month).
  - devs-equivalent = josh pace / conventional pace  (ROUNDED UP, and the
    p75 basis makes this conservative: faster-than-p75 builders would need
    MORE hires)
  - annual fully-loaded cost of those hires (LOADED_DEV_COST, default $230k)

Writes roi/data/counterfactual.json. Env overrides: ROI_LOADED_DEV_COST.
"""
import json
import math
import os
import statistics
from collections import defaultdict

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi")
LOADED_DEV_COST = float(os.environ.get("ROI_LOADED_DEV_COST", "230000"))


def main():
    with open(os.path.join(ROI, "data", "velocity-raw.json")) as f:
        v = json.load(f)

    # Josh's accountId from the tagged class
    josh_ids = {r["assigneeAccountId"] for r in v if r.get("builderClass") == "josh"}

    # Josh burst: resolved points since the inflection month
    by_month_josh = defaultdict(float)
    for r in v:
        if r.get("assigneeAccountId") in josh_ids:
            res = r.get("resolved") or ""
            if res >= "2026-09":
                by_month_josh[res[:7]] += r.get("storyPoints") or 0
    months_josh = sorted(by_month_josh)
    # partial months prorated by working-day share: count days spanned
    from datetime import date
    first = date(2026, 9, 1)
    last_res = max(
        (r.get("resolved") for r in v
         if r.get("assigneeAccountId") in josh_ids and (r.get("resolved") or "") >= "2026-09"),
        default="2026-10-11")
    y, m, d = (int(x) for x in last_res[:10].split("-"))
    last = date(y, m, d)
    span_months = (last - first).days / 30.44
    josh_total = sum(by_month_josh.values())
    josh_pm = josh_total / span_months if span_months else 0

    # conventional pace: p75 of builder monthly points, 2025+, >=6 active months
    bym = defaultdict(lambda: defaultdict(float))
    for r in v:
        res = r.get("resolved") or ""
        if not res.startswith("2025"):
            continue
        aid = r.get("assigneeAccountId")
        if not aid:
            continue
        bym[aid][res[:7]] += r.get("storyPoints") or 0
    rates = [sum(mm.values()) / len(mm) for mm in bym.values() if len(mm) >= 6]
    p75 = statistics.quantiles(rates, n=4)[2] if len(rates) >= 4 else statistics.mean(rates)

    devs = math.ceil(josh_pm / p75) if p75 else None
    out = {
        "generated": last.isoformat(),
        "josh_burst": {
            "window": f"2026-09-01 to {last.isoformat()}",
            "total_points": josh_total,
            "span_months": round(span_months, 2),
            "points_per_month": round(josh_pm, 1),
        },
        "conventional_builder": {
            "basis": "p75 of monthly points, 2025+ window, builders with >=6 active months",
            "builders_counted": len(rates),
            "p75_points_per_month": round(p75, 1),
            "mean_points_per_month": round(statistics.mean(rates), 1),
            "theoretical_ceiling_pts_per_month": 21,
        },
        "loaded_dev_cost_usd": LOADED_DEV_COST,
        "devs_equivalent": devs,
        "annual_cost_of_hires_usd": round(devs * LOADED_DEV_COST) if devs else None,
    }
    with open(os.path.join(ROI, "data", "counterfactual.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
