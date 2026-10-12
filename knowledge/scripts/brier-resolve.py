#!/usr/bin/env python3
"""brier-resolve.py — nightly resolver for the Calibration Ledger.

Reads knowledge/predictions/predictions.jsonl. For every prediction still open
whose resolve_by has passed, attempts resolution per its resolver_query:

  wt-health:recipe=<id>:expect=running|stopped       -> `wt api GET /api/recipes/<id>`
  wt-health:recipe=<id>:expect=new-failures          -> any failed job since the
      prediction was submitted, via `wt jobs list <id> --status failed`
  wt-health:recipe=<id>:expect=no-new-failures       -> the negation
  wt-health:sweeps:indicator=<name>:expect=above|below-baseline
      -> workato-health sweeps daily aggregate over the resolve window vs baseline
  manual                                             -> flagged "needs-josh" (once)
  anything else / probe failure                      -> "unresolved-extended":
      resolve_by pushed +7 days, extension counter incremented

Append-only: resolutions, flags, and extensions are NEW lines keyed by id (the
aggregation below joins on id); the original line is never rewritten.
Brier = (outcome - confidence)^2, on resolved rows only.

Prints a per-agent calibration table (mean Brier, n, sorted best-first) and
writes knowledge/predictions/calibration-report-<ts>.md.

Exit codes: 0 normal (including nothing to do), 1 ledger missing/unreadable.
"""
import argparse, json, os, subprocess, sys, time
from collections import defaultdict
from datetime import date, datetime, timedelta

LEDGER = os.path.expanduser("~/.claude/knowledge/predictions/predictions.jsonl")
REPORT_DIR = os.path.expanduser("~/.claude/knowledge/predictions")
SWEEPS = os.path.expanduser("~/.claude/knowledge/workato-health/sweeps")
EXTEND_DAYS = 7
WT = os.path.expanduser("~/.local/bin/wt")


# ---------- ledger io ----------

