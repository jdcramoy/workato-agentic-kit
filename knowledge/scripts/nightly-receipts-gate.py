#!/usr/bin/env python3
"""nightly-receipts-gate.py — morning gate over the nightly schedule's OUTPUTS.

Implements dreams/proposals/2026-10-16-nightly-sync-receipts.md as amended by
Josh-accepted dissent (re_looks 2026-10-17/18): the gate routes on MISSING
OUTPUT — report/artifact existence and freshness per job — NEVER on
self-reported receipts. Self-reported liveness can lie two ways:
  - crash-after-work  -> receipt row written, artifact absent -> false alarm
  - zombie-ok         -> artifact stale, receipt says fine    -> false pass
So the receipts ledger is auxiliary data only (the gate appends its run
verdicts to garden-reports/nightly-receipts.jsonl for the record); every
escalation decision below keys on the job's output artifact being present
(and where the artifact encodes it, fresh) for the job's last scheduled run.

Schedule verified live from ~/Library/LaunchAgents/ on 2026-10-19 (deviates
from the proposal text: docs-watch fires 22:31, dreamer 23:43 — the 03:47 in
the proposal was the dreamer's old fire time). No StartCalendarInterval in
this set carries a Weekday key — all eight jobs are DAILY; the `weekday`
config slot below is carried for future Monday-only jobs and validated
against the plist facts on --verify-config.

Per-job ground-truth outputs (traced from the plists -> run-job.sh -> job
prompts/scripts -> the scripts' own docstrings):

  docs-watch   22:31  garden-reports/platform-delta.jsonl (crawler appends)
  gardener     22:43  garden-reports/<date>-brain-gardener-nightly.md
  watchdog     23:13  watchdog-reports/<date>.md
  backup       23:33  newest commit in the backup repo (josh-orca)
  kb-sync      21:37  ~/.claude/workato-kb/diffs/<date>.json (must PARSE)
  dreamer      23:43  dreams/<date>.md  (the report-existence tripwire,
                        folded in here as one instance — not duplicated)
  kb-digest    22:07  last "date" marker block in ~/.claude/workato-kb/digest.log
  registry-backup 04:23  registry-snapshot-latest.json "exported_at" field

run-date rule: a job's "last night" run is TODAY if the current time is past
its fire time, else YESTERDAY. A morning gate (e.g. 07:00) therefore expects
the 23:xx jobs' artifacts dated yesterday and the 04:23 registry backup dated
today. Freshness = artifact date >= run-date.

Escalation: each stale job gets one bus row via bus_post.py (agent
nightly-receipts-gate, type finding — bus_post.py's enforced schema has five
types and no "escalation"; the escalation semantics live in the subject/claim,
the corroboration counter groups on type+subject so nightly repeats count
mechanically). One escalation per job per run-date — a state file dedupes
re-runs of the same morning.

Usage:
  python3 nightly-receipts-gate.py            # summary + bus escalations
  python3 nightly-receipts-gate.py --json     # machine-readable verdicts
  python3 nightly-receipts-gate.py --no-bus   # verdicts only, post nothing
  python3 nightly-receipts-gate.py --verify-config  # restate plist facts

Read-only over job outputs. Stdlib only. Not wired into launchd (Josh
schedules it); standalone runnable.
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
SCRIPTS = HOME / ".claude/knowledge/scripts"
sys.path.insert(0, str(SCRIPTS))

GARDEN = HOME / ".claude/knowledge/garden-reports"
STATE_FILE = GARDEN / "nightly-gate-state.json"
RECEIPTS_LEDGER = GARDEN / "nightly-receipts.jsonl"  # auxiliary record only
AGENT = "nightly-receipts-gate"
SUBJECT = "nightly-receipts-gate"

# --- job table: fire time verified against the plist 2026-10-19 -------------
# weekday: None = daily; 0-6 = launchd Weekday (0/7=Sun..6=Sat). No job in the
# current nightly set carries a Weekday key (verified from the plists).
JOBS = [
    {
        "job": "docs-watch", "plist": "com.josh.fleet.docs-watch",
        "fire": (22, 31), "weekday": None,
        "artifact": str(GARDEN / "platform-delta.jsonl"),
        "check": "mtime-date",
        "desc": "platform-delta.jsonl (crawler appends; docs-watch session summarizes)",
    },
    {
        "job": "gardener", "plist": "com.josh.fleet.gardener",
        "fire": (22, 43), "weekday": None,
        "artifact": str(GARDEN / "{run_date}-brain-gardener-nightly.md"),
        "check": "exists",
        "desc": "garden report for the run date",
    },
    {
        "job": "watchdog", "plist": "com.josh.fleet.watchdog",
        "fire": (23, 13), "weekday": None,
        "artifact": str(HOME / ".claude/knowledge/watchdog-reports/{run_date}.md"),
        "check": "exists",
        "desc": "watchdog report for the run date",
    },
    {
        "job": "backup", "plist": "com.josh.fleet.backup",
        "fire": (23, 33), "weekday": None,
        "artifact": str(HOME / "Documents/josh-orca"),  # newest commit timestamp
        "check": "git-commit-date",
        "desc": "newest commit in the harness backup repo (josh-orca)",
    },
    {
        "job": "kb-sync", "plist": "com.josh.workato-kb-sync",
        "fire": (21, 37), "weekday": None,
        "artifact": str(HOME / ".claude/workato-kb/diffs/{run_date}.json"),
        "check": "exists-parse",
        "desc": "nightly diff report (must exist AND parse as JSON)",
    },
    {
        "job": "dreamer", "plist": "com.josh.fleet.dreamer",
        "fire": (23, 43), "weekday": None,
        "artifact": str(HOME / ".claude/knowledge/dreams/{run_date}.md"),
        "check": "exists",
        "desc": "dream report (the report-existence tripwire, folded in)",
    },
    {
        "job": "kb-digest", "plist": "com.josh.workato-kb-digest",
        "fire": (22, 7), "weekday": None,
        "artifact": str(HOME / ".claude/workato-kb/digest.log"),
        "check": "digest-date-marker",
        "desc": 'last "date" block in digest.log (kb-digests/*.md are secondary)',
    },
    {
        "job": "registry-backup", "plist": "com.gwsemantic.registry-backup",
        "fire": (4, 23), "weekday": None,
        "artifact": str(Path(HOME / "Documents/ChatGPT/Google Workspace MCP",
                             "registry-backups/registry-snapshot-latest.json")),
        "check": "exported-at",
        "desc": "registry snapshot exported_at (UTC, compared in local date)",
    },
]


def run_date_for(fire_h: int, fire_m: int, weekday, now: dt.datetime) -> dt.date:
    """Date of the job's most recent scheduled run relative to `now`."""
    # weekly filtering: a Mon-only job checked on a non-scheduled day simply
    # looks back to its most recent scheduled date (handled by the caller's
    # day-walk); the current set is all-daily so this is future-proofing.
    d = now.date()
    if now.time() < dt.time(fire_h, fire_m):
        d -= dt.timedelta(days=1)
    if weekday is not None:
        # walk back to the most recent scheduled weekday
        # (launchd Weekday: 0/7=Sun..6=Sat -> python weekday: 0=Mon..6=Sun)
        py_target = (weekday % 7 + 6) % 7
        while d.weekday() != py_target:
            d -= dt.timedelta(days=1)
    return d


