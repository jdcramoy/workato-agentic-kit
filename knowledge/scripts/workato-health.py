#!/usr/bin/env python3
"""workato-health.py — bounded health pull for assets we own.

Reads workato-health/owned-registry.json (from asset-fingerprint.py) and
makes ONE `wt recipes get` call per selected asset (cap 50/run, hypercare
and new assets first, then newest-touched rotation). Writes:

  workato-health/sweeps/<ts>.jsonl   one verdict per asset
  workato-health/health-latest.json  sweep summary + failures

New failures (failed-count increase or stopped recipe) are appended to the
TRIAGE QUEUE (knowledge/triage/queue.jsonl, status open, deduped: an existing
open row for the same slug is updated in place) and posted to the gossip bus
(thread: recipe-health). mcp_mock registry probe jobs (title/context contains
"mcp_mock_genie_id") are excluded — they are noise by design. Red TEST-CASE
job runs (is_test_case_job=true in the job payload) are excluded too: a
recipe's failed test case is authoring noise, not a recipe failure. Everything
is read-only against Workato.

Usage:
  workato-health.py               run sweep
  workato-health.py --dry-run     select assets, call nothing
  workato-health.py --json        summary as JSON
"""
import fcntl, json, os, subprocess, sys, tempfile, time, datetime as dt
from atomic_io import atomic_append

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
H = os.path.join(K, "workato-health")
REG = os.path.join(H, "owned-registry.json")
STATE = os.path.join(H, "state.json")
LATEST = os.path.join(H, "health-latest.json")
SWEEPS = os.path.join(H, "sweeps")
QUEUE = os.path.join(K, "triage", "queue.jsonl")
BUS = os.path.join(K, "dreams", "bus", "workato-health.jsonl")
MC_EVENTS = os.path.join(K, "mission-control", "events.jsonl")
CAP = 50
PROFILE = {"dev": "josh-us", "prod": "josh-prod"}


def load_registry():
    if not os.path.exists(REG):
        subprocess.run(["python3", os.path.join(HOME, ".claude", "knowledge",
                                               "scripts", "asset-fingerprint.py")], timeout=60)
    return json.load(open(REG))


def select_assets(reg):
    """Hypercare + new first, then newest-touched rotation, capped."""
    recipes = reg.get("recipes", [])
    pri = [e for e in recipes if "hypercare" in e["flags"] or "new" in e["flags"]]
    rest = [e for e in recipes if e not in pri]
    return (pri + rest)[:CAP]


WT = os.environ.get("WT_BIN", os.path.expanduser("~/.local/bin/wt"))


def wt_get(rid, server, timeout=25):
    cmd = [WT, "recipes", "get", rid, "--raw"]
    prof = PROFILE.get(server, "josh-us")
    cmd += ["--profile", prof]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        out = r.stdout.strip()
        if r.returncode != 0 or not out.startswith("{"):
            return None, (out or r.stderr)[:200]
        return json.loads(out), None
    except subprocess.TimeoutExpired:
        return None, "timeout"


def wt_failed_jobs(rid, server, timeout=25):
    """One page of recent failed jobs for a recipe (empty on any error)."""
    cmd = [WT, "jobs", "list", str(rid), "--status", "failed", "--raw",
           "--profile", PROFILE.get(server, "josh-us")]
    try:
        r = subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)
        if r.returncode != 0 or not r.stdout.strip().startswith("{"):
            return []
        data = json.loads(r.stdout)
        return (data.get("items") or []) if isinstance(data, dict) else []
    except (subprocess.TimeoutExpired, ValueError):
        return []


def is_probe_job(job):
    """True for mcp_mock registry health-probe jobs (noise by design)."""
    return "mcp_mock" in json.dumps(job).lower()


