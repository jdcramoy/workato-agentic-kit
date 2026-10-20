#!/usr/bin/env python3
"""render-board.py — generate roi/board.html (AI-spend ROI dashboard).

Zero-LLM, stdlib only. Reads roi/data/{roi-monthly.json, cost-weekly.json,
velocity-weekly.json, gateway-actuals.json} and writes roi/board.html.
Style mirrors Workato's public site: light surfaces, deep teal-navy ink,
turquoise highlight (#67eadd), teal (#009489) / pink (#d6407f) series —
each validated single-slot on white (both charts are single-series).
Re-run after any data refresh.
"""
import json
import os
from datetime import datetime

HOME = os.path.expanduser("~")
ROI = os.path.join(HOME, ".claude/knowledge/roi")


def week_monday(wk):
    """ISO week '2026-W36' -> Monday date label like 'Aug 31'."""
    y, w = wk.split("-W")
    d = datetime.fromisocalendar(int(y), int(w), 1)
    return d.strftime("%b %-d")

def load(p):
    with open(os.path.join(ROI, "data", p)) as f:
        return json.load(f)

monthly = load("roi-monthly.json")
cost_weekly = load("cost-weekly.json").get("weekly", {})
vw = load("velocity-weekly.json")
cf = load("counterfactual.json")

WEEKS = sorted(cost_weekly)
cost_series = [{"week": w, "usd": round(cost_weekly[w]["total_usd"], 0),
                "sessions": cost_weekly[w]["sessions"]} for w in WEEKS]

josh_weekly = []
for wk in sorted(vw["weekly"]):
    if not wk.startswith("2026"):
        continue
    d = vw["weekly"][wk]["josh"]
    josh_weekly.append({"week": wk, "points": d["points"], "tickets": d["count"]})

INFLECTION = monthly.get("inflection_week", "2026-W36")
RATE = monthly.get("labor_day_rate", 600)

sept_oct = {m: d for m, d in monthly["months"].items() if m >= "2026-02"}
sum_cost = sum(d["cost_gateway_usd"] for d in sept_oct.values())
sum_res = sum(d["josh"]["resolved"] for d in sept_oct.values())
sum_pts = sum(d["josh"]["points"] for d in sept_oct.values())
sum_ship = sum(d["josh"]["shipped_manifest"] for d in sept_oct.values())
sum_ship_pts = sum(d["josh"]["shipped_points"] for d in sept_oct.values())
labor = sum_ship_pts * RATE
lev = round(labor / sum_cost, 1) if sum_cost else None
labor_hi = sum_pts * RATE
lev_hi = round(labor_hi / sum_cost, 1) if sum_cost else None

rows = []
for m, d in monthly["months"].items():
    if m < "2026-02":
        continue
    rows.append((m, d))

has_codex = any(d.get("codex_org_usd") for _, d in rows)
span_yr = 253 / 365  # Feb 1 -> Oct 11, 2026 in years (253 days)