def check_exists(path: Path) -> tuple[bool, str]:
    if path.is_file() and path.stat().st_size >= 0:
        return True, f"exists ({path.stat().st_size} bytes)"
    return False, f"missing: {path}"


def check_exists_parse(path: Path, run_date: dt.date) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing: {path}"
    try:
        json.loads(path.read_text())
    except (json.JSONDecodeError, OSError) as e:
        return False, f"present but unparseable: {e}"
    return True, "exists and parses"


def check_mtime_date(path: Path, run_date: dt.date) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing: {path}"
    mdate = dt.datetime.fromtimestamp(path.stat().st_mtime).date()
    if mdate >= run_date:
        return True, f"mtime {mdate} >= run-date {run_date}"
    return False, f"stale: mtime {mdate} < run-date {run_date}"


def check_git_commit_date(repo: Path, run_date: dt.date) -> tuple[bool, str]:
    if not (repo / ".git").is_dir():
        return False, f"not a git repo: {repo}"
    try:
        out = subprocess.run(
            ["git", "-C", str(repo), "log", "-1", "--format=%cI"],
            capture_output=True, text=True, timeout=30, check=True,
        ).stdout.strip()
        last = dt.datetime.fromisoformat(out).astimezone().date()
    except Exception as e:  # noqa: BLE001
        return False, f"git inspect failed: {e}"
    if last >= run_date:
        return True, f"newest commit {last} >= run-date {run_date}"
    return False, f"stale: newest commit {last} < run-date {run_date}"


def check_digest_marker(path: Path, run_date: dt.date) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing: {path}"
    markers = re.findall(r'"date":\s*"(\d{4}-\d{2}-\d{2})"', path.read_text(errors="replace"))
    if not markers:
        return False, "no date marker block found in digest.log"
    last = dt.date.fromisoformat(markers[-1])
    if last >= run_date:
        return True, f"digest marker {last} >= run-date {run_date}"
    return False, f"stale: digest marker {last} < run-date {run_date}"


def check_exported_at(path: Path, run_date: dt.date) -> tuple[bool, str]:
    if not path.is_file():
        return False, f"missing: {path}"
    try:
        exported = json.loads(path.read_text()).get("exported_at", "")
        exp_local = dt.datetime.fromisoformat(exported.replace("Z", "+00:00")).astimezone()
    except Exception as e:  # noqa: BLE001
        return False, f"snapshot present but exported_at unreadable: {e}"
    if exp_local.date() >= run_date:
        return True, f"exported_at {exp_local.date()} (local) >= run-date {run_date}"
    return False, f"stale: exported_at {exp_local.date()} (local) < run-date {run_date}"


