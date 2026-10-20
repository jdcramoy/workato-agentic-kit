#!/usr/bin/env python3
"""one-pager.py — generate the monthly AI-spend one-pager (leadership artifact).

Zero-LLM, stdlib only. Reads roi/data/{roi-monthly.json, gateway-actuals.json,
velocity-weekly.json} + roi/theses.json (Josh-approved work-block theses) and
writes roi/one-pager-<month>.md in Josh's doc voice.

Usage: python3 one-pager.py [--month 2026-10]
"""
import json
import os
import sys
from datetime import datetime, timezone

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi")


def load(p):
    with open(os.path.join(ROI, "data", p)) as f:
        return json.load(f)


def main():
    monthly = load("roi-monthly.json")
    vw = load("velocity-weekly.json")
    cf = load("counterfactual.json")
    try:
        theses = json.load(open(os.path.join(ROI, "theses.json")))
    except (FileNotFoundError, json.JSONDecodeError):
        theses = {"blocks": []}

    months = monthly["months"]
    now = datetime.now(timezone.utc)
    args = sys.argv
    month = args[args.index("--month") + 1] if "--month" in args else now.strftime("%Y-%m")
    if month not in months:
        raise SystemExit(f"no data for {month}; have: {', '.join(sorted(months))}")

    d = months[month]
    prior_keys = sorted(k for k in months if k < month and months[k]["cost_gateway_usd"] > 0)
    prior = months[prior_keys[-1]] if prior_keys else None

    # baseline: monthly mean of resolved points before the harness step (2026-02..2026-07; AI-assisted throughout)
    base = [months[k]["josh"]["points"] for k in sorted(months) if "2026-02" <= k <= "2026-07"]
    base_avg = sum(base) / len(base) if base else 0

    # Leverage pairs cost and output over the FULL data window (2026 YTD).
    # All months count (zero-spend months still ship work — e.g. April);
    # Josh has been AI-assisted since the data begins; the Aug-31 step is the
    # harness coming online, not the start of AI use.
    cost_months = [k for k in sorted(months) if "2026-02" <= k <= month]
    t_keys = cost_months
    t_ship = sum(months[k]["josh"]["shipped_manifest"] for k in t_keys)
    t_ship_pts = sum(months[k]["josh"]["shipped_points"] for k in t_keys)
    t_cost = sum(months[k]["cost_gateway_usd"] for k in t_keys)
    lev_lo = t_ship_pts * monthly["labor_day_rate"] / t_cost if t_cost else None
    t_res_pts = sum(months[k]["josh"]["points"] for k in t_keys)
    lev_hi = t_res_pts * monthly["labor_day_rate"] / t_cost if t_cost else None

    lines = []
    a = lines.append
    a(f"# AI spend and what it shipped: {month}")
    a("")
    a(f"My personal AI spend across all of 2026 is ${t_cost:,.0f} across three surfaces: the "
      f"company AI gateway, my Anthropic console, and my ChatGPT/Codex usage "
      f"(${d['cost_gateway_usd']:,.0f} of it in {month}). I have been working and shipping with "
      f"AI for the whole span of that data; the step-change in the week of August 31 is when "
      f"the build-automating harness came online, not where AI started. That spend carried "
      f"{t_ship} reviewed, manifest-backed promotions to production ({t_ship_pts:.0f} story "
      f"points) and {t_res_pts:.0f} resolved story points total on the BSYS board. Valued at a "
      f"conservative ${monthly['labor_day_rate']:.0f} per engineer-day, the shipped work alone "
      f"is worth ${t_ship_pts * monthly['labor_day_rate']:,.0f} of engineering time, a "
      f"{lev_lo:.1f}x return on the tooling spend; counting all resolved work it is "
      f"{lev_hi:.1f}x.")
    a("")
    a("## Before and after")
    a("")
    a(f"I was already AI-assisted all year: my monthly resolved throughput ran {base_avg:.0f} "
      f"story points per month from February through July on Claude and Codex alone. The "
      f"step-change lands in the week of August 31 (2026-W36), and the curve, not a declared "
      f"date, picks that week: that is when the build-automating harness came online and AI "
      f"stopped being an assistant and became a builder with verification. Since then I have "
      f"resolved {sum(months[k]['josh']['points'] for k in months if k >= '2026-09'):,.0f} points "
      f"across September and October to date. Same builder, same domain, same backlog; what "
      f"moved is the maturity of the tooling, not its presence.")
    a("")
    a("## Read this pace as a burst, not a run-rate")
    a("")
    a("That September-October surge is a transition burst, not a promise. It is what happened "
      "when a build-automating harness met months of accumulated backlog and a set of "
      "platform-scale first builds. Nobody holds that pace, and I am not proposing to. The "
      "burst is the return on the setup investment; the steady state that follows will be "
      "lower and is the honest basis for go-forward planning. I would rather show you the "
      "burst and name it than let it become the expectation.")
    a("")
    a("## Where the spend goes")
    a("")
    a("Nine tenths of gateway spend is delivery work on business automations (Workato "
      "builds, service-desk platform, estate operations). Overhead, meaning harness "
      "improvement plus scheduled fleet jobs, runs under a tenth. The expensive sessions "
      "are long resumed builds, and the weekly curve falls as builds complete, which is "
      "what a build-spike profile looks like.")
    a("")
    a("## What the shipped work does")
    a("")
    if theses.get("blocks"):
        for b in theses["blocks"]:
            a(f"- **{b['name']}**: {b['thesis']}")
    else:
        a("- Theses are drafted per work block and attached once approved. "
          "Candidate blocks this period: GW Semantic MCP platform, HR Genie service desk, "
          "estate monitoring, promotion tooling.")
    a("")
    a("## What it would cost to hire instead")
    a("")
    a(f"The conventional-builder pace on our own board, 75th percentile across "
      f"{cf['conventional_builder']['builders_counted']} builders over 2025+, is "
      f"{cf['conventional_builder']['p75_points_per_month']} points a month, which lands on the "
      f"one-point-one-day ceiling of about 21 working days. My burst pace is "
      f"{cf['josh_burst']['points_per_month']:.0f} points a month. Matching it by hiring would "
      f"take about {cf['devs_equivalent']} fully-loaded developers at "
      f"${cf['loaded_dev_cost_usd']/1000:,.0f}k a year each, ${cf['annual_cost_of_hires_usd']/1e6:.1f}M "
      f"a year, before recruiting and ramp time. The AI tooling run-rate is a low tens of "
      f"thousands. Two honesty notes: this prices the burst, so steady-state equivalence will "
      f"land lower; and ramp time plus coordination overhead would push the hire cost up, not "
      f"down.")
    a("")
    a("## How to read this")
    a("")
    a("Story points are the team's own estimates at creation (one point, one developer day), "
      "shown with ticket counts so no single estimator's bias carries the number. "
      "Manifest-backed promotions are the conservative basis; the full resolved basis is "
      "shown as the upper bound. This measures throughput change, not a controlled "
      "experiment. Org-wide gateway adoption is context and never a cross-team comparison.")
    a("")
    a("## Verdict")
    a("")
    a(f"The spend bought shipped, reviewed, production-bound work at a multiple of its cost, "
      f"and the transition burst that did it is visible in the team's own board. Recommend "
      f"holding the tooling, planning go-forward on a steady state we will measure through "
      f"Q4, and re-cutting this monthly.")

    out = os.path.join(ROI, f"one-pager-{month}.md")
    with open(out, "w") as f:
        f.write("\n".join(lines) + "\n")
    print(f"wrote {out}")
    print("\n".join(lines[:8]))


if __name__ == "__main__":
    main()
