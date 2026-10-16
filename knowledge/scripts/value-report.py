#!/usr/bin/env python3
"""value-report.py — monthly value-vs-cost roll for the agentic harness.

The counterpart to roi-report.py. roi-report answers "what should we stop?"
(cost + consumption). This answers "what was it worth?" — it joins the value
ledger (engineering-hours returned, by capability) with the same cost proxies
roi-report uses (dispatch-log bytes for cortex, invocation count otherwise), and
prints value per capability next to its cost.

Zero-LLM. Reads:
  - garden-reports/value-ledger.jsonl   (value: hours returned, by capability)
  - garden-reports/heartbeat.jsonl      (cost: invocations)
  - cortex/dispatches.jsonl             (cost: dispatch-log bytes)
Reuses roi-report.py's JOB_TO_CAP + readers so the two reports agree.

Output: ~/.claude/knowledge/garden-reports/value-<YYYY-MM>.md
Nothing is mutated.
"""
import importlib.util
import json
import os
import sys
from datetime import date
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
G = K / "garden-reports"
SCRIPTS = K / "scripts"

# reuse roi-report's mapping + readers so cost lines match exactly
_spec = importlib.util.spec_from_file_location("roi_report", SCRIPTS / "roi-report.py")
roi = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(roi)


def load_value_rows(ym):
    p = G / "value-ledger.jsonl"
    if not p.exists():
        return []
    rows = []
    for line in p.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        if str(r.get("ts", "")).startswith(ym):
            rows.append(r)
    return rows


def main():
    ym = date.today().strftime("%Y-%m")

    rows = load_value_rows(ym)
    hours = {}
    count = {}
    types = {}
    for r in rows:
        cap = r.get("capability", "unknown")
        h = float(r.get("hours", 0) or 0)
        hours[cap] = hours.get(cap, 0.0) + h
        count[cap] = count.get(cap, 0) + 1
        types[r.get("value_type", "?")] = types.get(r.get("value_type", "?"), 0) + 1

    # cost proxies, identical to roi-report
    hb = {}
    for r in roi.read_jsonl_month(G / "heartbeat.jsonl", ym):
        hb[r.get("job", "?")] = hb.get(r.get("job", "?"), 0) + 1
    disp_bytes = 0
    for r in roi.read_jsonl_month(K / "cortex" / "dispatches.jsonl", ym):
        log = Path(r.get("log", "")) if r.get("log") else None
        if log and log.exists():
            try:
                disp_bytes += log.stat().st_size
            except OSError:
                pass

    caps = sorted(set(list(hours) + list(count) + roi.CAPABILITIES))

    def cost_for(cap):
        inv = sum(n for j, n in hb.items() if roi.JOB_TO_CAP.get(j) == cap)
        if cap == "cortex":
            return f"{disp_bytes:,}B dispatch log"
        return f"{inv} runs"

    total_h = sum(hours.values())
    rep = G / f"value-{ym}.md"
    G.mkdir(parents=True, exist_ok=True)
    L = []
    L.append(f"# Capability VALUE vs cost — {ym} (month to date)")
    L.append("")
    L.append("The value half of ROI. roi-report.py answers what to stop; this "
             "answers what the harness was worth. Value = engineering-hours "
             "returned, recorded in garden-reports/value-ledger.jsonl. Hours are "
             "a HEURISTIC per outcome class (see value-ledger.py DEFAULT_HOURS), "
             "conservative and labeled; a human `note` row overrides. This is "
             "hours returned, not dollars — the defensible unit. Cost column is "
             "the same proxy roi-report uses (invocation count, dispatch bytes "
             "for cortex); no per-capability token attribution exists yet.")
    L.append("")
    L.append("| capability | value rows | hours returned | cost proxy | hours / run |")
    L.append("|---|---|---|---|---|")
    for cap in caps:
        if cap not in hours and cap not in count:
            continue
        inv = sum(n for j, n in hb.items() if roi.JOB_TO_CAP.get(j) == cap)
        per = (hours.get(cap, 0.0) / inv) if inv else 0.0
        L.append(f"| {cap} | {count.get(cap, 0)} | {hours.get(cap, 0.0):.1f} | "
                 f"{cost_for(cap)} | {per:.2f} |")
    L.append("")
    L.append(f"**Total: {len(rows)} value rows, {total_h:.1f} engineering-hours "
             f"returned this month** (month to date; grows as the month does).")
    L.append("")
    if types:
        L.append("By outcome type: " + ", ".join(f"{t}={n}" for t, n in sorted(types.items())))
        L.append("")
    L.append("Read with roi-report.py: a capability with high hours returned and low "
             "cost is PROMOTE-worthy; one with runs but zero value rows for 30 days "
             "is the KILL case. Incident-prevented and decision-unblocked value is "
             "only ever recorded by a human note, never auto-asserted.")
    rep.write_text("\n".join(L) + "\n")
    print(f"value report: {rep}")
    print(f"  total: {len(rows)} rows, {total_h:.1f} hours returned")
    for cap in caps:
        if cap in hours:
            print(f"  {cap}: {hours[cap]:.1f}h over {count.get(cap, 0)} rows")
    return 0


if __name__ == "__main__":
    sys.exit(main())
