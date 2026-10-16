#!/usr/bin/env python3
"""roi-report.py — monthly capability ROI roll for the agentic harness.

Zero-LLM. Per capability (watchdog, gardener, dreamer, cortex, watcher,
shadow, regression, backup): invocation count (heartbeat), findings produced
(month's artifacts/ledger rows), dispatch cost proxy, and a
KILL / PROMOTE / KEEP recommendation:
  KILL    — 30 days of runs produced zero consumed findings
            (consumed = the finding surfaces in triage-outcomes or
            proposal-outcomes with action built/accepted)
  PROMOTE — findings -> accepted-changes ratio > 0.5
  KEEP    — otherwise

Output: ~/.claude/knowledge/garden-reports/roi-<YYYY-MM>.md
Nothing is mutated. Backup is special-cased: it produces no findings by
design, so the findings-based KILL rule does not apply.
"""

import json
import os
import sys
from collections import defaultdict
from datetime import date
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
GARDEN = K / "garden-reports"
HEARTBEAT = GARDEN / "heartbeat.jsonl"
TRIAGE = GARDEN / "triage-outcomes.jsonl"
PROPOSALS = GARDEN / "proposal-outcomes.jsonl"

# heartbeat job name -> capability
JOB_TO_CAP = {
    "workato-watchdog": "watchdog", "watchdog": "watchdog", "ops-autopsy": "watchdog",
    "brain-gardener": "gardener", "gardener": "gardener",
    "harness-dreamer": "dreamer", "dreamer": "dreamer", "project-dreamer": "dreamer",
    "cortex": "cortex",
    "workato-health": "watcher", "docs-watch": "watcher", "room-sweep": "watcher",
    "loadout": "watcher", "morning-brief": "watcher",
    "session-shadow": "shadow",
    "regression-nightly": "regression", "testcase-cleanup": "regression",
    "harness-backup": "backup", "backup": "backup",
}

CAPABILITIES = ["watchdog", "gardener", "dreamer", "cortex", "watcher",
                "shadow", "regression", "backup"]

# findings-produced artifacts per capability, scoped to the month
def findings_for(cap, ym):
    n = 0
    def count(pat):
        return len(list(GARDEN.glob(pat)))
    if cap == "watchdog":
        n += count(f"watchdog-{ym}-*.md")
    elif cap == "gardener":
        n += count(f"*{ym}-*gardener*.md")
    elif cap == "dreamer":
        n += len(list((K / "dreams").glob(f"{ym}-*.md")))
        n += len(list((K / "dreams" / "proposals").glob(f"{ym}-*.md")))
    elif cap == "cortex":
        n += sum(1 for _ in read_jsonl_month(K / "cortex" / "dispatches.jsonl", ym))
        n += len([p for p in (K / "cortex" / "investigations").glob("*.md")
                  if month_of_mtime(p, ym)])
    elif cap == "watcher":
        n += sum(1 for _ in read_jsonl_month(GARDEN / "platform-delta.jsonl", ym))
    elif cap == "shadow":
        # bus lines are per-minute focus pings (status, not findings); shadow
        # publishes ambient state to knowledge/now/ instead — findings n/a
        n += 0
    elif cap == "regression":
        n += count(f"regression-{ym}-*.md")
    elif cap == "backup":
        n += 0  # no findings by design
    return n


def month_of_mtime(path, ym):
    try:
        return date.fromtimestamp(path.stat().st_mtime).strftime("%Y-%m") == ym
    except OSError:
        return False


def read_jsonl_month(path, ym):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            r = json.loads(line)
        except json.JSONDecodeError:
            continue
        ts = str(r.get("ts", r.get("date", "")))
        if ts.startswith(ym):
            yield r