def is_test_case_job(job):
    """True for failed TEST-CASE runs (authoring noise, not recipe failures).

    Proven 2026-10-11: recipe 82272892's red test-case job j-AbtJNHaT was
    counted as a real recipe failure while the recipe itself was fine (UAT).
    Any recipe's red test case is authoring noise — same shape of exclusion
    as mcp_mock probe jobs, matched on the job payload's is_test_case_job
    flag (top-level or nested).
    """
    return bool(job.get("is_test_case_job")) or "is_test_case_job" in json.dumps(job)


# harness_fire_drill (82934150) is the harness fire drill: it intentionally
# plants a failing task ("fail" / drill-mode / DRILL-NOT-AUTHORITY markers —
# e.g. failed job j-AbtH9wHd-MezE9t-CD carrying task fields "fail" and
# "drill-control") as a controlled canary, then recovery succeeds seconds
# later (j-AbtH9nPX succeeded 11s after the planted failure). Its failures
# and stop/starts are noise by design, like mcp_mock probe jobs — excluded by
# recipe identity so classification stays fast (no trace fetch needed).
FIRE_DRILL_RECIPES = {"82934150"}


def load_state():
    try:
        return json.load(open(STATE))
    except Exception:
        return {"failed_counts": {}}


def queue_load():
    try:
        with open(QUEUE) as fh:
            return [json.loads(l) for l in fh if l.strip()]
    except Exception:
        return []


def ownership(rid, qrows):
    """Who already owns this failing asset? Returns (owner, pending_age_h).

    triage-owned  — a non-terminal triage finding naming the asset is actively
                    owned (accepted/filed = being acted on). Re-alerting adds
                    nothing; the finding carries the state.
    mc-pending    — a mission-control row (in-flight/needs-josh/blocked) names
                    the asset: a decision is pending. Mute + escalate if it has
                    sat >4h (the 82964017 incident: verdict open 16h, no SLA).
    None          — unowned: post the finding normally.
    """
    for r in qrows:
        if r.get("status") in ("accepted", "filed") and rid in (r.get("slug", "") + " " + r.get("title", "")):
            return "triage-owned", 0.0
    try:
        events = [json.loads(l) for l in open(MC_EVENTS) if l.strip()][-300:]
    except Exception:
        events = []
    # only real DECISION rows count as ownership: needs-josh/blocked are
    # pending Josh calls; in-flight matched dropped-session deadman rows and
    # cortex pulses that merely MENTION an asset (live-proven false-mute
    # 2026-10-14 on 82964017)
    for e in reversed(events):
        if e.get("state") in ("needs-josh", "blocked") and rid in json.dumps(e):
            try:
                age_h = (dt.datetime.now(dt.timezone.utc)
                         - dt.datetime.fromisoformat(e["ts"].replace("Z", "+00:00"))).total_seconds() / 3600
            except Exception:
                age_h = 0.0
            return "mc-pending", age_h
    return None, 0.0


