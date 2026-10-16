#!/usr/bin/env python3
"""replay-gym.py — nightly harness regression replay + immune fire drill.

The regression harness catches RECIPE regressions; this catches HARNESS
regressions (hooks, wt, the command loop, canon coverage) by replaying
yesterday's real activity as read-only assertions. Never mutates anything
in replay mode. The fire drill (--firedrill) is the one intentional
exception: it injects a failure into the dedicated drill recipe
(82934150), verifies the detection chain catches it, and restores.

Modes:
    replay-gym.py             nightly pass: replay + invariants + canary check
    replay-gym.py --firedrill immune fire drill (weekly): break -> detect -> restore

Report: knowledge/garden-reports/gym-<date>.md. Misses -> canon entry
(status: open, found_by: replay-gym) + noted for the morning brief.
"""
import argparse
import datetime as dt
import json
import re
import subprocess
import time
from pathlib import Path
from atomic_io import atomic_append

K = Path.home() / ".claude/knowledge"
LEDGER = K / "build-ledger.jsonl"
CANON = K / "regression-canon/canon.jsonl"
REPORTS = K / "garden-reports"
CANARY_STATUS = REPORTS / "command-canary-status.json"
HEARTBEAT = REPORTS / "heartbeat.jsonl"

WT = str(Path.home() / ".local/bin/wt")
DRILL_RECIPE = 82934150  # harness_fire_drill — reads its fail-mode from a drill-control row
# Recipe contract (built via AIRO, never edited by the gym): clock trigger ->
# get_records(queue table, filter directive=="fail") -> if a fail-row exists,
# parse its directive text as JSON ("fail" is invalid) -> job FAILS. No
# fail-row -> healthy heartbeat. The drill flips a ROW, never code — REST
# code PUTs silently no-op on the runtime (stale execution) and strip
# code_input.data on save; row writes are instant and reliable.


def drill_row(watcher, directive):
    """Upsert the drill-control row: newest fail-row flipped, or created."""
    # restore targets the FAIL rows (flip them to ok); injecting finds/creates
    # the fail row. Filtering for the TARGET state, not the desired one.
    want = "fail"
    status, resp = watcher.api("POST", "/query",
                               {"where": {"source_ref": {"$eq": "drill-mode"},
                                          "directive": {"$eq": want}}})
    rows = resp.get("data", []) if isinstance(resp, dict) else []
    if directive == "fail":
        if rows:
            rid = (rows[0][0] if isinstance(rows[0][0], list) else [rows[0][0]])[0]
            u = watcher.update_row(rid, {"directive": "fail"})
            return u[0] == 200
        status, resp = watcher.api("POST", "/records", {"document": {
            "directive": "fail", "author_slack_id": "DRILL-NOT-AUTHORITY",
            "status": "drill-control", "source_ref": "drill-mode"}})
        return status == 201
    # restore: flip every fail-row to ok
    ok = True
    for v in rows:
        rid = (v[0] if isinstance(v[0], list) else [v[0]])[0]
        u = watcher.update_row(rid, {"directive": "ok"})
        ok = ok and u[0] == 200
    return ok


def force_run_status():
    """Force-run + return the NEW job's status (force-run silently no-ops on
    stopped recipes — verify a job actually appeared)."""
    try:
        rc, before = wt(["jobs", "list", str(DRILL_RECIPE)])
        before_ids = {j["id"] for j in json.loads(before).get("items", [])}
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        before_ids = set()
    wt(["recipes", "force-run", str(DRILL_RECIPE)], timeout=120)
    time.sleep(8)
    try:
        rc, jobs = wt(["jobs", "list", str(DRILL_RECIPE)])
        items = json.loads(jobs).get("items", [])
    except (json.JSONDecodeError, subprocess.TimeoutExpired):
        return None, []
    new = [j for j in items if j["id"] not in before_ids]
    return (new[0].get("status") if new else None), items


def firedrill(findings):
    """Immune fire drill: flip the drill-control row to fail -> force-run ->
    assert FAILED job (the surface the watchdog autopsies) -> flip back ->
    assert green. Zero code edits, pure runtime-state injection."""
    now = lambda: dt.datetime.now(dt.timezone.utc).strftime("%H:%M:%S")
    t0 = time.time()

    import importlib.util
    spec = importlib.util.spec_from_file_location("w", str(Path.home() / ".local/bin/agent-command-watcher.py"))
    watcher = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(watcher)

    baseline, _ = force_run_status()
    if baseline != "succeeded":
        # leftover fail-rows from an interrupted drill are the usual cause —
        # self-clean, then re-baseline once
        drill_row(watcher, "ok")
        baseline, _ = force_run_status()
        if baseline != "succeeded":
            findings.append(f"firedrill-abort: baseline still not green after cleanup ({baseline}) — fix the drill recipe first")
            return
    print(f"[{now()}] baseline green")

    if not drill_row(watcher, "fail"):
        findings.append("firedrill-abort: could not queue the fail row")
        return
    fail_status, _ = force_run_status()
    inject_to_fail = time.time() - t0
    if fail_status != "failed":
        drill_row(watcher, "ok")
        findings.append(f"firedrill-miss: fail-row did NOT produce a failed job (got {fail_status})")
        return
    print(f"[{now()}] failure materialized (inject->fail {inject_to_fail:.0f}s)")

    if not drill_row(watcher, "ok"):
        findings.append("firedrill-CRITICAL: could not flip the fail row back — drill recipe keeps failing; fix the drill-mode row")
        canon_add("firedrill-restore-failed", DRILL_RECIPE, "harness-regression",
                  "fire drill could not restore healthy mode — flip the drill-mode row directive to ok")
        return
    green_status, _ = force_run_status()
    total = time.time() - t0
    if green_status != "succeeded":
        findings.append("firedrill-miss: post-restore force-run not green")
        return
    print(f"[{now()}] drill complete (inject->fail {inject_to_fail:.0f}s, total {total:.0f}s)")
    findings.append(f"firedrill-ok: fail-row -> FAILED job observed ({inject_to_fail:.0f}s) -> flipped back -> "
                    f"green ({total:.0f}s total). The failed job is in the job list for the watchdog's next autopsy pass.")



