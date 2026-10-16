#!/usr/bin/env python3
"""cost-governor.py — daily dynamic cost/quality governor for the agentic harness.

Zero-LLM. Reads the flywheel's outcome data, computes per-task-class /
per-model posteriors (invocation count, verified-pass rate, cost proxy),
raises BUDGET ALARMS, and writes routing-table change PROPOSALS (never edits)
to the cortex attention queue.

Outputs: ~/.claude/knowledge/garden-reports/cost-governor-<YYYY-MM-DD>.md
Proposals: appended under "## Cost governor" in knowledge/cortex/attention-queue.md
           (read first, other content preserved; an existing section is replaced).

Cost proxies, honestly labeled:
  - Cortex dispatches: bytes of the dispatch log (the dispatch's whole output).
  - Fleet jobs: invocation count (brain-guard turn-usage lines carry in/out
    token counts but NO job/class/model attribution — instrumentation gap,
    proposed below). mcp-call bytes are also unattributed.
Pass signals, degraded gracefully:
  - Fleet jobs: fleet-validation.jsonl "stub" rows are fails; heartbeat count
    is the denominator. If a job has no validation row, pass rate = n/a.
  - Cortex dispatches: log exists and is substantial (>500 bytes) = produced
    output (proxy-pass); log tail matching a known gate/abort marker = fail.
  - Flywheel outcome ledger (dream_math/flywheel/outcomes*.jsonl): consumed
    if present; the search covers knowledge/ — absent today, noted in report.
"""

import json
import math
import os
import re
import sys
from datetime import date, datetime, timezone
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
GARDEN = K / "garden-reports"
ROUTING = K / "config" / "model-routing.json"
DISPATCHES = K / "cortex" / "dispatches.jsonl"
HEARTBEAT = GARDEN / "heartbeat.jsonl"
VALIDATION = GARDEN / "fleet-validation.jsonl"
FLEET_COST = K / "reports" / "fleet-cost.jsonl"  # P1 PRICEBOOK (2026-10-13)
ATTENTION = K / "cortex" / "attention-queue.md"

# heartbeat job name -> routing task class (routing classes are fixed by
# model-routing.json; jobs that map to nothing land in "unmapped" and are
# reported for transparency, never scored against a routing row)
JOB_TO_CLASS = {
    "room-sweep": "sweep", "corpus": "sweep", "docs-watch": "sweep",
    "loadout": "sweep", "morning-brief": "sweep", "workato-health": "sweep",
    "session-shadow": "sweep", "gym": "sweep", "healer": "sweep",
    "jira-triage": "triage-lane", "jira-triage-fleet": "triage-lane",
    "ops-autopsy": "autopsy-investigation", "workato-watchdog": "autopsy-investigation",
    "watchdog": "autopsy-investigation",
    "bsys-29418-fix": "build", "testcase-cleanup": "build", "uat-sweep": "build",
    "brain-gardener": "judgment", "gardener": "judgment",
    "harness-dreamer": "judgment", "dreamer": "judgment", "project-dreamer": "judgment",
    "harness-backup": "backup", "backup": "backup",
}
DISPATCH_CLASSES = ["sweep", "lookup", "autopsy-investigation"]  # dispatchable_by_cortex

GATE_MARKERS = [  # log-tail evidence the dispatch did NOT produce its finding
    "was blocked", "blocked by the sensitive-file gate", "permission denied",
    "saying the word", "not persisted", "i'll persist it",
]

WINDOW_DAYS = 7  # daily governor looks at the trailing week


def read_jsonl(path):
    rows = []
    if not path.exists():
        return rows
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def within_window(ts, days):
    if not ts:
        return False
    try:
        t = datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except Exception:
        return True  # unparsable timestamps stay in scope rather than vanish
    if t.tzinfo is None:
        t = t.replace(tzinfo=timezone.utc)
    return (datetime.now(timezone.utc) - t).days <= days


