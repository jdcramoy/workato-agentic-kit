#!/usr/bin/env python3
"""spend-ingest.py — build the multi-surface AI spend ledger (data/ai-spend.json).

Surfaces:
  gateway   : Josh's AI gateway My-spend ACTUALS (chargeback view; months from
              gateway-actuals.json — ruling 2026-10-14 de-authorized est_cost_usd,
              which ran ~2.7-3.3x hot)
  claude    : Josh's Anthropic console spend by month (from his console
              screenshot, 2026-10-11; personal spend)
  codex     : Josh's personal ChatGPT/Codex spend (the workato-enterprise
              workspace export IS Josh-scoped per Josh 2026-10-11) converted
              at CODEX_CREDIT_USD (default 0.04 — CONFIRMED against OpenAI's
              console Est. $9,577.13 for 239,428 credits; also derivable
              from the rate card). Env overrides: ROI_CODEX_CREDIT_USD.

Writes data/ai-spend.json with per-month per-surface rows; personal_total =
gateway + claude + codex (all three are Josh's).
"""
import csv
import json
import os
from collections import defaultdict

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi")
DL = os.path.join(HOME, "Downloads")
CODEX_CREDIT_USD = float(os.environ.get("ROI_CODEX_CREDIT_USD", "0.04"))

CODEX_CSVS = [
    "analytics-codex-credits-used_workspace-workato-enterprise_by-model_2026-06-01-to-2026-10-12.csv",
]

# Anthropic console, Joshua Cramoy account, from his screenshot 2026-10-11
CLAUDE_MONTHLY_USD = {
    "2026-01": 0.00, "2026-02": 9.71, "2026-03": 73.92, "2026-04": 0.00,
    "2026-05": 56.74, "2026-06": 177.35, "2026-07": 1796.48,
    "2026-08": 310.71, "2026-09": 54.83, "2026-10": 92.81,  # Oct = 1st-10th
}


def main():
    # gateway: reuse derived monthly actuals
    with open(os.path.join(ROI, "data", "gateway-actuals.json")) as f:
        ga = json.load(f)
    d = ga["derived_monthly"]
    gateway = {}
    if d["september_2026"].get("est_cost_usd") is not None:
        gateway["2026-09"] = d["september_2026"]["est_cost_usd"]
    else:
        print("note: Sep-2026 gateway actuals unknown (My-spend window not widened "
              "before Oct) — month excluded from gateway totals")
    gateway["2026-10"] = d["october_2026_partial_14d"]["usd"]

    # codex: sum 'All' credits per month from the workspace CSV
    codex_credits = defaultdict(float)
    rows_read = 0
    for name in CODEX_CSVS:
        p = os.path.join(DL, name)
        with open(p) as f:
            for r in csv.DictReader(f):
                rows_read += 1
                codex_credits[r["Start Time"][:7]] += float(r["All"] or 0)
    codex = {m: round(c * CODEX_CREDIT_USD, 2) for m, c in sorted(codex_credits.items())}

    months = sorted(set(gateway) | set(CLAUDE_MONTHLY_USD) | set(codex))
    out = {
        "generated": "2026-10-11",
        "codex_credit_usd": CODEX_CREDIT_USD,
        "codex_credit_rate_note": "$0.04/credit CONFIRMED against OpenAI's own console dollar estimate (239,428 credits -> Est. $9,577.13, screenshot 2026-10-11); also derivable from the rate card (GPT-5.4: 62.5 credits per $2.50 API input).",
        "surfaces": {},
        "monthly": {},
    }
    for m in months:
        row = {
            "gateway_josh": round(gateway.get(m, 0.0), 2),
            "claude_josh": CLAUDE_MONTHLY_USD.get(m, 0.0),
            "codex_josh": round(codex.get(m, 0.0), 2),
        }
        row["personal_total"] = round(row["gateway_josh"] + row["claude_josh"] + row["codex_josh"], 2)
        out["monthly"][m] = row
        out["surfaces"].setdefault(m, {})
    out["totals"] = {
        "gateway_josh": round(sum(r["gateway_josh"] for r in out["monthly"].values()), 2),
        "claude_josh": round(sum(r["claude_josh"] for r in out["monthly"].values()), 2),
        "codex_josh": round(sum(r["codex_josh"] for r in out["monthly"].values()), 2),
        "personal_total": round(sum(r["personal_total"] for r in out["monthly"].values()), 2),
        "codex_csv_rows_read": rows_read,
        "codex_scope": "Josh-personal (Josh confirmation 2026-10-11)",
    }
    with open(os.path.join(ROI, "data", "ai-spend.json"), "w") as f:
        json.dump(out, f, indent=2)
    print(json.dumps(out["monthly"], indent=2))
    print(json.dumps(out["totals"], indent=2))


if __name__ == "__main__":
    main()