def triage_append(finding):
    """Dedupe-aware append to the triage queue.

    Proven bug fixed 2026-10-11: the old body did an UNLOCKED queue_load()
    then a whole-file atomic_write on every dedupe hit — a read-modify-write
    race against triage-decide.py's save() (its rows written between our read
    and our replace were clobbered) and it silently restamped the matched
    row's ts (seen 03:09:59 Oct 11), making an old finding look fresh again.

    Now: the read happens INSIDE the queue's flock (same <path>.lock every
    atomic_io writer honors), so the matched-line swap is atomic against all
    concurrent writers. Only the matched line is re-serialized; unrelated
    lines are copied through byte-for-byte. The row's ORIGINAL ts is
    preserved — only `evidence` is refreshed (that field holds the latest
    sweep's observed detail; ts drives /triage age ranking and must not
    move). No matching open row -> plain append (the recorder's fan-out
    tolerates duplicates; queue integrity beats byte-minimalism).
    """
    os.makedirs(os.path.dirname(QUEUE), exist_ok=True)
    with open(QUEUE + ".lock", "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        try:
            try:
                with open(QUEUE, "r", encoding="utf-8") as fh:
                    raw_lines = fh.read().splitlines(keepends=True)
            except FileNotFoundError:
                raw_lines = []
            match_i = None
            for i, raw in enumerate(raw_lines):
                if not raw.strip():
                    continue
                try:
                    r = json.loads(raw)
                except ValueError:
                    continue
                if r.get("slug") == finding["slug"] and r.get("status") == "open":
                    match_i = i
                    break
            if match_i is None:
                pass  # fall through to append below, after releasing the lock
            else:
                orig = json.loads(raw_lines[match_i])
                updated = {**orig, "evidence": finding["evidence"]}  # ts preserved
                out = list(raw_lines)
                out[match_i] = json.dumps(updated, ensure_ascii=False) + "\n"
                fd, tmp = tempfile.mkstemp(dir=os.path.dirname(QUEUE),
                                           prefix=".tmp-", suffix=".jsonl")
                try:
                    with os.fdopen(fd, "wb") as t:
                        t.write("".join(out).encode("utf-8"))
                        t.flush()
                        os.fsync(t.fileno())
                    os.replace(tmp, QUEUE)
                except BaseException:
                    try:
                        os.unlink(tmp)
                    except OSError:
                        pass
                    raise
                return
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)
    atomic_append(QUEUE, finding)  # takes its own flock; safe after release


def bus_post(e):
    atomic_append(BUS, e)