def main():
    ym = date.today().strftime("%Y-%m")

    hb = defaultdict(int)
    for r in read_jsonl_month(HEARTBEAT, ym):
        hb[r.get("job", "?")] += 1

    # consumed findings: accepted/built outcomes, attributed by keyword to a capability
    keywords = {
        "watchdog": ["autopsy", "watchdog", "failure", "stall"],
        "gardener": ["gardener", "index", "claim", "memory", "insight"],
        "dreamer": ["dream", "proposal", "vision"],
        "cortex": ["cortex", "dispatch", "investigation", "attention"],
        "watcher": ["watcher", "changelog", "docs", "delta", "command"],
        "shadow": ["shadow", "session"],
        "regression": ["regression", "canon", "test case", "fixture"],
    }

    def consumed_rows():
        for r in read_jsonl_month(TRIAGE, ym):
            if str(r.get("action", "")) == "built":
                yield " ".join(str(r.get(k, "")) for k in
                               ("finding", "slug", "source", "notes"))
        for r in read_jsonl_month(PROPOSALS, ym):
            if str(r.get("action", "")) == "accepted":
                yield " ".join(str(r.get(k, "")) for k in
                               ("proposal", "report", "notes"))

    consumed_text = list(consumed_rows())
    consumed_by_cap = defaultdict(int)
    unattributed = 0
    for text in consumed_text:
        low = text.lower()
        # single credit, first capability whose keywords match (priority =
        # CAPABILITIES order); avoids inflating ratios above 100%
        for c in CAPABILITIES:
            if any(kw in low for kw in keywords.get(c, [])):
                consumed_by_cap[c] += 1
                break
        else:
            unattributed += 1
    total_consumed = len(consumed_text)

    # cost proxy: dispatch-log bytes for cortex, invocation count otherwise
    disp_bytes = 0
    for r in read_jsonl_month(K / "cortex" / "dispatches.jsonl", ym):
        log = Path(r.get("log", "")) if r.get("log") else None
        if log and log.exists():
            try:
                disp_bytes += log.stat().st_size
            except OSError:
                pass

    recs = {}
    unmapped = {j: n for j, n in hb.items() if j not in JOB_TO_CAP}
    for cap in CAPABILITIES:
        invocations = sum(n for j, n in hb.items() if JOB_TO_CAP.get(j) == cap)
        findings = findings_for(cap, ym)
        if cap == "cortex":
            cost = f"{disp_bytes:,} dispatch-log bytes"
        else:
            cost = f"{invocations} runs (invocation proxy; no attributed token data)"
        consumed = consumed_by_cap.get(cap, 0)
        if cap == "backup":
            rec = "KEEP (by design: backup produces no findings; the KILL rule on " \
                  "consumed findings does not apply — verify by snapshot count instead)"
            ratio_txt = "n/a"
        elif invocations == 0:
            rec = "KEEP (no runs this month — insufficient data; do not kill on silence)"
            ratio_txt = "n/a"
        elif findings == 0 and consumed > 0:
            rec = "KEEP (consumed findings exist; this capability publishes ambient " \
                  "status, not discrete findings — the findings-based rules do not apply)"
            ratio_txt = f"{consumed}/n-a"
        elif consumed == 0 and total_consumed == 0:
            rec = "KEEP (no consumed findings anywhere this month — attribution, " \
                  "not production, is the bottleneck)"
            ratio_txt = "n/a"
        else:
            ratio = consumed / findings if findings else 0
            # findings are counted as report FILES, which undercounts reports
            # bundling multiple findings — flag rather than fake precision
            if consumed > findings:
                ratio_txt = f"{consumed}/{findings} >= 100% (file-count findings proxy)"
            else:
                ratio_txt = f"{consumed}/{findings} = {ratio:.0%}"
            if ratio > 0.5:
                rec = f"PROMOTE (findings -> accepted {ratio_txt} > 0.5)"
            elif consumed == 0:
                rec = f"KILL-CANDIDATE ({invocations} invocations, {findings} findings, " \
                      "ZERO consumed — the 30d rule fires if this stands at month end)"
            else:
                rec = f"KEEP (findings -> accepted {ratio_txt})"
        recs[cap] = {"invocations": invocations, "findings": findings,
                     "cost": cost, "consumed": consumed, "rec": rec, "ratio": ratio_txt}

    rep = GARDEN / f"roi-{ym}.md"
    GARDEN.mkdir(parents=True, exist_ok=True)
    L = []
    L.append(f"# Capability ROI — {ym} (month to date)")
    L.append("")
    L.append("Partial-month data: this roll covers heartbeat/ledger rows dated in "
             f"{ym} up to today; counts grow as the month does. Invocation source: "
             "garden-reports/heartbeat.jsonl. Consumed findings: triage-outcomes "
             "(action=built) + proposal-outcomes (action=accepted), attributed by "
             "single-keyword match (heuristic; unmatched consumption is counted as "
             "unattributable). Findings produced are counted as report FILES, so a "
             "report bundling several findings undercounts — ratios are directional, "
             "not precise. Cost proxy: dispatch-log bytes (cortex) / invocation "
             "count (all others); no per-capability token attribution exists "
             "(brain-guard turn-usage lines carry no job/model field).")
    L.append("")
    L.append("| capability | invocations | findings produced | cost proxy | findings -> accepted | recommendation |")
    L.append("|---|---|---|---|---|---|")
    for cap in CAPABILITIES:
        r = recs[cap]
        L.append(f"| {cap} | {r['invocations']} | {r['findings']} | {r['cost']} | "
                 f"{r['ratio']} | {r['rec']} |")
    L.append("")
    L.append(f"Total consumed findings this month: {total_consumed} "
             f"({unattributed} unattributable to any capability). "
             f"Unmapped heartbeat jobs ({sum(unmapped.values())} runs, no capability): "
             + (", ".join(f"{k} ({v})" for k, v in sorted(unmapped.items())) or "none"))
    L.append("")
    L.append("Rule: KILL if 30 days of runs produced zero consumed findings; PROMOTE "
             "if findings->accepted ratio > 0.5; KEEP otherwise. Backup is exempt "
             "(no findings by design). All recommendations are advisory — capability "
             "removal is Josh's call, executed via the proposals/triage queues.")
    rep.write_text("\n".join(L) + "\n")
    print(f"roi report: {rep}")
    for cap in CAPABILITIES:
        print(f"  {cap}: {recs[cap]['rec']}")


if __name__ == "__main__":
    sys.exit(main())
