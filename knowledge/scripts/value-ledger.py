#!/usr/bin/env python3
"""value-ledger.py — the missing VALUE half of the harness ROI loop.

roi-report.py measures cost and *consumption* (did a finding get built or
accepted). It cannot say what a capability was worth. This ledger records the
outcome value a harness action produced, so the monthly value-report can put
value next to cost.

Two ways rows land here:
  1. derive (default) — zero-LLM, idempotent. Walks the outcome ledgers the
     harness already writes (triage-outcomes, proposal-outcomes, build-ledger,
     jira-triage runs) and appends one value row per delivered outcome, keyed so
     re-runs never duplicate.
  2. note — the human one-liner ("what this saved"), for value a ledger cannot
     see: incident prevented, hours saved, decision unblocked.

Hours are a HEURISTIC default per outcome class, deliberately conservative and
labeled; a `note --hours` row overrides it. Nothing here asserts a dollar
figure — it counts engineering-hours returned, which is the defensible unit.

Usage:
  value-ledger.py                     derive new rows from the outcome ledgers
  value-ledger.py derive              same
  value-ledger.py note --capability jira --hours 3 --ref BSYS-29418 \
        --type ticket_fixed --what "closed the prod 403 envelope fix"
  value-ledger.py list [--month YYYY-MM]
  value-ledger.py stats [--month YYYY-MM]

Ledger: ~/.claude/knowledge/garden-reports/value-ledger.jsonl (append-only).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import sys
from pathlib import Path
from atomic_io import atomic_append

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
G = K / "garden-reports"
LEDGER = G / "value-ledger.jsonl"
TRIAGE = G / "triage-outcomes.jsonl"
PROPOSALS = G / "proposal-outcomes.jsonl"
BUILD = K / "build-ledger.jsonl"
JRUNS = K / "jira-triage" / "runs.jsonl"

# heuristic engineering-hours returned per outcome class. Conservative and
# labeled; override any row with `note --hours`. incident_prevented and
# decision_unblocked default to 0 on purpose — never auto-asserted, only set
# by a human note.
DEFAULT_HOURS = {
    "ticket_fixed": 2.0,
    "fix_delivered": 2.0,
    "capability_built": 4.0,
    "build_delivered": 3.0,
    "ticket_planned": 1.0,
    "ticket_replied": 0.5,
    "incident_prevented": 0.0,
    "decision_unblocked": 0.0,
}

CAP_FROM_SOURCE = {
    "brain-gardener": "gardener", "gardener": "gardener",
    "workato-watchdog": "watchdog", "watchdog": "watchdog",
    "ops-autopsy": "watchdog",
    "regression-harness": "regression", "regression-nightly": "regression",
    "estate-architect": "architect",
    "jira-autotriage": "jira", "jira-triage": "jira",
    "cortex": "cortex", "dreamer": "dreamer",
    "harness-dreamer": "dreamer", "project-dreamer": "dreamer",
}
KNOWN_CAPS = {"watchdog", "gardener", "dreamer", "cortex", "watcher",
              "regression", "architect", "jira", "build", "harness"}


def normalize_cap(source):
    """Fold a free-text source into a known capability, else 'harness' — so
    one-off artifact names never leak into the report as fake capabilities."""
    cap = CAP_FROM_SOURCE.get(str(source or ""), str(source or ""))
    return cap if cap in KNOWN_CAPS else "harness"


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def today():
    return dt.date.today().isoformat()


def _key(*parts):
    h = hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]
    return h


def load_rows():
    if not LEDGER.exists():
        return []
    rows = []
    for line in LEDGER.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            rows.append(json.loads(line))
        except json.JSONDecodeError:
            pass
    return rows


def load_keys():
    return {r.get("key") for r in load_rows() if r.get("key")}


def read_jsonl(path):
    if not path.exists():
        return
    for line in path.read_text(errors="replace").splitlines():
        line = line.strip()
        if not line:
            continue
        try:
            yield json.loads(line)
        except json.JSONDecodeError:
            continue


def append(rows, keys):
    if not rows:
        return 0
    G.mkdir(parents=True, exist_ok=True)
    new_rows = []
    for r in rows:
        k = r.get("key")
        if not k or k in keys:
            continue
        keys.add(k)
        new_rows.append(r)
    if new_rows:
        atomic_append(LEDGER, new_rows)
    return len(new_rows)


def derive():
    keys = load_keys()
    out = []

    # 1. triage findings that were built (a delivered fix) or filed (a ticket)
    for r in read_jsonl(TRIAGE):
        slug = str(r.get("slug", "")).strip()
        if not slug:
            continue
        act = str(r.get("action", ""))
        if act == "built":
            vtype = "fix_delivered"
        elif act == "filed":
            vtype = "ticket_planned"
        else:
            continue
        cap = normalize_cap(r.get("source", ""))
        out.append({
            "ts": str(r.get("date", today())), "key": _key("triage", slug, act),
            "capability": cap, "source": r.get("source", ""), "ref": slug,
            "value_type": vtype, "hours": DEFAULT_HOURS.get(vtype, 0.0),
            "what": str(r.get("finding", ""))[:200], "jira": r.get("jira", ""),
            "origin": "derive", "by": r.get("by", "triage-decide"),
        })

    # 2. proposals that were built (a delivered capability)
    for r in read_jsonl(PROPOSALS):
        name = str(r.get("proposal", "")).strip()
        if not name or str(r.get("action", "")) != "built":
            continue
        out.append({
            "ts": str(r.get("date", today())), "key": _key("proposal", name),
            "capability": "dreamer", "source": "dreamer", "ref": name,
            "value_type": "capability_built",
            "hours": DEFAULT_HOURS["capability_built"],
            "what": str(r.get("notes", ""))[:200], "jira": "",
            "origin": "derive", "by": r.get("by", "proposal-decide"),
        })

    # 3. build-ledger — ONE value row per ticket, not per mutation. The ledger
    # records every airo-mutation / cli call; a delivered build is one ticket,
    # so key on the ticket alone (recount-don't-increment).
    for r in read_jsonl(BUILD):
        tk = r.get("ticket")
        if not tk:
            continue
        ts = str(r.get("ts", ""))[:10] or today()
        out.append({
            "ts": ts, "key": _key("build", tk),
            "capability": "build", "source": r.get("server", "build"),
            "ref": tk, "value_type": "build_delivered",
            "hours": DEFAULT_HOURS["build_delivered"],
            "what": f"{r.get('kind', 'build')} {r.get('tool', '')}".strip(),
            "jira": tk, "origin": "derive", "by": "build-ledger",
        })

    # 4. jira-triage runs: tickets fixed / planned / replied
    for i, r in enumerate(read_jsonl(JRUNS)):
        ts = str(r.get("ts", ""))[:10] or today()
        for j, item in enumerate(r.get("fixed", []) or []):
            out.append({
                "ts": ts, "key": _key("jira-fixed", ts, i, j),
                "capability": "jira", "source": "jira-autotriage",
                "ref": str(item)[:80], "value_type": "ticket_fixed",
                "hours": DEFAULT_HOURS["ticket_fixed"], "what": str(item)[:200],
                "jira": "", "origin": "derive", "by": "jira-triage",
            })
        for j, item in enumerate(r.get("planned", []) or []):
            out.append({
                "ts": ts, "key": _key("jira-planned", ts, i, j),
                "capability": "jira", "source": "jira-autotriage",
                "ref": str(item)[:80], "value_type": "ticket_planned",
                "hours": DEFAULT_HOURS["ticket_planned"], "what": str(item)[:200],
                "jira": "", "origin": "derive", "by": "jira-triage",
            })
        for j, item in enumerate(r.get("replied", []) or []):
            out.append({
                "ts": ts, "key": _key("jira-replied", ts, i, j),
                "capability": "jira", "source": "jira-autotriage",
                "ref": str(item)[:80], "value_type": "ticket_replied",
                "hours": DEFAULT_HOURS["ticket_replied"], "what": str(item)[:200],
                "jira": "", "origin": "derive", "by": "jira-triage",
            })

    n = append(out, keys)
    print(f"value-ledger: derived {n} new rows "
          f"({len(out)} candidates, {len(keys)} total keys)")
    return 0


def note(args):
    keys = load_keys()
    vtype = args.type or "decision_unblocked"
    hours = args.hours if args.hours is not None else DEFAULT_HOURS.get(vtype, 0.0)
    row = {
        "ts": args.date or today(),
        "key": _key("note", args.capability, args.ref, args.what, now_iso()),
        "capability": args.capability, "source": "human", "ref": args.ref or "",
        "value_type": vtype, "hours": hours,
        "what": args.what, "jira": args.jira or "",
        "origin": "note", "by": "josh",
    }
    append([row], keys)
    print(f"value-ledger: noted {vtype} {hours}h for {args.capability} "
          f"({args.ref or '-'}): {args.what}")
    return 0


def month_rows(ym):
    return [r for r in load_rows() if str(r.get("ts", "")).startswith(ym)]


def list_rows(args):
    ym = args.month or dt.date.today().strftime("%Y-%m")
    for r in month_rows(ym):
        print(f"{r.get('ts','')} {r.get('value_type',''):18} "
              f"{r.get('hours',0):>5}h {r.get('capability',''):10} "
              f"{(r.get('ref') or '')[:24]:24} {str(r.get('what',''))[:70]}")
    return 0


def stats(args):
    ym = args.month or dt.date.today().strftime("%Y-%m")
    rows = month_rows(ym)
    by_cap = {}
    by_type = {}
    total_h = 0.0
    for r in rows:
        h = float(r.get("hours", 0) or 0)
        total_h += h
        by_cap[r.get("capability", "?")] = by_cap.get(r.get("capability", "?"), 0) + h
        by_type[r.get("value_type", "?")] = by_type.get(r.get("value_type", "?"), 0) + 1
    print(f"value {ym}: {len(rows)} rows, {total_h:.1f} engineering-hours returned")
    for c, h in sorted(by_cap.items(), key=lambda x: -x[1]):
        print(f"  {c:12} {h:6.1f}h")
    print("  by type: " + ", ".join(f"{t}={n}" for t, n in sorted(by_type.items())))
    return 0


def main():
    p = argparse.ArgumentParser(description="harness value ledger")
    sub = p.add_subparsers(dest="cmd")
    sub.add_parser("derive")
    sub.add_parser("list").add_argument("--month")
    sub.add_parser("stats").add_argument("--month")
    np = sub.add_parser("note")
    np.add_argument("--capability", required=True)
    np.add_argument("--what", required=True)
    np.add_argument("--ref")
    np.add_argument("--hours", type=float)
    np.add_argument("--type")
    np.add_argument("--jira")
    np.add_argument("--date")
    args = p.parse_args()
    if args.cmd == "list":
        return list_rows(args)
    if args.cmd == "stats":
        return stats(args)
    if args.cmd == "note":
        return note(args)
    return derive()


if __name__ == "__main__":
    sys.exit(main())