def main():
    dry = "--dry-run" in sys.argv
    as_json = "--json" in sys.argv
    reg = load_registry()
    state = load_state()
    prev_fails = state.get("failed_counts", {})
    selected = select_assets(reg)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    rows, failures = [], []
    probe_excluded = 0

    for e in selected:
        rid, server = e["id"], ("prod" if "prod" in e["servers"] else "dev")
        if dry:
            rows.append({"id": rid, "server": server, "verdict": "selected"})
            continue
        data, err = wt_get(rid, server)
        if err:
            verdict, name = "unverifiable", ""
            detail = err[:120]
        else:
            name = data.get("name", "")
            running = bool(data.get("running"))
            fails = int(data.get("job_failed_count") or 0)
            stop_cause = data.get("stop_cause")
            prev = int(prev_fails.get(rid, fails))
            detail = (f'running={running} fails={fails} (was {prev}) '
                      f'last_run={str(data.get("last_run_at"))[:19]} stop_cause={stop_cause}')
            if rid in FIRE_DRILL_RECIPES:
                # fire drill: planned canary failure + harness-controlled
                # stop/start — never a real stopped/new-failures verdict
                verdict = "ok"
                detail += " (fire-drill: planned failure excluded)"
            elif not running and stop_cause:
                verdict = "stopped"
            elif fails > prev:
                fj = wt_failed_jobs(rid, server)
                probes = sum(1 for j in fj if is_probe_job(j))
                cases = sum(1 for j in fj if is_test_case_job(j))
                probe_excluded += probes
                real = [j for j in fj if not (is_probe_job(j) or is_test_case_job(j))]
                if fj and not real:
                    verdict = "ok"  # probe / red-test-case noise only
                else:
                    verdict = "new-failures"
                if probes:
                    detail += f" ({probes} probe jobs excluded)"
                if cases:
                    detail += f" ({cases} test-case jobs excluded)"
            elif not running:
                verdict = "not-running"
            else:
                verdict = "ok"
        row = {"ts": now, "id": rid, "server": server, "verdict": verdict,
               "name": name, "flags": e["flags"], "detail": detail}
        rows.append(row)
        if verdict in ("stopped", "new-failures"):
            failures.append(row)

    # persist sweep
    os.makedirs(SWEEPS, exist_ok=True)
    with open(os.path.join(SWEEPS, f"{now.replace(':', '')}.jsonl"), "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")

    # update state (failed counts) only on real runs
    if not dry:
        for r in rows:
            m = r["detail"].split("fails=")
            if len(m) > 1:
                try:
                    prev_fails[r["id"]] = int(m[1].split(" ")[0])
                except (ValueError, IndexError):
                    pass
        json.dump({"updated": now, "failed_counts": prev_fails}, open(STATE, "w"), indent=1)

    # failures -> triage queue + bus, with mute-on-ownership + escalation
    # (2026-10-14, graduated from incubating proposal sweep-finding-mute-on-
    # defect-verdict in the contrarian-amended form: mute ALWAYS pairs with
    # escalation of stale pending decisions, so muting can never automate
    # the skimming it fears)
    qrows = queue_load()
    muted, escalated = [], []
    for f in failures:
        owner, age_h = ownership(f["id"], qrows)
        if owner == "triage-owned":
            muted.append(f["id"])
            continue
        if owner == "mc-pending":
            muted.append(f["id"])
            last_esc = state.get("escalated_ts", {}).get(f["id"], "")
            esc_age_h = 1e9
            if last_esc:
                try:
                    esc_age_h = (dt.datetime.now(dt.timezone.utc)
                                 - dt.datetime.fromisoformat(last_esc.replace("Z", "+00:00"))).total_seconds() / 3600
                except Exception:
                    pass
            if age_h > 4 and esc_age_h >= 12:
                bus_post({"ts": now, "agent": "workato-health", "kind": "escalation",
                          "thread_id": "recipe-health",
                          "line": f"ESCALATION: {f['id']} {f['verdict']} [{f['server']}] has a pending "
                                  f"decision {age_h:.0f}h old with no resolution - needs Josh"})
                esc = state.setdefault("escalated_ts", {})
                esc[f["id"]] = now
                json.dump(state, open(STATE, "w"), indent=1)
                escalated.append(f["id"])
            continue
        triage_append({"ts": now, "slug": f"recipe-health-{f['id']}-{f['verdict']}",
                       "kind": "bugfix", "source": "workato-health",
                       "title": f"{f['verdict']}: recipe {f['id']} ({f['server']}) {f['name'][:60]}",
                       "evidence": f"wt recipes get {f['id']} --profile {PROFILE.get(f['server'])}: {f['detail'][:120]}",
                       "work": "autopsy + fix-forward (dev-scoped unless prod hotfix, which needs Josh)",
                       "points": 3, "status": "open"})
    live = [f for f in failures if f["id"] not in muted]
    if live:
        bus_post({"ts": now, "agent": "workato-health", "kind": "finding",
                  "thread_id": "recipe-health",
                  "line": f"sweep: {len(live)} failing owned asset(s): "
                          + "; ".join(f"{f['id']} {f['verdict']} [{f['server']}]" for f in live[:5])})
    if muted:
        bus_post({"ts": now, "agent": "workato-health", "kind": "sweep-muted",
                  "thread_id": "recipe-health",
                  "line": f"sweep-muted (owned/pending-elsewhere, not re-alerting): "
                          + ", ".join(f"{m}" for m in muted[:5])})


    summary = {"ts": now, "selected": len(rows),
               "verdicts": {v: sum(1 for r in rows if r["verdict"] == v) for v in
                            ("ok", "stopped", "new-failures", "not-running", "unverifiable")},
               "failures": failures}
    json.dump(summary, open(LATEST, "w"), indent=1)
    # heartbeat check-in so the dashboard timer chip sees liveness
    atomic_append(os.path.join(K, "garden-reports", "heartbeat.jsonl"),
                  {"ts": now, "job": "workato-health"})
    line = (f"sweep done: {summary['selected']} assets -> {summary['verdicts']} "
            f"| {len(failures)} failures -> triage queue + bus")
    if probe_excluded:
        line += f" ({probe_excluded} probe jobs excluded)"
    try:  # write our own fleet log line; launchd stdout capture is unreliable
        with open(os.path.join(HOME, ".local", "state", "fleet", "health.log"), "a") as fh:
            fh.write(f"{now} {line}\n")
    except OSError:
        pass
    print(json.dumps(summary, indent=1) if as_json else line)


if __name__ == "__main__":
    main()