def esc(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;")

def bars(data, val_key, cls, fmt):
    mx = max((d[val_key] for d in data), default=0) or 1
    out = []
    for d in data:
        h = max(3, round(d[val_key] / mx * 150))
        out.append(
            f'<div class="bar {cls}" style="height:{h}px" data-tip="{esc(fmt(d))}"></div>')
    return "\n".join(out)

josh_bars = bars(josh_weekly, "points", "s1",
                 lambda d: f"Week of {week_monday(d['week'])}: {d['points']:.0f} pts / {d['tickets']} tickets")
cost_bars = bars(cost_series, "usd", "s2",
                 lambda d: f"Week of {week_monday(d['week'])}: ~${d['usd']:.0f} ({d['sessions']} sessions)")

def axis(data, every):
    return "".join(
        f"<span>{week_monday(d['week']) if i % every == 0 else ''}</span>"
        for i, d in enumerate(data))

table_rows = []
for m, d in rows:
    lv = f"{d['leverage']:.1f}x" if d["leverage"] else "&mdash;"
    table_rows.append(
        f"<tr><td>{m}</td><td>${d['cost_gateway_usd']:,.0f}</td>"
        f"<td>${d.get('codex_org_usd', 0):,.0f}</td>"
        f"<td>{d['josh']['resolved']}</td><td>{d['josh']['points']:.0f}</td>"
        f"<td>{d['josh']['shipped_manifest']}</td><td>{d['josh']['shipped_points']:.0f}</td>"
        f"<td>${d['labor_equiv_usd']:,.0f}</td><td>{lv}</td></tr>")

per = sorted(vw["perAssignee_min10"], key=lambda r: -r["resolvedTickets"])[:10]
per_rows = "\n".join(
    f"<tr><td>{esc(r['displayName'])}</td><td>{r['resolvedTickets']:,}</td>"
    f"<td>{r['totalPoints']:,.0f}</td></tr>" for r in per)

team_recent = []
for wk in sorted(vw["weekly"])[-8:]:
    d = vw["weekly"][wk]
    mon = week_monday(wk)
    # date range label: Monday -> Sunday
    from datetime import datetime as _dt, timedelta as _td
    sun = (_dt.strptime(f"{mon} {wk[:4]}", "%b %d %Y") + _td(days=6)).strftime("%b %-d")
    team_recent.append(
        f"<tr><td>{mon} &ndash; {sun}</td><td>{d['josh']['count']}</td><td>{d['josh']['points']:.0f}</td>"
        f"<td>{d['all']['count']}</td><td>{d['all']['points']:.0f}</td></tr>")

# index of the inflection week inside the josh series, for the marker line
inf_idx = next((i for i, d in enumerate(josh_weekly) if d["week"] == INFLECTION), None)
inf_left = f"{(inf_idx + 0.5) / len(josh_weekly) * 100:.2f}%" if inf_idx is not None else None

html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta http-equiv="cache-control" content="no-cache, no-store, must-revalidate">
<meta http-equiv="pragma" content="no-cache">
<title>AI spend &rarr; shipped Workato work</title>
<style>
  :root {{
    --page: #ffffff; --plane: #f4f8f8; --card: #ffffff;
    --ink: #0e2e39; --ink-2: #45616b; --muted: #7a9299;
    --hair: #dbe7e9; --border: rgba(14,46,57,0.08);
    --teal: #009489; --pink: #d6407f; --turq: #67eadd;
  }}
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: var(--page); color: var(--ink);
    font-family: -apple-system, "Segoe UI", Inter, system-ui, sans-serif; }}
  .viz-root {{ max-width: 1100px; margin: 0 auto; padding: 0 24px 56px; }}
  .masthead {{ border-bottom: 3px solid var(--turq); padding: 30px 0 14px;
    margin-bottom: 24px; }}
  h1 {{ font-size: 26px; letter-spacing: -0.01em; margin: 0 0 6px; }}
  .sub {{ color: var(--ink-2); font-size: 13px; line-height: 1.5; }}
  .tiles {{ display: grid; grid-template-columns: repeat(auto-fit, minmax(180px, 1fr));
    gap: 14px; margin-bottom: 24px; }}
  .tile {{ background: var(--plane); border: 1px solid var(--border);
    border-radius: 14px; padding: 16px 18px; }}
  .tile .k {{ font-size: 12.5px; color: var(--ink-2); line-height: 1.4; }}
  .tile .v {{ font-size: 28px; font-weight: 700; margin-top: 4px; letter-spacing: -0.01em; }}
  .tile .n {{ font-size: 11.5px; color: var(--muted); margin-top: 2px; }}
  .panel {{ background: var(--card); border: 1px solid var(--border);
    border-radius: 14px; padding: 20px 22px; margin-bottom: 20px;
    box-shadow: 0 1px 3px rgba(14,46,57,0.05); }}
  .panel h2 {{ font-size: 16px; margin: 0 0 4px; }}
  .panel .desc {{ font-size: 13px; color: var(--ink-2); margin-bottom: 14px; line-height: 1.5; }}
  .chart {{ display: flex; align-items: flex-end; gap: 4px; height: 160px;
    position: relative; }}
  .bar {{ flex: 1; border-radius: 4px 4px 0 0; min-height: 3px; }}
  .bar.s1 {{ background: var(--teal); }}
  .bar.s2 {{ background: var(--pink); }}
  .bar:hover {{ opacity: .75; }}
  .marker {{ position: absolute; top: 0; bottom: 0; border-left: 2px dashed #17b3a6; }}
  .marker span {{ position: absolute; top: -2px; left: 6px; background: var(--turq);
    color: #0e2e39; font-size: 10.5px; font-weight: 600; padding: 1px 7px;
    border-radius: 999px; white-space: nowrap; }}
  .axis {{ display: flex; gap: 4px; font-size: 11px; color: var(--muted); margin-top: 6px;
    font-variant-numeric: tabular-nums; }}
  .axis span {{ flex: 1; text-align: left; }}
  table {{ border-collapse: collapse; width: 100%; font-size: 13.5px; }}
  th, td {{ text-align: right; padding: 7px 10px; border-bottom: 1px solid var(--hair);
    font-variant-numeric: tabular-nums; }}
  th:first-child, td:first-child {{ text-align: left; }}
  th {{ color: var(--ink-2); font-weight: 600; font-size: 12.5px; }}
  tr:hover td {{ background: var(--plane); }}
  .note {{ font-size: 12.5px; color: var(--ink-2); line-height: 1.55; }}
  .cols {{ display: grid; grid-template-columns: 1fr 1fr; gap: 20px; }}
  @media (max-width: 840px) {{ .cols {{ grid-template-columns: 1fr; }} }}
  .tip {{ position: fixed; pointer-events: none; background: var(--ink); color: #fff;
    font-size: 12.5px; padding: 5px 10px; border-radius: 6px; opacity: 0;
    transition: opacity .1s; z-index: 9; }}
</style>
</head>
<body>
<div class="viz-root">
  <div class="masthead">
    <h1>AI spend &rarr; shipped Workato work</h1>
    <div class="sub">AI spend actuals, all surfaces Joshua's own (gateway + Claude
console + Codex) + Jira BSYS &middot; generated {monthly['generated'][:10]} &middot; conversion:
1 pt = 1 engineer-day &asymp; ${RATE:.0f} loaded cost (a price tag on work, not our spend) &middot;
      inflection picked by the data: <strong>week of {week_monday(INFLECTION)}, 2026</strong></div>
  </div>

  <div class="tiles">
    <div class="tile"><div class="k">AI spend (you), 2026 YTD</div>
      <div class="v">${sum_cost:,.0f}</div><div class="n">gateway + Claude + Codex, actuals since Feb</div></div>
    <div class="tile"><div class="k">BSYS tickets resolved (you)</div>
      <div class="v">{sum_res}</div><div class="n">{sum_pts:.0f} story points</div></div>
    <div class="tile"><div class="k">Manifest-shipped (you)</div>
      <div class="v">{sum_ship}</div><div class="n">{sum_ship_pts:.0f} points, review+manifest</div></div>
    <div class="tile"><div class="k">Labor-equivalent (shipped, conservative)</div>
      <div class="v">${labor:,.0f}</div><div class="n">shipped pts &times; ${RATE:.0f} loaded cost/engineer-day</div></div>
    <div class="tile"><div class="k">Leverage (conservative &rarr; full)</div>
      <div class="v" style="white-space:nowrap">{lev if lev else '&mdash;'}x&rarr;{lev_hi if lev_hi else '&mdash;'}x</div>
      <div class="n">labor-equiv &divide; gateway spend</div></div>
  </div>

  <div class="panel">
    <h2>Your weekly throughput (story points resolved, 2026)</h2>
    <div class="desc">AI-assisted throughout (Claude spend from Feb, Codex from Jul).
The step-change in the week of {week_monday(INFLECTION)}, 2026, picked from the curve, is when the
build-automating harness came online. The Sep&ndash;Oct surge is a <strong>transition
burst</strong> (backlog burn-down + platform first-builds), not a sustainable run-rate
&mdash; steady state lands lower and gets measured in Q4.</div>
    <div class="chart">{josh_bars}
      {f'<div class="marker" style="left:{inf_left}"><span>{week_monday(INFLECTION)} (harness live)</span></div>' if inf_left else ''}</div>
    <div class="axis">{axis(josh_weekly, 6)}</div>
  </div>

  <div class="cols">
    <div class="panel">
      <h2>Gateway spend by week (telemetry estimate)</h2>
      <div class="desc">~$0.325/M billed-equiv, calibrated to gateway My-spend
actuals ($1,467 Oct 1-14). Authoritative months are in the table below.</div>
      <div class="chart">{cost_bars}</div>
      <div class="axis">{axis(cost_series, 2)}</div>
    </div>
    <div class="panel">
      <h2>BSYS context, last 8 weeks (two-tier)</h2>
      <div class="desc">All BSYS resolved activity (dozens of closers/week,
mostly small tickets at 0&ndash;2 pts). Leadership artifact
shows this aggregate only; named rows are internal.</div>
      <table>
        <tr><th>week (dates)</th><th>you (tickets)</th><th>you (pts)</th><th>BSYS (tickets)</th><th>BSYS (pts)</th></tr>
        {''.join(team_recent)}
      </table>
    </div>
  </div>

  <div class="panel">
    <h2>Monthly roll &mdash; cost in, work out</h2>
    <table>
      <tr><th>month</th><th>spend (you) $</th><th>of which codex $</th><th>you resolved</th><th>you pts</th>
          <th>manifest shipped</th><th>shipped pts</th><th>labor-equiv $</th><th>leverage</th></tr>
      {''.join(table_rows)}
    </table>
    <p class="note">Manifest shipping is batch-lumpy (promotions queue in review): read
leverage on a trailing window, not a single part-month. Feb&ndash;Jul carried only
Claude-console spend; the gateway era (and the AI inflection) starts the week of
Aug 31. All three spend surfaces are Joshua's own (Codex confirmed Josh-scoped
2026-10-11; $0.04/credit confirmed against OpenAI's console estimate).</p>
  </div>

  <div class="panel">
    <h2>Counterfactual: hire to match this pace</h2>
    <div class="desc">Conventional-builder pace is the 75th percentile of monthly points
across {cf['conventional_builder']['builders_counted']} BSYS builders (2025+ window), {cf['conventional_builder']['p75_points_per_month']} pts/month
&mdash; which lands on the theoretical 1pt=1day ceiling of ~21. Joshua&rsquo;s burst pace:
{cf['josh_burst']['points_per_month']} pts/month.</div>
    <div class="tiles" style="margin-bottom:8px">
      <div class="tile"><div class="k">Conventional devs to match</div>
        <div class="v">{cf['devs_equivalent']}</div>
        <div class="n">at p75 pace, rounded up</div></div>
      <div class="tile"><div class="k">Their fully-loaded annual cost</div>
        <div class="v">${cf['annual_cost_of_hires_usd']:,.0f}</div>
        <div class="n">${cf['loaded_dev_cost_usd']:,.0f}/dev/yr, recruiting+ramp excluded</div></div>
      <div class="tile"><div class="k">AI tooling run-rate</div>
        <div class="v">~${sum_cost / span_yr / 1000:,.0f}k/yr</div>
        <div class="n">gateway + Claude + Codex (you), annualized from actuals</div></div>
      <div class="tile"><div class="k">Basis caveat</div>
        <div class="v" style="font-size:16px;line-height:1.3">burst-priced</div>
        <div class="n">steady-state equivalence lands lower; ramp and coordination overhead would push hire cost UP</div></div>
    </div>
  </div>

  <div class="cols">
    <div class="panel">
      <h2>Work-block value theses</h2>
      <div class="desc">One thesis per epic, drafted from ticket content +
manifests &mdash; each Josh-approved before it reaches a leadership artifact.</div>
      <p class="note">Pending: first theses land with the one-pager. Candidate
blocks from the shipped ledger: GW Semantic MCP platform, HR Genie service
desk, estate monitoring/observability, PTO/Workday self-service, promotion
tooling.</p>
    </div>
    <div class="panel">
      <h2>Builder roster (internal only)</h2>
      <div class="desc">Full BSYS resolution history, all builders with &ge;10 resolved
tickets. NOT for the leadership artifact (two-tier rule).</div>
      <table>
        <tr><th>builder</th><th>resolved</th><th>points</th></tr>
        {per_rows}
      </table>
    </div>
  </div>

  <div class="panel">
    <h2>Honest weaknesses</h2>
    <p class="note">Points are self-estimated (56% of pre-2025 tickets lack them;
2026 coverage is good). Manifest-defined shipped undercounts ops/triage work
&mdash; both bases are shown. Throughput change is correlation, not causality proof.
Gateway $ figures are My-spend chargeback actuals (the Usage-per-user
est_cost_usd column was de-authorized 2026-10-14 — an estimator that ran
~2.7-3.3x hot); telemetry weeks between manual reads are model-derived.
Adoption context (org-wide gateway spend) must never
be used as a cross-team productivity comparison.</p>
  </div>
</div>
<div class="tip" id="tip"></div>
<script>
const tip = document.getElementById('tip');
document.addEventListener('mousemove', e => {{
  const t = e.target.closest('.bar');
  if (t) {{ tip.textContent = t.dataset.tip; tip.style.opacity = 1;
    tip.style.left = (e.clientX + 12) + 'px'; tip.style.top = (e.clientY - 28) + 'px'; }}
  else tip.style.opacity = 0;
}});
</script>
</body>
</html>
"""

out = os.path.join(ROI, "board.html")
with open(out, "w") as f:
    f.write(html)
print(f"wrote {out} ({len(html)} bytes)")
print(f"summary: cost ${sum_cost:,.0f} 2026 YTD; josh {sum_res} resolved / {sum_pts:.0f} pts; "
      f"shipped {sum_ship} tickets / {sum_ship_pts:.0f} pts; leverage {lev}x-{lev_hi}x")