CHECKS = {
    "exists": lambda p, rd: check_exists(p),
    "exists-parse": check_exists_parse,
    "mtime-date": check_mtime_date,
    "git-commit-date": check_git_commit_date,
    "digest-date-marker": check_digest_marker,
    "exported-at": check_exported_at,
}


def load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(state: dict) -> None:
    STATE_FILE.parent.mkdir(parents=True, exist_ok=True)
    tmp = STATE_FILE.with_suffix(".tmp")
    tmp.write_text(json.dumps(state, indent=1))
    tmp.replace(STATE_FILE)


def append_receipt(row: dict) -> None:
    """Auxiliary ledger ONLY — never consulted by the escalation decision."""
    try:
        sys.path.insert(0, str(SCRIPTS))
        from atomic_io import atomic_append  # type: ignore
        atomic_append(RECEIPTS_LEDGER, row)
    except Exception as e:  # noqa: BLE001 — ledger is best-effort
        print(f"[gate] receipts ledger append failed (non-fatal): {e}", file=sys.stderr)


def bus_escalate(claim: str) -> bool:
    try:
        subprocess.run(
            [sys.executable, str(SCRIPTS / "bus_post.py"), "post",
             "--agent", AGENT, "--type", "finding",  # enforced schema; no 'escalation' type
             "--subject", SUBJECT, "--thread", SUBJECT,
             "--claim", claim],
            check=True, capture_output=True, timeout=60,
        )
        return True
    except Exception as e:  # noqa: BLE001
        print(f"[gate] bus post failed: {e}", file=sys.stderr)
        return False


def main() -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--no-bus", action="store_true", help="do not post escalations")
    ap.add_argument("--verify-config", action="store_true",
                    help="print the plist-verified schedule facts and exit")
    a = ap.parse_args()

    if a.verify_config:
        print(json.dumps([
            {"job": j["job"], "plist": j["plist"], "fire": f"{j['fire'][0]:02d}:{j['fire'][1]:02d}",
             "weekday": j["weekday"], "artifact": j["artifact"], "check": j["check"],
             "desc": j["desc"]} for j in JOBS], indent=2))
        return

    now = dt.datetime.now()
    state = load_state()
    results, stale_jobs = [], []

    for job in JOBS:
        run_date = run_date_for(*job["fire"], job["weekday"], now)
        rd = run_date.isoformat()
        art = Path(job["artifact"].format(run_date=rd))
        ok, why = CHECKS[job["check"]](art, run_date)
        verdict = {
            "job": job["job"], "run_date": rd, "fire": f"{job['fire'][0]:02d}:{job['fire'][1]:02d}",
            "artifact": str(art), "fresh": ok, "detail": why,
        }
        results.append(verdict)
        if ok:
            continue

        stale_jobs.append(verdict)
        reason = f"OUTPUT {verdict['detail']}"
        claim = (f"ESCALATION nightly-receipts-gate: job '{job['job']}' "
                 f"({job['plist']}, fire {verdict['fire']}) has no fresh output for "
                 f"run-date {rd} — {reason}. Expected artifact: {art}")
        already = state.get("escalated", {}).get(job["job"]) == rd
        posted = False
        if not a.no_bus and not already:
            posted = bus_escalate(claim)
            if posted:
                state.setdefault("escalated", {})[job["job"]] = rd
                save_state(state)
        verdict["bus_posted"] = posted
        verdict["bus_already_posted"] = already
        append_receipt({
            "ts": now.astimezone().isoformat(), "kind": "gate-run",
            "job": job["job"], "run_date": rd, "fresh": False, "detail": why,
        })

    for v in results:
        if v["fresh"]:
            append_receipt({
                "ts": now.astimezone().isoformat(), "kind": "gate-run",
                "job": v["job"], "run_date": v["run_date"], "fresh": True,
            })

    fresh_n = sum(1 for v in results if v["fresh"])
    summary = {
        "checked_at": now.astimezone().isoformat(),
        "fresh": fresh_n, "stale": len(results) - fresh_n,
        "verdicts": results,
    }

    if a.json:
        print(json.dumps(summary, indent=2))
    else:
        for v in results:
            mark = "GREEN" if v["fresh"] else "RED"
            extra = f" — {v['detail']}" if not v["fresh"] else f" — {v['detail']}"
            bus = ""
            if not v["fresh"] and not a.no_bus:
                bus = " (escalation posted)" if v.get("bus_posted") else \
                      " (already escalated this run-date)" if v.get("bus_already_posted") \
                      else " (bus post FAILED — see stderr)"
            print(f"{mark}  {v['job']:<15} run-date {v['run_date']}  {extra}{bus}")
        if stale_jobs:
            names = ", ".join(v["job"] for v in stale_jobs)
            print(f"MORNING GATE: {fresh_n}/{len(results)} fresh — STALE: {names}")
        else:
            print(f"MORNING GATE: all {len(results)} nightly outputs fresh — all clear.")
    sys.exit(0 if not stale_jobs else 1)


if __name__ == "__main__":
    main()