def read_rows():
    if not os.path.exists(LEDGER):
        return []
    rows = []
    with open(LEDGER) as f:
        for n, line in enumerate(f, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                print(f"WARNING: malformed line {n} skipped", file=sys.stderr)
    return rows


def append(row):
    with open(LEDGER, "a") as f:
        f.write(json.dumps(row) + "\n")


def iso(ts):
    return datetime.fromisoformat(str(ts).replace("Z", "+00:00"))


# ---------- resolvers ----------

def wt(*args):
    r = subprocess.run([WT, *args], capture_output=True, text=True, timeout=90)
    if r.returncode != 0:
        raise WtError(r.returncode, f"wt {' '.join(args)} rc={r.returncode}: {r.stderr.strip()[:200]}")
    return r.stdout


class WtError(RuntimeError):
    def __init__(self, rc, msg):
        super().__init__(msg)
        self.rc = rc


def resolve_wt_recipe(pred, expect):
    """Return (outcome 0/1, evidence str) or raise WtError."""
    rid = pred["_recipe_id"]
    if expect in ("running", "stopped"):
        try:
            doc = json.loads(wt("api", "GET", f"/api/recipes/{rid}"))
        except WtError as e:
            if "HTTP 404" in str(e):
                # a 404 on a known recipe id means the recipe no longer exists —
                # a definitive observation, not a probe failure
                if expect == "running":
                    return 0, f"recipe {rid} HTTP 404 — deleted, certainly not running"
                return 1, f"recipe {rid} HTTP 404 — deleted, certainly not running"
            raise
        running = bool(doc.get("running"))
        want = (expect == "running")
        return (1 if running == want else 0), f"recipe {rid} running={running}"
    if expect in ("new-failures", "no-new-failures"):
        out = wt("jobs", "list", rid, "--status", "failed", "--raw")
        doc = json.loads(out)
        since = iso(pred["ts"])
        newest = None
        for item in doc.get("items", []):
            st = item.get("started_at") or item.get("completed_at")
            if not st:
                continue
            if iso(st) > since:
                newest = f"{item.get('id')} at {st} — {str(item.get('error'))[:120]}"
                break  # items are newest-first
        had = newest is not None
        want = (expect == "new-failures")
        ev = newest or f"no failed job after {pred['ts']}"
        return (1 if had == want else 0), ev
    raise RuntimeError(f"unsupported expect {expect!r}")


def daily_sweep_series(indicator):
    """indicator -> {day: value} from workato-health sweeps."""
    import glob, re
    series = defaultdict(float)
    files = sorted(glob.glob(os.path.join(SWEEPS, "*.jsonl")))
    last_verdict = {}  # id -> verdict, for restart detection
    for fn in files:
        try:
            lines = open(fn).read().splitlines()
        except OSError:
            continue
        day = None
        m = re.search(r"(\d{4}-\d{2}-\d{2})", os.path.basename(fn))
        for line in lines:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = str(r.get("ts") or "")
            d = ts[:10] if ts[:4].isdigit() else (m.group(1) if m else None)
            if not d:
                continue
            day = d
            verdict = r.get("verdict", "")
            rid = str(r.get("id"))
            detail = (r.get("detail") or "")
            if indicator == "job-failures":
                mm = re.search(r"fails=(\d+) \(was (\d+)\)", detail)
                if mm:
                    series[d] += max(0, int(mm.group(1)) - int(mm.group(2)))
            elif indicator == "failed-recipes":
                if verdict == "new-failures":
                    series[d] += 1
            elif indicator == "connection-errors":
                low = (detail + " " + str(r.get("name") or "")).lower()
                if any(t in low for t in ("401", "403", "connection", "unauthorized",
                                          "service unavailable", "timeout", "auth")):
                    series[d] += 1
            elif indicator == "restarts":
                prev = last_verdict.get(rid)
                if prev == "not-running" and verdict == "ok":
                    series[d] += 1
                last_verdict[rid] = verdict
        # rows with no per-row day still belong to the file's day for restarts
    return dict(series)


def resolve_wt_sweeps(pred, indicator, expect):
    """True if the indicator's mean over [pred.ts, today] sits above/below the
    trailing baseline (all days before the window)."""
    series = daily_sweep_series(indicator)
    if not series:
        raise RuntimeError("no sweep data")
    since = iso(pred["ts"]).date()
    window = {d: v for d, v in series.items() if date.fromisoformat(d) >= since}
    base = {d: v for d, v in series.items() if date.fromisoformat(d) < since}
    if not window:
        raise RuntimeError("no sweep data in the resolve window yet")
    wmean = sum(window.values()) / len(window)
    if base:
        bmean = sum(base.values()) / len(base)
    else:
        bmean = wmean  # degenerate: no baseline -> cannot be above/below
    if expect == "above-baseline":
        outcome, ev = (1 if wmean > bmean else 0), (f"window mean {wmean:.2f} vs baseline {bmean:.2f}")
    else:
        outcome, ev = (1 if wmean < bmean else 0), (f"window mean {wmean:.2f} vs baseline {bmean:.2f}")
    return outcome, ev


# ---------- main ----------

def main():
    ap = argparse.ArgumentParser(description="Resolve due predictions, compute Brier "
                                 "scores, print calibration table, write the daily report.")
    ap.add_argument("--dry-run", action="store_true",
                    help="show what would be resolved without writing")
    args = ap.parse_args()

    today = date.today()
    if not os.path.exists(LEDGER):
        print("no predictions ledger yet — nothing to resolve")
        return 0
    rows = read_rows()

    # group by id: submission = row with claim; later rows = resolution/flag/extension events
    subs, events = {}, defaultdict(list)
    for r in rows:
        if "claim" in r:
            subs[r["id"]] = r
        else:
            events[r["id"]].append(r)

    fresh = []           # event rows to append this run
    resolved = []        # (sub, outcome, brier, evidence)
    needs_josh, extended, probe_failed = [], [], []
    for pid, sub in subs.items():
        evs = events.get(pid, [])
        if any(e.get("type") == "resolution" for e in evs):
            continue  # settled — the join already has its outcome
        exts = [e for e in evs if e.get("type") == "extension"]
        flags = [e for e in evs if e.get("type") == "flag"]
        if flags and not exts:
            continue  # parked as needs-josh until a manual resolution lands
        # effective due date: latest extension pushes it, else the original
        due = date.fromisoformat(exts[-1]["resolve_by"]) if exts \
            else date.fromisoformat(sub["resolve_by"])
        if due > today:
            continue  # not yet due
        n_ext = len(exts)
        rq = sub.get("resolver_query", "")

        if rq == "manual":
            needs_josh.append(sub)
            if not args.dry_run:
                fresh.append({"id": pid, "ts": now_ts(), "type": "flag",
                              "flag": "needs-josh",
                              "note": "manual resolver — Josh (or a session) must "
                                      "check and submit a resolution line"})
            continue

        if rq.startswith("wt-health"):
            try:
                parts = dict(p.split("=", 1) for p in rq.split(":")[1:] if "=" in p)
                if "recipe" in parts:
                    sub["_recipe_id"] = parts["recipe"]
                    outcome, ev = resolve_wt_recipe(sub, parts.get("expect", ""))
                elif parts.get("indicator"):
                    outcome, ev = resolve_wt_sweeps(sub, parts["indicator"],
                                                    parts.get("expect", "above-baseline"))
                else:
                    raise RuntimeError(f"unparseable wt-health query {rq!r}")
                brier = round((outcome - sub["confidence"]) ** 2, 4)
                status = "resolved_true" if outcome == 1 else "resolved_false"
                resolved.append((sub, outcome, brier, ev))
                if not args.dry_run:
                    fresh.append({"id": pid, "ts": now_ts(), "type": "resolution",
                                  "status": status, "outcome": outcome,
                                  "brier": brier, "resolved_at": now_ts(),
                                  "evidence": ev})
            except Exception as e:
                probe_failed.append((sub, str(e)))
                if not args.dry_run:
                    new_due = (today + timedelta(days=EXTEND_DAYS)).isoformat()
                    fresh.append({"id": pid, "ts": now_ts(), "type": "extension",
                                  "status": "open", "event": "unresolved-extended",
                                  "resolve_by": new_due,
                                  "extensions": n_ext + 1,
                                  "note": f"resolver probe failed: {str(e)[:200]}"})
            continue

        # default: unresolved-extended
        extended.append(sub)
        if not args.dry_run:
            new_due = (today + timedelta(days=EXTEND_DAYS)).isoformat()
            fresh.append({"id": pid, "ts": now_ts(), "type": "extension",
                          "status": "open", "event": "unresolved-extended",
                          "resolve_by": new_due, "extensions": n_ext + 1,
                          "note": f"no recognized resolver for {rq!r}"})

    if fresh and not args.dry_run:
        for r in fresh:
            append(r)

    # ---------- calibration table (join submissions with latest resolution) ----------
    outcome_by_id = {}
    for r in rows + fresh:
        if r.get("type") == "resolution":
            outcome_by_id[r["id"]] = r
    by_agent = defaultdict(list)
    for pid, res in outcome_by_id.items():
        sub = subs.get(pid)
        if sub:
            by_agent[sub["agent"]].append((sub, res["brier"]))

    agent_stats = []
    for agent, items in by_agent.items():
        n = len(items)
        mean_b = sum(b for _, b in items) / n
        agent_stats.append((agent, mean_b, n))
    agent_stats.sort(key=lambda t: (t[1], t[0]))

    flagged_ids = {r["id"] for r in rows + fresh if r.get("type") == "flag"}
    ext_ids = {r["id"] for r in rows + fresh if r.get("type") == "extension"}
    open_ids = [s["id"] for s in subs.values()
                if s["id"] not in outcome_by_id and s["id"] not in flagged_ids
                and s["id"] not in ext_ids]

    print(f"\n=== Calibration Ledger — {today.isoformat()} ===")
    print(f"{len(subs)} predictions | {len(outcome_by_id)} resolved | "
          f"{len(flagged_ids)} needs-josh | {len(ext_ids)} extended | {len(open_ids)} not yet due")
    print("\nPer-agent calibration (mean Brier, best first — lower is better; "
          "coin-flip baseline = 0.25):")
    if agent_stats:
        print(f"  {'agent':<22}{'n':>4}{'mean Brier':>12}")
        for agent, mb, n in agent_stats:
            print(f"  {agent:<22}{n:>4}{mb:>12.4f}")
    else:
        print("  (no resolved predictions yet)")
    for sub, outcome, brier, ev in resolved:
        print(f"  {sub['id']} {sub['agent']}: {'TRUE ' if outcome else 'FALSE'} "
              f"brier={brier} — {ev[:110]}")
    if needs_josh:
        print("\nneeds-josh (manual resolvers due):")
        for s in needs_josh:
            print(f"  {s['id']} [{s['agent']}] {s['claim'][:100]}")
    if extended or probe_failed:
        print("\nunresolved-extended (+7d):")
        for s, why in probe_failed:
            print(f"  {s['id']} probe failed: {why[:110]}")
        for s in extended:
            print(f"  {s['id']} no recognized resolver: {s['resolver_query'][:110]}")
    print()

    if not args.dry_run:
        write_report(today, subs, outcome_by_id, agent_stats, needs_josh, extended,
                     probe_failed, len(open_ids))
    return 0


def now_ts():
    return time.strftime("%Y-%m-%dT%H:%M:%S%z")


def write_report(today, subs, outcome_by_id, agent_stats, needs_josh, extended,
                 probe_failed, n_open):
    os.makedirs(REPORT_DIR, exist_ok=True)
    path = os.path.join(REPORT_DIR, f"calibration-report-{today.isoformat()}.md")
    L = [f"# Calibration report — {today.isoformat()}", "",
         f"{len(subs)} predictions on ledger; {len(outcome_by_id)} resolved; "
         f"{n_open} not yet due; {len(flagged(needs_josh))} needs-josh; "
         f"{len(extended) + len(probe_failed)} extended.", "",
         "## Per-agent calibration (mean Brier, best first)", "",
         "| agent | n | mean Brier |", "|---|---|---|"]
    for agent, mb, n in agent_stats:
        L.append(f"| {agent} | {n} | {mb:.4f} |")
    if not agent_stats:
        L.append("| (none resolved yet) | | |")
    L += ["", "## Resolutions", ""]
    for pid, res in outcome_by_id.items():
        sub = subs.get(pid, {})
        L.append(f"- **{pid}** [{sub.get('agent')}] "
                 f"{'TRUE' if res.get('outcome') else 'FALSE'} "
                 f"brier={res.get('brier')} — {sub.get('claim', '')[:140]}")
        if res.get("evidence"):
            L.append(f"  - evidence: {res['evidence'][:200]}")
    if needs_josh or extended or probe_failed:
        L += ["", "## Not resolved", ""]
        for s in needs_josh:
            L.append(f"- {s['id']} [{s['agent']}] needs-josh — {s['claim'][:140]}")
        for s, why in probe_failed:
            L.append(f"- {s['id']} extended (probe failed: {why[:150]})")
        for s in extended:
            L.append(f"- {s['id']} extended (no recognized resolver)")
    with open(path, "w") as f:
        f.write("\n".join(L) + "\n")
    print(f"report: {path}")


def flagged(needs_josh):
    return needs_josh


if __name__ == "__main__":
    sys.exit(main() or 0)