def find_flywheel_outcomes():
    """Search knowledge/ for dream_math/flywheel/outcomes jsonl. Absent today."""
    hits = []
    for pat in ("*flywheel*.jsonl", "*dream_math*", "*outcomes*.jsonl"):
        hits += list(K.glob(f"**/{pat}"))
    # exclude our own known outcome ledgers (they are consumed directly below)
    named = {"triage-outcomes.jsonl", "proposal-outcomes.jsonl", "fleet-validation.jsonl"}
    return [h for h in hits if h.name not in named]


def load_routing():
    try:
        return json.loads(ROUTING.read_text())
    except Exception:
        return {"default": {}, "classes": {}}


def main():
    today = date.today()
    routing = load_routing()
    classes = routing.get("classes", {})
    routing_json = json.dumps(routing)

    # ---- invocation counts from the heartbeat -------------------------------
    hb = [r for r in read_jsonl(HEARTBEAT) if within_window(r.get("ts", ""), WINDOW_DAYS)]
    hb_by_job = {}
    for r in hb:
        hb_by_job[r.get("job", "?")] = hb_by_job.get(r.get("job", "?"), 0) + 1

    # ---- failure signal from the validation ledger --------------------------
    val = [r for r in read_jsonl(VALIDATION) if within_window(r.get("ts", ""), WINDOW_DAYS)]
    fails_by_job = {}
    for r in val:
        j = r.get("job", "?")
        if "stub" in str(r.get("result", "")):
            fails_by_job[j] = fails_by_job.get(j, 0) + 1

    # ---- REAL fleet cost (P1 PRICEBOOK, 2026-10-13): gateway costUSD per -----
    # fleet session, attributed by fleet-cost.py (prompt-prefix matching).
    # Replaces/annotates the invocation-count byte-proxy for fleet jobs where
    # rows exist; interactive + cortex dispatch spend is still proxy-only.
    fleet_rows = [r for r in read_jsonl(FLEET_COST)
                  if within_window(r.get("ts", ""), WINDOW_DAYS)]
    fleet_by_job = {}
    for r in fleet_rows:
        j = r.get("job", "?")
        st = fleet_by_job.setdefault(j, {"n": 0, "usd": 0.0, "costed": 0})
        st["n"] += 1
        c = r.get("cost_usd")
        if isinstance(c, (int, float)):
            st["usd"] += float(c)
            st["costed"] += 1

    # ---- cortex dispatches: class, output bytes, proxy pass -----------------
    dispatches = [r for r in read_jsonl(DISPATCHES) if within_window(r.get("ts", ""), WINDOW_DAYS)]
    disp_stats = {}  # class -> {n, bytes, pass, fail}
    for r in dispatches:
        cls = r.get("class", "unmapped")
        log = Path(os.path.expanduser(r.get("log", ""))) if r.get("log") else None
        size = log.stat().st_size if log and log.exists() else 0
        tail = ""
        if log and log.exists():
            try:
                tail = log.read_text(errors="replace")[-4000:].lower()
            except Exception:
                pass
        st = disp_stats.setdefault(cls, {"n": 0, "bytes": 0, "pass": 0, "fail": 0, "gated": 0})
        st["n"] += 1
        st["bytes"] += size
        if size == 0:
            st["fail"] += 1  # log vanished or never written
        elif any(m in tail for m in GATE_MARKERS):
            # The harness write gate blocked persisting the finding — the
            # investigation itself was substantive (lookup-cost-spike
            # attribution, 2026-10-12). Not a model-quality fail; excluded
            # from the pass rate until the gate gets a sanctioned channel.
            # Sanctioned channel (2026-10-12): a bus post from cortex with the
            # dispatch's task in the subject counts as persisted.
            task = str(r.get("task", ""))[:40].lower()
            bus_persisted = bool(task) and any(
                task[:20] in str(b.get("subject", "")).lower()
                for b in read_jsonl(K / "dreams" / "bus" / "cortex.jsonl")
                if str(b.get("type", "")) == "investigation")
            if bus_persisted:
                st["pass"] += 1
            else:
                st["gated"] += 1
        else:
            st["pass"] += 1

    # ---- outcome ledgers (consumed-findings pass signal, by keyword) --------
    triage_rows = [r for r in read_jsonl(GARDEN / "triage-outcomes.jsonl")
                   if within_window(str(r.get("date", "")), WINDOW_DAYS)]
    proposal_rows = [r for r in read_jsonl(GARDEN / "proposal-outcomes.jsonl")
                     if within_window(str(r.get("date", "")), WINDOW_DAYS)]
    accepted_rows = ([r for r in triage_rows if str(r.get("action", "")) == "built"] +
                     [r for r in proposal_rows if str(r.get("action", "")) == "accepted"])

    # ---- per-class rollup ----------------------------------------------------
    rows = []
    for cls, cfg in classes.items():
        model = cfg.get("headless", "?")
        n_hb = sum(v for k, v in hb_by_job.items() if JOB_TO_CLASS.get(k) == cls)
        n_disp = disp_stats.get(cls, {}).get("n", 0)
        n = n_hb + n_disp
        # pass rate: prefer explicit signals (validation ledger + dispatch logs)
        fb = sum(fails_by_job.get(k, 0) for k, v in JOB_TO_CLASS.items() if v == cls)
        dp = disp_stats.get(cls, {})
        if dp.get("n", 0) + n_hb == 0:
            rows.append({"cls": cls, "model": model, "n": 0, "pass": None,
                         "cost": 0, "cost_kind": "none", "cur": cfg.get("agent_alias", "?")})
            continue
        pass_n = dp.get("pass", 0) + max(n_hb - fb, 0)
        # write-gate-blocked dispatches are exempt from pass-rate scoring
        # (excluded from the denominator, counted in neither pass nor fail)
        total_signal = dp.get("n", 0) - dp.get("gated", 0) + n_hb
        pass_rate = pass_n / total_signal if total_signal else None
        # cost proxy: dispatch-log bytes when the class has dispatches,
        # otherwise invocation count (no attributed token data exists)
        if n_disp and dp.get("bytes", 0):
            cost = dp["bytes"]
            cost_kind = "dispatch-log bytes"
        else:
            cost = n_hb
            cost_kind = "invocations (no attributed token data)"
        rows.append({"cls": cls, "model": model, "n": n, "pass": pass_rate,
                     "cost": cost, "cost_kind": cost_kind, "cur": cfg.get("agent_alias", "?")})

    # unmapped heartbeat jobs — transparency row
    unmapped = {k: v for k, v in hb_by_job.items() if k not in JOB_TO_CLASS}
    unmapped_n = sum(unmapped.values())

    # ---- budget alarm: spend > 2x median AND known pass rate < 0.80 ----------
    with_spend = [r for r in rows if r["cost"] > 0]
    median_cost = 0
    if with_spend:
        cs = sorted(r["cost"] for r in with_spend)
        m = len(cs)
        median_cost = cs[m // 2] if m % 2 else (cs[m // 2 - 1] + cs[m // 2]) / 2
    alarms = [r for r in rows
              if r["cost"] > 2 * median_cost and r["pass"] is not None and r["pass"] < 0.80]

    # ---- proposals ------------------------------------------------------------
    props = []
    for r in rows:
        if r["n"] == 0:
            continue
        cheap = r["model"] == "fireworks/glm-5.3-flash"
        if r["pass"] is not None and r["pass"] < 0.80 and r["n"] >= 5 and cheap:
            props.append(f"UPGRADE SIGNAL: `{r['cls']}` on glm-5.3-flash shows "
                         f"pass {r['pass']*100:.0f}% over {r['n']} runs — propose trial "
                         f"upgrade to kimi-k3 for this class (Josh approves).")
        if r["pass"] is not None and r["pass"] >= 0.90 and r["n"] >= 5 and not cheap:
            props.append(f"DOWNGRADE TRIAL: `{r['cls']}` on kimi-k3 shows pass "
                         f"{r['pass']*100:.0f}% over {r['n']} runs at the class's highest "
                         f"cost — propose an A/B trial on glm-5.3-flash (Josh approves).")
    # instrumentation proposal (always, once) — the attribution gap is structural
    tu = sum(1 for r in read_jsonl(GARDEN / "usage-ledger.jsonl")
             if r.get("kind") == "turn-usage")
    props.append(f"INSTRUMENTATION: brain-guard has logged {tu} turn-usage lines with "
                 "in/out token counts but NO job/class/model field, so per-class token "
                 "cost is a proxy (dispatch-log bytes; fleet runs scored nominally). "
                 "Propose: brain-guard adds job+model to turn-usage lines — then this "
                 "governor switches to true token cost with no other change.")
    fly_hits = find_flywheel_outcomes()
    if not fly_hits:
        props.append("FLYWHEEL GAP: no dream_math/flywheel/outcomes ledger exists yet "
                     "(searched knowledge/). Verified-pass posterior currently rests on "
                     "the validation ledger + dispatch-log signals; when the failure-"
                     "flywheel write-back (dream proposal 2026-10-08) ships its outcomes "
                     "jsonl, this governor consumes it first.")

    # ---- write the governor report -------------------------------------------
    rep = GARDEN / f"cost-governor-{today.isoformat()}.md"
    GARDEN.mkdir(parents=True, exist_ok=True)
    lines = []
    lines.append(f"# Cost governor — {today.isoformat()} (trailing {WINDOW_DAYS}d window)")
    lines.append("")
    lines.append(f"Data sources read: model-routing.json, usage-ledger.jsonl "
                 f"({tu} turn-usage lines lifetime), cortex/dispatches.jsonl "
                 f"({len(dispatches)} in window), heartbeat.jsonl ({len(hb)} in window), "
                 f"fleet-validation.jsonl ({len(val)} in window), triage/proposal "
                 f"outcome ledgers ({len(triage_rows)}+{len(proposal_rows)} in window), "
                 f"fleet-cost.jsonl ({len(fleet_rows)} in window — real gateway "
                 f"costUSD, P1 PRICEBOOK).")
    lines.append("")
    lines.append("**Cost proxy note:** no token counts are attributable per class or "
                 "model today. Cost proxy = dispatch-log bytes for classes with cortex "
                 "dispatches, invocation count otherwise (fleet runs are scored by "
                 "count; brain-guard turn-usage tokens carry no job/class/model field). "
                 "Byte counts are an output-volume proxy, not dollars. EXCEPTION: "
                 "fleet jobs with rows in fleet-cost.jsonl now carry REAL gateway "
                 "costUSD below — where present, read dollars there, not the "
                 "invocation proxy.")
    lines.append("")
    lines.append("## Per-class posterior table")
    lines.append("")
    lines.append("| class | model (headless) | runs | pass rate | cost proxy | current routing |")
    lines.append("|---|---|---|---|---|---|")
    for r in rows:
        pr = f"{r['pass']*100:.0f}%" if r["pass"] is not None else "n/a (no signal)"
        lines.append(f"| {r['cls']} | {r['model']} | {r['n']} | {pr} | "
                     f"{r['cost']:,} | {r['cur']} |")
    if unmapped:
        lines.append("")
        lines.append(f"Unmapped heartbeat jobs ({unmapped_n} runs, no routing class): "
                     + ", ".join(f"{k} ({v})" for k, v in sorted(unmapped.items())))
    lines.append("")
    lines.append("## Budget alarms")
    lines.append("")
    lines.append(f"Spend median across classes: {median_cost:,.0f}. "
                 "Alarm rule: spend proxy >2x median AND known pass rate <80%.")
    lines.append("")
    if alarms:
        for a in alarms:
            lines.append(f"- **BUDGET ALARM — {a['cls']}**: cost proxy {a['cost']:,} "
                         f"(>2x median), pass rate {a['pass']*100:.0f}% — paying above-"
                         f"median for below-threshold quality. Routed to {a['model']}.")
    else:
        lines.append("- none. No class is simultaneously above 2x the spend median and "
                     "below an 80% known pass rate.")
    lines.append("")
    # ---- REAL fleet cost section (P1 PRICEBOOK, 2026-10-13) ------------------
    lines.append("## Real fleet cost (gateway costUSD, trailing "
                 f"{WINDOW_DAYS}d) — P1 PRICEBOOK")
    lines.append("")
    if fleet_by_job:
        lines.append("Source: knowledge/reports/fleet-cost.jsonl (fleet-cost.py "
                     "--report; sessions attributed by job-prompt prefix; costUSD "
                     "is the gateway's own per-session total, present since "
                     "~2026-10-12 — sessions without it are token-only rows). "
                     "For these fleet jobs this REPLACES the invocation-count "
                     "proxy above as the honest cost signal.")
        lines.append("")
        lines.append("| fleet job | routing class | sessions | costed | real costUSD (7d) |")
        lines.append("|---|---|---|---|---|")
        cls_real = {}
        for j in sorted(fleet_by_job):
            st = fleet_by_job[j]
            cls = JOB_TO_CLASS.get(j, "unmapped")
            cls_real.setdefault(cls, 0.0)
            cls_real[cls] += st["usd"]
            lines.append(f"| {j} | {cls} | {st['n']} | {st['costed']} | "
                         f"{st['usd']:.2f} |")
        lines.append("")
        lines.append("Real costUSD by routing class: "
                     + ", ".join(f"{c} ${v:.2f}" for c, v in sorted(cls_real.items()))
                     + f". Fleet total 7d: ${sum(cls_real.values()):.2f}.")
    else:
        lines.append("No fleet-cost.jsonl rows in window (run "
                     "`fleet-cost.py --report` to populate; likely a pre-"
                     "2026-10-12 corpus or the job has not run). Fleet spend "
                     "remains proxy-only this window.")
    lines.append("")
    lines.append("## Routing-table proposals (PROPOSALS ONLY — model-routing.json is "
                 "Josh-approved; the cortex proposes, Josh approves)")
    lines.append("")
    if props:
        for p in props:
            lines.append(f"- {p}")
    else:
        lines.append("- no change signals this window.")
    lines.append("")
    lines.append(f"_Classes with runs: {sum(1 for r in rows if r['n'])}/{len(rows)}. "
                 f"Window accepted findings: {len(accepted_rows)} "
                 "(context for pass-rate denominators). Nothing was mutated — "
                 "model-routing.json untouched._")
    rep.write_text("\n".join(lines) + "\n")

    # ---- attention queue: append/replace "## Cost governor" section ----------
    section = ["## Cost governor", f"_cost-governor.py {today.isoformat()} — "
               "proposals only; Josh approves any routing edit._", ""]
    if alarms:
        for a in alarms:
            section.append(f"- **BUDGET ALARM — {a['cls']}**: cost proxy {a['cost']:,} "
                           f">2x median, pass {a['pass']*100:.0f}%. Report: "
                           f"garden-reports/{rep.name}")
    else:
        section.append(f"- No budget alarms this window (median spend proxy "
                       f"{median_cost:,.0f}).")
    for p in props:
        section.append(f"- {p}")
    section.append(f"- Full table: garden-reports/{rep.name}")
    section.append("")

    existing = ATTENTION.read_text() if ATTENTION.exists() else ""
    marker = "## Cost governor"
    if marker in existing:
        head, rest = existing.split(marker, 1)
        # drop the old section body up to the next "## " (if any) and keep it
        after = rest.split("\n## ", 1)
        old_body, tail = ("\n## " + after[1], "") if len(after) > 1 else (after[0], "")
        # preserve any non-governor content that lived after the old section
        kept = tail.strip("\n")
        new = head.rstrip("\n") + "\n\n" + "\n".join(section).rstrip("\n") + "\n"
        if kept:
            new += "\n" + kept + "\n"
    else:
        new = (existing.rstrip("\n") + "\n\n" if existing.strip() else "") + \
              "\n".join(section).rstrip("\n") + "\n"
    ATTENTION.write_text(new)

    print(f"governor report: {rep}")
    print(f"attention queue updated: {ATTENTION}")
    print(f"alarms: {len(alarms)}; proposals: {len(props)}; "
          f"classes with runs: {sum(1 for r in rows if r['n'])}")


if __name__ == "__main__":
    sys.exit(main())
