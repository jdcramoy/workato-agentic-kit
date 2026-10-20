#!/usr/bin/env python3
"""roi-roll.py — join cost + velocity + shipped ledgers into the ROI roll.

Zero-LLM, stdlib only. Reads:
  knowledge/roi/data/shipped-raw.json     (manifest-keyed shipped tickets, Jira)
  knowledge/roi/data/velocity-raw.json    (all resolved BSYS tickets w/ builderClass)
  knowledge/roi/data/cost-weekly.json     (telemetry $ estimate per ISO week)
  knowledge/roi/data/gateway-actuals.json (authoritative gateway $ figures)

Writes:
  knowledge/roi/data/roi-monthly.json     (per-month roll for the analysis window)

Parameters:
  LABOR_DAY_RATE  $/engineer-day (default 600, override env ROI_LABOR_DAY_RATE)
  INFLECTION      ISO week the harness step lands (default 2026-W36; picked by data,
                  see framework.md — Josh velocity step-change)

Usage: python3 roi-roll.py [--out PATH]
"""
import json
import os
import sys
from collections import defaultdict
from datetime import date, datetime, timezone

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi/data")
LABOR_DAY_RATE = float(os.environ.get("ROI_LABOR_DAY_RATE", "600"))
INFLECTION_WEEK = "2026-W36"


def load(name):
    with open(os.path.join(ROI, name)) as f:
        return json.load(f)


def iso_week(iso_ts):
    d = datetime.fromisoformat(iso_ts[:10]).isocalendar()
    return f"{d[0]}-W{d[1]:02d}"


def month(iso_ts):
    return iso_ts[:7]


def pts(t):
    v = t.get("story_points") or t.get("storyPoints") or t.get("points") or 0
    try:
        return float(v)
    except (TypeError, ValueError):
        return 0.0


def main():
    shipped = load("shipped-raw.json")
    velocity = load("velocity-raw.json")

    # Josh's accountId comes from the tagged builderClass in velocity-raw.
    josh_ids = {r["assigneeAccountId"] for r in velocity if r.get("builderClass") == "josh" and r.get("assigneeAccountId")}

    # Per-month roll, 2026 only (points coverage + Josh's tenure + harness step).
    roll = {}
    for r in velocity:
        resolved = r.get("resolved") or r.get("resolutiondate") or ""
        if not resolved or not resolved.startswith("2026"):
            continue
        m = month(resolved)
        cell = roll.setdefault(m, {
            "josh": {"resolved": 0, "points": 0.0, "shipped_manifest": 0, "shipped_points": 0.0},
            "team_others": {"resolved": 0, "points": 0.0},
            "team_all": {"resolved": 0, "points": 0.0},
            "peers_named": defaultdict(lambda: {"resolved": 0, "points": 0.0}),
        })
        who = "josh" if r.get("assigneeAccountId") in josh_ids else "team_others"
        cell[who]["resolved"] += 1
        cell[who]["points"] += pts(r)
        cell["team_all"]["resolved"] += 1
        cell["team_all"]["points"] += pts(r)
        cls = r.get("builderClass")
        if cls in ("patricia-guevarra", "sam-cox", "benny-tan"):
            cell["peers_named"][cls]["resolved"] += 1
            cell["peers_named"][cls]["points"] += pts(r)

    # Manifest-keyed shipped subset (the strong definition of "shipped").
    for t in shipped:
        resolved = t.get("resolutiondate") or ""
        if not resolved.startswith("2026"):
            continue
        aid = t.get("assignee_accountId")
        m = month(resolved)
        if m not in roll:
            continue
        if aid in josh_ids:
            roll[m]["josh"]["shipped_manifest"] += 1
            roll[m]["josh"]["shipped_points"] += pts(t)
        # org-wide shipped counts kept in a separate accumulation
        roll[m].setdefault("org_shipped_manifest", 0)
        roll[m]["org_shipped_manifest"] += 1

    # Cost: multi-surface AI spend ledger — gateway + Claude + Codex, ALL Josh
    # personal (codex_josh confirmed Josh-scoped 2026-10-11). Telemetry weekly
    # estimate only fills months with no actuals.
    try:
        spend = load("ai-spend.json")
    except (FileNotFoundError, json.JSONDecodeError):
        spend = {"monthly": {}}
    cost_by_month = defaultdict(float)
    codex_by_month = defaultdict(float)
    for m, row in spend.get("monthly", {}).items():
        cost_by_month[m] += row.get("personal_total", 0.0)
        codex_by_month[m] += row.get("codex_josh", row.get("codex_org_wide", 0.0))
    if not any(cost_by_month.values()):  # fallback: telemetry estimate
        try:
            weekly_cost = load("cost-weekly.json").get("weekly", {})
            for wk, data in weekly_cost.items():
                cost_by_month[wk[:7]] += data.get("total_usd", 0)
        except (FileNotFoundError, json.JSONDecodeError):
            pass

    out = {
        "generated": datetime.now(timezone.utc).isoformat(),
        "labor_day_rate": LABOR_DAY_RATE,
        "inflection_week": INFLECTION_WEEK,
        "months": {},
    }
    for m in sorted(roll):
        c = cost_by_month.get(m, 0.0)
        j = roll[m]["josh"]
        labor_equiv = j["shipped_points"] * LABOR_DAY_RATE
        out["months"][m] = {
            "cost_gateway_usd": round(c, 2),  # personal AI spend (gateway + Claude)
            "codex_org_usd": round(codex_by_month.get(m, 0.0), 2),
            "josh": j,
            "team_others": roll[m]["team_others"],
            "team_all": roll[m]["team_all"],
            "peers_named": {k: dict(v) for k, v in roll[m].get("peers_named", {}).items()},
            "org_shipped_manifest": roll[m].get("org_shipped_manifest", 0),
            "labor_equiv_usd": round(labor_equiv, 2),
            "leverage": round(labor_equiv / c, 2) if c else None,
        }

    out_path = sys.argv[sys.argv.index("--out") + 1] if "--out" in sys.argv else os.path.join(ROI, "roi-monthly.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=2)
    # console summary
    print(f"{'month':8} {'cost':>8} {'josh res':>9} {'josh pts':>9} {'shipped':>8} {'ship pts':>9} {'labor$':>9} {'leverage':>9}")
    for m, d in out["months"].items():
        print(f"{m:8} {d['cost_gateway_usd']:>8.0f} {d['josh']['resolved']:>9} {d['josh']['points']:>9.1f} "
              f"{d['josh']['shipped_manifest']:>8} {d['josh']['shipped_points']:>9.1f} "
              f"{d['labor_equiv_usd']:>9.0f} {d['leverage'] if d['leverage'] else '-':>9}")


if __name__ == "__main__":
    main()