def wt(args, timeout=90):
    r = subprocess.run([WT] + args, capture_output=True, text=True, timeout=timeout)
    return r.returncode, (r.stdout or "") + (r.stderr or "")


def heartbeat(job, extra=None):
    row = {"ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
           "job": job}
    if extra:
        row.update(extra)
    atomic_append(HEARTBEAT, row)


def canon_add(signature, recipe_id, kind, line):
    row = {"signature": signature, "recipe_id": recipe_id, "kind": kind,
           "found_by": "replay-gym", "found": dt.date.today().isoformat(),
           "status": "open", "test_case_id": None, "line": line[:300]}
    atomic_append(CANON, row)
    return row


def load_window(hours=24):
    cutoff = time.time() - hours * 3600
    rows = []
    if not LEDGER.exists():
        return rows
    for l in LEDGER.read_text(errors="replace").splitlines():
        if not l.strip():
            continue
        try:
            r = json.loads(l)
        except json.JSONDecodeError:
            continue
        ts = r.get("ts", "")
        try:
            t = dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
        except (ValueError, AttributeError):
            continue
        if t >= cutoff:
            rows.append(r)
    return rows


def replay_pass(findings):
    rows = load_window(24)
    # recipe_id is only trustworthy from precise sources: airo-mutation rows
    # carry the exact id; composite shell rows (pipes, curl URLs) record
    # workspace/project/webhook ids in that field too (cost 75 false misses
    # live 2026-10-09). Single-command wt recipes rows are also precise.
    recipe_ids = set()
    for r in rows:
        rid = r.get("recipe_id")
        if not isinstance(rid, int):
            continue
        kind = r.get("kind", "")
        cmd = r.get("command", "") or ""
        if kind == "airo-mutation" or (
                kind == "workato-cli" and cmd.startswith("wt recipes ")
                and "|" not in cmd and ";" not in cmd):
            recipe_ids.add(rid)
    recipe_ids = sorted(recipe_ids)

    # 1. asset liveness — the ledger spans BOTH workspaces: prod recipes
    # (readable only via --profile josh-prod) read as 404 on dev.
    for rid in recipe_ids:
        rc, out = wt(["recipes", "get", str(rid), "--raw"])
        profile = "dev"
        if rc != 0:
            rc, out = wt(["recipes", "get", str(rid), "--raw", "--profile", "josh-prod"])
            profile = "josh-prod"
        if rc != 0:
            if "404" in out or "Not found" in out:
                findings.append(f"info: recipe {rid} deleted since yesterday (404 both profiles)")
            else:
                findings.append(f"asset-liveness: recipe {rid} unreadable on BOTH profiles (rc={rc}) — auth/schema problem?")
                canon_add(f"gym-recipe-unreadable-{rid}", rid, "harness-regression",
                          f"replay gym: recipe {rid} unreadable on dev AND prod (non-404)")
        else:
            try:
                running = json.loads(out).get("running")
                findings.append(f"info: recipe {rid} ({profile}) running={running}") if not running else None
            except json.JSONDecodeError:
                pass

    # 2. harness invariants: hooks installed, canary fresh. (Canon recipe
    # liveness is covered by pass 1 next night — no self-referential loop.)
    hooks = Path.home() / "mods/workato-guardrails/hooks/register.js"
    if not hooks.exists():
        findings.append("invariant-miss: workato-guardrails register.js missing — hooks not installed?")
    if CANARY_STATUS.exists():
        cs = json.loads(CANARY_STATUS.read_text())
        age_h = (time.time() - cs.get("checked_epoch", 0)) / 3600
        if not cs.get("pass"):
            findings.append(f"canary-fail: command loop canary FAILED at {cs.get('checked')} — {cs.get('detail', '')[:120]}")
        elif age_h > 26:
            findings.append(f"canary-stale: last command-loop canary {age_h:.0f}h ago (SLA: daily)")
    else:
        findings.append("canary-stale: command loop canary has never run")

    return {"ledger_rows": len(rows), "recipe_ids": recipe_ids}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--firedrill", action="store_true")
    args = ap.parse_args()

    findings = []
    stats = replay_pass(findings)

    if args.firedrill:
        firedrill(findings)

    misses = [f for f in findings if "info:" not in f and "firedrill-ok" not in f]
    date = dt.date.today().isoformat()
    report = REPORTS / f"gym-{date}.md"
    report.write_text(
        f"# Replay gym — {date}\n\n"
        f"- ledger rows in window: {stats['ledger_rows']}; recipes checked: {len(stats['recipe_ids'])}\n"
        f"- misses: {len(misses)}\n\n"
        + "\n".join(f"- {f}" for f in findings) + "\n")
    heartbeat("replay-gym", {"misses": len(misses), "firedrill": args.firedrill})
    for f in misses:
        if "replay-miss" in f or "invariant-miss" in f or "canary-fail" in f:
            canon_add("gym-" + re.sub(r"[^a-z0-9]+", "-", f.lower())[:50], None,
                      "harness-regression", f)
    print(f"gym done: {len(misses)} misses -> {report}")


if __name__ == "__main__":
    main()
