#!/usr/bin/env python3
"""harness-health.py — the watchdog for the harness itself.

workato-health watches the Workato estate; gym asserts 5 invariants. Nothing
watches the fleet and the ledgers as a system. This does: every nightly job is
checked for liveness, every outcome ledger for freshness, every queue for
self-dedup, and a few known tooling defects are probed directly. Findings are
appended to harness-fix/queue.jsonl (deduped) where decision-inbox picks them
up — safe ones drain without Josh, unsafe ones surface.

Zero-LLM. Output: ~/.claude/knowledge/garden-reports/harness-health-<date>.md
"""
import datetime as dt
import json
import os
import plistlib
import re
import subprocess
import sys
from pathlib import Path
from atomic_io import atomic_append

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
G = K / "garden-reports"
SCRIPTS = K / "scripts"
LA = HOME / "Library" / "LaunchAgents"
HARNESS_FIX = K / "harness-fix" / "queue.jsonl"
HEARTBEAT = G / "heartbeat.jsonl"

# job name -> heartbeat aliases (a job is "seen" if any alias matches a
# heartbeat job name). Canonical name = the FLEET job (plist suffix); the
# second spellings are the agent/mechanical identities the same job writes
# under (deduped 2026-10-11, proposal #2 — the ledger held dual identities:
# gardener vs brain-gardener, dreamer vs harness-dreamer, watchdog vs
# workato-watchdog, backup vs harness-backup, gym vs replay-gym, brief vs
# morning-brief, jira-triage vs jira-triage-fleet).
# NOT merged on live evidence: "health" (workato-health.py, hourly, heartbeats
# as "workato-health") and "harness-health" (run-job.sh job) are TWO DISTINCT
# jobs — binding "health" to its true heartbeat name instead of merging the
# pair removes the "-health" suffix cross-masking. Known residual: the
# endswith matcher still lets "dreamer" claim "project-dreamer" rows (a real
# second job); fixing that needs the matcher, not the alias table.
ALIASES = {
    "dreamer": ["dreamer", "harness-dreamer"],
    "project-dreamer": ["project-dreamer"],
    "health": ["workato-health"],
    "harness-health": ["harness-health"],
    "watchdog": ["watchdog", "workato-watchdog"],
    "architect": ["architect"],
    "ops-autopsy": ["autopsy"], "ops-visibility": ["ops-visibility"],
    "jira-triage": ["jira-triage", "jira-triage-fleet"],
    "brief": ["brief", "morning-brief"], "loadout": ["loadout"],
    "minutes": ["minutes"], "corpus": ["corpus"], "docs-watch": ["docs-watch"],
    "backup": ["backup", "harness-backup"],
    "gym": ["gym", "replay-gym"], "healer": ["healer"],
    "cortex": ["cortex"], "gardener": ["gardener", "brain-gardener"],
}
STALE_HOURS = 26.0

LEDGERS = {
    "build-ledger": K / "build-ledger.jsonl",
    "triage-outcomes": G / "triage-outcomes.jsonl",
    "proposal-outcomes": G / "proposal-outcomes.jsonl",
    "value-ledger": G / "value-ledger.jsonl",
}


def now_utc():
    return dt.datetime.now(dt.timezone.utc)


def now_iso():
    return now_utc().strftime("%Y-%m-%dT%H:%M:%SZ")


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


def parse_ts(s):
    # honor explicit offsets: ledger rows mix Z and -04:00 (and skip-heartbeat
    # rows carry a local offset by design) — the old str(s)[:19] UTC assumption
    # read every -04:00 row as 4h older than it is (2026-10-11, proposal #2)
    t = str(s).strip()
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    try:
        d = dt.datetime.fromisoformat(t)
    except ValueError:
        return None
    if d.tzinfo is None:  # naive ts (older rows): treat as UTC, as before
        d = d.replace(tzinfo=dt.timezone.utc)
    return d


def heartbeat_last():
    last = {}
    for r in read_jsonl(HEARTBEAT):
        j = r.get("job")
        t = parse_ts(r.get("ts", ""))
        if j and t and (j not in last or t > last[j]):
            last[j] = t
    return last


def plist_cadence_hours(d):
    """Per-job staleness threshold from its OWN schedule, not a flat 26h.
    Returns (threshold_hours, note) — a Monday-only job is not stale at 26h,
    it is stale at 168+26h; an every-2h job is stale at 5h."""
    # 1.5x cadence, Josh-approved 2026-10-11: the old 24h+26h slack let a dead
    # daily job render "(ok)" for over two days (verified 2026-10-11 incident)
    sci = d.get("StartCalendarInterval")
    iv = d.get("StartInterval")
    if sci:
        entries = sci if isinstance(sci, list) else [sci]
        if any("Weekday" in e for e in entries):
            return 168.0 * 1.5, "weekly (Weekday pin)"
        return 24.0 * 1.5, "daily"
    if iv:
        return max((iv / 3600.0) * 1.5, 1.0), f"every {iv // 3600 or 1}h (StartInterval)"
    return None, "no schedule key"


def check_fleet(findings):
    hb = heartbeat_last()
    now = now_utc()
    jobs = []
    for p in sorted(LA.glob("com.josh.fleet.*.plist")):
        try:
            d = plistlib.loads(p.read_bytes())
        except Exception as e:  # noqa: BLE001
            findings.append({"slug": f"harness-health-plist-parse-{p.stem}", "kind": "hygiene",
                             "title": f"fleet plist unparseable: {p.name}",
                             "evidence": str(e)[:160], "work": "fix the plist (plutil -lint)",
                             "source": "harness-health"})
            continue
        label = d.get("Label", p.stem)
        suffix = label.replace("com.josh.fleet.", "")
        cadence, note = plist_cadence_hours(d)
        threshold = cadence if cadence else STALE_HOURS
        # install time: a job younger than its own cadence+slack cannot have
        # missed a fire yet — "never heartbeated" is PENDING, not a defect
        try:
            st = p.stat()
            installed = dt.datetime.fromtimestamp(getattr(st, "st_birthtime", st.st_ctime), dt.timezone.utc)
        except OSError:
            installed = now
        pending = (now - installed).total_seconds() / 3600.0 < threshold
        aliases = ALIASES.get(suffix, [suffix])
        seen = None
        for j, t in hb.items():
            # boundary-aware: "health" must not match "harness-health" and
            # vice versa (2026-10-11 cross-masking fix)
            if any(j == a or j.endswith("-" + a) or j.startswith(a + "-") for a in aliases):
                if seen is None or t > seen:
                    seen = t
        if seen is None:
            if pending:
                jobs.append((suffix, f"pending first tick ({note})"))
            else:
                jobs.append((suffix, None))
                findings.append({"slug": f"harness-health-no-heartbeat-{suffix}", "kind": "hygiene",
                                 "title": f"fleet job '{suffix}' never writes heartbeat.jsonl",
                                 "evidence": f"{label} ({note}); installed {installed:%m-%d %H:%M}, "
                                             f"no heartbeat row ever, first fire long past",
                                 "work": "add a heartbeat write to the job's script",
                                 "source": "harness-health"})
        else:
            age = (now - seen).total_seconds() / 3600.0
            if age > threshold:
                jobs.append((suffix, age))
                findings.append({"slug": f"harness-health-stale-{suffix}", "kind": "hygiene",
                                 "title": f"fleet job '{suffix}' stale: last heartbeat {age:.0f}h ago",
                                 "evidence": f"threshold {threshold:.0f}h ({note}); last {seen.isoformat()}",
                                 "work": "check the launchd job ran (log in ~/.local/state/fleet)",
                                 "source": "harness-health"})
            else:
                jobs.append((suffix, f"{age:.1f}h ago (ok, {note})"))
    return jobs



# Consumer-side completion markers (2026-10-14, graduated from incubating
# proposal fleet-job-completion-marker in the contrarian-amended form: the
# validator never trusts producer self-report — it checks the freshness of
# the artifact each job's CONSUMERS read. rc=0 with a stale artifact is its
# own failure class (frontier-nightly sat green for months that way).
ARTIFACTS = {
    # fleet job suffix -> (glob relative to K, max age in hours)
    "health":         ("workato-health/sweeps/*.jsonl", 3),
    "decision-inbox": ("now/decision-inbox.md", 30),
    "dreamer":        ("dreams/2*.md", 30),
    "project-dreamer": ("dreams/project/*.md", 30),
}


def check_artifacts(findings):
    checked = 0
    for job, (rel, max_h) in ARTIFACTS.items():
        paths = sorted(K.glob(rel), key=lambda p: p.stat().st_mtime)
        if not paths:
            findings.append({"slug": f"harness-health-artifact-missing-{job}", "kind": "hygiene",
                             "title": f"fleet job '{job}': consumer artifact missing ({rel})",
                             "evidence": f"no file matches knowledge/{rel}",
                             "work": "fix the job or its artifact path in ARTIFACTS",
                             "source": "harness-health"})
            checked += 1
            continue
        newest = paths[-1]
        age = now_utc() - dt.datetime.fromtimestamp(newest.stat().st_mtime, dt.timezone.utc)
        age_h = age.total_seconds() / 3600.0
        checked += 1
        if age_h > max_h:
            findings.append({"slug": f"harness-health-silent-noop-{job}", "kind": "hygiene",
                             "title": f"fleet job '{job}': SILENT NO-OP class - heartbeat may be green "
                                      f"but its consumer artifact is {age_h:.0f}h stale",
                             "evidence": f"knowledge/{rel} newest = {newest.name} (window {max_h}h); "
                                         f"rc-based validation alone cannot see this",
                             "work": "run the job manually and diff its output; check ~/.local/state/fleet logs",
                             "source": "harness-health"})
    unmapped = 0
    for p_ in LA.glob("com.josh.fleet.*.plist"):
        suffix = p_.stem.replace("com.josh.fleet.", "")
        if suffix not in ARTIFACTS:
            unmapped += 1
    return checked, unmapped


def check_ledgers(findings):
    out = []
    now = now_utc()
    for name, p in LEDGERS.items():
        if not p.exists():
            out.append((name, "missing"))
            findings.append({"slug": f"harness-health-ledger-missing-{name}", "kind": "hygiene",
                             "title": f"ledger '{name}' does not exist",
                             "evidence": str(p), "work": "create it or confirm it was retired",
                             "source": "harness-health"})
            continue
        age = (now - dt.datetime.fromtimestamp(p.stat().st_mtime, dt.timezone.utc)).total_seconds() / 86400.0
        out.append((name, f"{age:.1f}d"))
        if name != "value-ledger" and age > 14:
            findings.append({"slug": f"harness-health-ledger-stale-{name}", "kind": "hygiene",
                             "title": f"ledger '{name}' not written in {age:.0f}d",
                             "evidence": f"{p} mtime {age:.1f}d old",
                             "work": "check the writer; a silent write-path is a blind spot",
                             "source": "harness-health"})
    return out


def check_dedup(findings):
    slugs = [r.get("slug") for r in read_jsonl(K / "triage" / "queue.jsonl")
             if r.get("status") == "open" and r.get("slug")]
    dupes = sorted({s for s in slugs if slugs.count(s) > 1})
    if dupes:
        findings.append({"slug": "harness-health-triage-dupe-slugs", "kind": "hygiene",
                         "title": f"triage queue has {len(dupes)} duplicate open slug(s)",
                         "evidence": ", ".join(dupes[:8]), "work": "dedupe-on-append in the writers",
                         "source": "harness-health"})
    return dupes


# Queue <-> outcomes parity (added 2026-10-11 after the 2026-10-10 silent
# triage-queue reversion: ~49 decided rows flipped back to open and ~45
# outcome rows deleted by a `git checkout -f` discarding uncommitted state).
# Invariant: a final-state queue row (built/rejected/filed/accepted/deferred —
# all terminal or near-terminal per triage-decide.py's transition map) must
# carry a matching final outcome row, and every outcome slug must still be
# final-state in the queue. Divergence > 0 means one ledger moved without the
# other — a reversion or selective loss in progress.
FINAL_STATES = {"built", "rejected", "filed", "accepted", "deferred"}


def check_queue_outcome_parity(findings):
    queue = list(read_jsonl(K / "triage" / "queue.jsonl"))
    outcomes = list(read_jsonl(G / "triage-outcomes.jsonl"))

    q_status = {}
    for r in queue:
        s = r.get("slug")
        if s:
            q_status.setdefault(s, set()).add(r.get("status"))

    # last occurrence wins: a slug may be re-decided (defer -> accept -> build)
    last_action = {}
    for r in outcomes:
        s, a = r.get("slug"), r.get("action")
        if s and a:
            last_action[s] = a

    bad = []

    # family-aware outcome lookup: outcome rows may carry a truncated slug
    # (bsys-29457) whose queue row spells it out (bsys-29457-health-sweep-
    # hygiene) — 2026-10-11: exact-only matching false-positived on these.
    def family_action(slug):
        if slug in last_action:
            return last_action[slug]
        for osl, a in last_action.items():
            if slug in osl or osl in slug:
                return a
        return None

    # direction 1: final-state queue row without a matching final outcome.
    # filed-with-jira -> built is a legitimate progression (story filed, then
    # built; the built outcome row may be absent from older recorder runs).
    for r in queue:
        s, st = r.get("slug"), r.get("status")
        if not s:
            continue  # malformed row (writer skipped queue-append); don't crash the nightly
        oa = family_action(s)
        if s and st in FINAL_STATES and oa != st \
                and not (st == "built" and oa == "filed"):
            # duplicate-seed tolerance: one slug may hold rows decided BOTH
            # ways (fan-out history: original built, superseded re-reports
            # rejected). If the outcome action matches ANY final row of the
            # slug family, this row's divergence is history, not reversion.
            if oa and any(oa in q_status.get(q, set())
                          for q in list(q_status) + [s]
                          if q == s or s in q or q in s):
                continue
            bad.append((s, f"queue={st}",
                        f"outcomes={oa or 'MISSING'}"))
    # direction 2: outcome slug whose queue row is no longer in that final
    # state (reverted to open, or deleted outright). Slug-family match first:
    # outcome rows may carry a truncated slug (bsys-29457) whose queue row
    # spells it out (bsys-29457-health-sweep-hygiene) — that is a match, not
    # a parity break (2026-10-11: 3 false positives on exact match).
    def family_final(slug):
        for q, states in q_status.items():
            if q == slug or slug in q or q in slug:
                if any(t in FINAL_STATES for t in states):
                    return True
        return False

    for s, a in sorted(last_action.items()):
        if a in FINAL_STATES and a not in q_status.get(s, set()) \
                and not any(t in FINAL_STATES for t in q_status.get(s, set())) \
                and not family_final(s):
            where = sorted(q_status.get(s, set())) if s in q_status else "MISSING"
            bad.append((s, f"outcomes={a}", f"queue={where}"))

    # dedupe by slug (a slug can trip both directions)
    seen = {}
    for s, q_side, o_side in bad:
        seen.setdefault(s, (q_side, o_side))
    if seen:
        findings.append({
            "slug": "harness-health-triage-parity", "kind": "hygiene",
            "title": f"triage queue/outcomes parity broken: {len(seen)} rows — "
                     f"possible reversion",
            "evidence": "; ".join(f"{s} ({q} vs {o})"
                                  for s, (q, o) in sorted(seen.items())[:8]),
            "work": "reconcile triage/queue.jsonl vs "
                    "garden-reports/triage-outcomes.jsonl — restore the "
                    "reverted side from git history or the nightly backup; "
                    "never hand-rebuild one ledger without the other",
            "source": "harness-health",
        })
    return sorted(seen.items())


# Append-only ledgers: a corrupt (truncated / interleaved) line means a writer
# bypassed atomic_io. Checked nightly so corruption is caught, not discovered.
INTEGRITY_LEDGERS = {
    "build-ledger": K / "build-ledger.jsonl",
    "value-ledger": G / "value-ledger.jsonl",
    "triage-outcomes": G / "triage-outcomes.jsonl",
    "proposal-outcomes": G / "proposal-outcomes.jsonl",
    "triage-queue": K / "triage" / "queue.jsonl",
    "harness-fix-queue": K / "harness-fix" / "queue.jsonl",
    "heartbeat": HEARTBEAT,
}


def check_ledger_integrity(findings):
    out = []
    for name, p in INTEGRITY_LEDGERS.items():
        if not p.exists():
            continue
        bad = 0
        total = 0
        for i, line in enumerate(p.read_text(errors="replace").splitlines(), 1):
            s = line.strip()
            total = i
            if not s:
                continue
            try:
                json.loads(s)
            except json.JSONDecodeError:
                bad += 1
        out.append((name, f"{total} lines, {bad} corrupt"))
        if bad:
            findings.append({"slug": f"harness-health-jsonl-corrupt-{name}", "kind": "hygiene",
                             "title": f"ledger '{name}' has {bad} corrupt line(s) of {total}",
                             "evidence": str(p),
                             "work": "a writer bypassed atomic_io.py — re-serialize the "
                                     "line and fix the writer to atomic_append",
                             "source": "harness-health"})
    return out


# The ONE runner. The 2026-10-10 consolidation made the kit repo the single
# source of truth: ~/.local/bin/fleet is a symlink to it. A plist pointing at
# anything else resolves its job defs from a diverged copy — the trap that
# made the cortex --add-dir fix silently not apply.
CANONICAL_RUNNER = Path("/Users/YOUR-USER/Documents/agentic-workato-kit/bin/fleet/run-job.sh")
# jobs that run their script directly instead of via run-job.sh
ALLOWED_DIRECT = {"health", "ops-visibility"}


# Ledger-shrink alarm: the Oct-11 heartbeat wipe (1402 rows -> 448, a writer
# replaced the file mid-day) fired nothing because every check here looks at
# the CURRENT run only. Persist each ledger's line count and compare across
# runs; any decrease is an alarm. Baseline is the last-seen count (not a
# high-water mark) so a legitimate rotation resets the alarm instead of
# pinning it — shrink events are caught one run after they happen.
SHRINK_STATE = G / "harness-health-ledger-counts.json"


def check_ledger_shrink(findings):
    out = []
    last = {}
    if SHRINK_STATE.exists():
        try:
            last = json.loads(SHRINK_STATE.read_text())
        except json.JSONDecodeError:
            last = {}  # unreadable state = no baseline, rebuild it
    counts = {}
    for name, p in INTEGRITY_LEDGERS.items():
        if not p.exists():
            continue
        counts[name] = sum(1 for ln in p.read_text(errors="replace").splitlines() if ln.strip())
        prev = last.get(name)
        if prev is not None and counts[name] < prev:
            findings.append({"slug": f"harness-health-ledger-shrank-{name}", "kind": "hygiene",
                             "title": f"ledger '{name}' SHRANK {prev} -> {counts[name]} lines",
                             "evidence": f"{p}: last run {prev} lines, now {counts[name]}",
                             "work": "a writer replaced/truncated an append-only ledger — "
                                     "recover from git (committed rows) and fix the writer "
                                     "to atomic_io append",
                             "source": "harness-health"})
        out.append((name, f"{prev} -> {counts[name]}" if prev is not None else f"{counts[name]} (baseline)"))
    if counts:
        tmp = SHRINK_STATE.with_suffix(".tmp")
        tmp.write_text(json.dumps(counts, indent=1))
        tmp.replace(SHRINK_STATE)
    return out


def check_runner_paths(findings):
    out = []
    canon = os.path.realpath(CANONICAL_RUNNER)
    for p in sorted(LA.glob("com.josh.fleet.*.plist")):
        suffix = p.stem.replace("com.josh.fleet.", "")
        try:
            d = plistlib.loads(p.read_bytes())
        except Exception:  # noqa: BLE001 — already flagged by check_fleet
            out.append((suffix, "plist unparseable"))
            continue
        args = d.get("ProgramArguments", [])
        runner = next((a for a in args if a.endswith("run-job.sh")), None)
        if runner is None:
            if suffix in ALLOWED_DIRECT:
                out.append((suffix, "direct-script (allowed)"))
            else:
                out.append((suffix, "no runner"))
                findings.append({
                    "slug": f"harness-health-no-runner-{suffix}", "kind": "hygiene",
                    "title": f"fleet job '{suffix}' runs no run-job.sh runner",
                    "evidence": f"ProgramArguments: {args}",
                    "work": "either route it through run-job.sh (for the "
                            "heartbeat contract) or allowlist it in "
                            "harness-health.py ALLOWED_DIRECT",
                    "source": "harness-health"})
            continue
        if os.path.realpath(runner) == canon:
            out.append((suffix, "canonical"))
        else:
            out.append((suffix, f"non-canonical: {runner}"))
            findings.append({
                "slug": f"harness-health-noncanonical-runner-{suffix}", "kind": "hygiene",
                "title": f"fleet job '{suffix}' points at a non-canonical runner",
                "evidence": f"{runner} resolves to {os.path.realpath(runner)}, not {canon}",
                "work": "re-point the plist at the canonical runner (the kit "
                        "repo); a diverged copy silently ignores prompt fixes",
                "source": "harness-health"})
    return out


# Fleet job-file parity: two real copies exist (canonical knowledge tree per
# the run-job.sh DEPLOY CHECKLIST, and the kit repo — ~/.local/bin/fleet is a
# symlink to it, per the 2026-10-10 consolidation). Divergence between them is
# the dual-copy drift class that bit twice (partial-deploy 2026-10-10, stale
# jira-triage prompt 2026-10-12). Checked as name-set + content hash.
CANONICAL_FLEET = K / "config" / "fleet"
DEPLOYED_FLEET = HOME / "Documents" / "agentic-workato-kit" / "bin" / "fleet"


def check_jobfile_parity(findings):
    out = []
    canon = CANONICAL_FLEET / "jobs"
    dep = DEPLOYED_FLEET / "jobs"
    if not (canon.is_dir() and dep.is_dir()):
        return [("jobfile-parity", "a fleet jobs dir is missing — skipped")]
    canon_files = {p.name for p in canon.iterdir() if p.is_file()}
    dep_files = {p.name for p in dep.iterdir() if p.is_file()}
    # .bak files are point-in-time backups (fusion/recovery snapshots), not
    # live job defs — they exist in exactly one copy by design and never
    # deploy, so they must not count as drift (17 false rows 2026-10-14).
    canon_files = {n for n in canon_files if ".bak" not in n}
    dep_files = {n for n in dep_files if ".bak" not in n}
    n = 0
    for name in sorted(canon_files - dep_files):
        findings.append({"slug": f"harness-health-jobfile-drift-{name}", "kind": "hygiene",
                         "title": f"fleet job file '{name}' in canonical but missing in kit repo",
                         "evidence": f"{canon}/{name} vs {dep}",
                         "work": "copy the file kit-ward (deploy) or canonical-ward (retire) — "
                                 "one of the two copies is stale",
                         "source": "harness-health"})
        out.append((name, "missing in kit repo"))
        n += 1
    for name in sorted(dep_files - canon_files):
        findings.append({"slug": f"harness-health-jobfile-drift-{name}", "kind": "hygiene",
                         "title": f"fleet job file '{name}' in kit repo but missing in canonical",
                         "evidence": f"{dep}/{name} vs {canon}",
                         "work": "copy the file canonical-ward (kit repo is the live source of "
                                 "truth via the ~/.local/bin/fleet symlink)",
                         "source": "harness-health"})
        out.append((name, "missing in canonical"))
        n += 1
    for name in sorted(canon_files & dep_files):
        if (canon / name).read_bytes() != (dep / name).read_bytes():
            findings.append({"slug": f"harness-health-jobfile-drift-{name}", "kind": "hygiene",
                             "title": f"fleet job file '{name}' diverged between canonical and kit repo",
                             "evidence": f"{canon}/{name} != {dep}/{name}",
                             "work": "diff the two copies, keep the corrected one, copy it over the other",
                             "source": "harness-health"})
            out.append((name, "content diverged"))
            n += 1
    if not n:
        out.append(("*", f"OK ({len(canon_files)} files identical)"))
    return out


def check_known_defects(findings):
    res = []
    # proposal-pipeline file-gate: run it; if it says "no dream report" but a
    # report file for a recent date exists, the gate is lying.
    try:
        r = subprocess.run(["python3", str(SCRIPTS / "proposal-pipeline.py")],
                           capture_output=True, text=True, timeout=60)
        if "no dream report" in r.stdout.lower():
            recent = sorted((K / "dreams").glob("2026-*.md"))
            if recent:
                res.append(("proposal-pipeline-file-gate", "FALSE"))
                findings.append({"slug": "proposal-pipeline-file-gate", "kind": "hygiene",
                                 "title": "proposal-pipeline.py file-gate false negative",
                                 "evidence": f"pipeline says no dream report; {recent[-1].name} exists",
                                 "work": "fix dream-report date/path matching in proposal-pipeline.py",
                                 "source": "harness-health"})
            else:
                res.append(("proposal-pipeline-file-gate", "ok"))
        else:
            res.append(("proposal-pipeline-file-gate", "ok"))
    except Exception as e:  # noqa: BLE001
        res.append(("proposal-pipeline-file-gate", f"probe error: {e}"))
    # dispatch --add-dir present in fleet cortex job? The dispatch command
    # lives in the cortex job prompt (the plist just calls run-job.sh), so
    # probe the prompt's nohup claude line, not the plist blob.
    try:
        prompt = None
        for base in (HOME / ".local" / "bin" / "fleet" / "jobs",
                     HOME / "Documents" / "agentic-workato-kit" / "bin" / "fleet" / "jobs"):
            p = base / "cortex.prompt"
            if p.exists():
                prompt = p.read_text(errors="replace")
                break
        line = ""
        for ln in (prompt or "").splitlines():
            if "nohup claude" in ln:
                line = ln
                break
        if "--add-dir" in line and "--add-dir \"$HOME/.claude/knowledge\"" in line:
            res.append(("cortex-dispatch-add-dir", "present"))
        elif line:
            res.append(("cortex-dispatch-add-dir", "MISSING"))
            findings.append({"slug": "cortex-dispatch-add-dir-fix", "kind": "hygiene",
                             "title": "fleet cortex dispatch lacks --add-dir ~/.claude/knowledge",
                             "evidence": "cortex prompt's nohup claude dispatch line has no --add-dir",
                             "work": "add --add-dir \"$HOME/.claude/knowledge\" to the dispatch line in the cortex prompt",
                             "source": "harness-health"})
        else:
            res.append(("cortex-dispatch-add-dir", "no dispatch line found in cortex prompt"))
    except Exception as e:  # noqa: BLE001
        res.append(("cortex-dispatch-add-dir", f"probe error: {e}"))
    return res


# A slug closed fixed/resolved suppresses re-flagging of the same
# harness-health finding for this long, so verdicts like "Monday-only job,
# first tick pending" (whose 'never' condition persists by design) don't
# ping-pong open/closed every run. Genuine recurrence still re-surfaces
# after the window.
FIX_COOLDOWN_H = 96.0


def append_findings(findings):
    HARNESS_FIX.parent.mkdir(parents=True, exist_ok=True)
    open_rows = {}
    row_ts = {}
    for r in read_jsonl(HARNESS_FIX):
        if r.get("slug"):
            open_rows[r["slug"]] = r.get("status")
            t = parse_ts(r.get("ts", ""))
            if t:
                row_ts[r["slug"]] = t
    current = {it["slug"] for it in findings}
    n = 0
    new_rows = []
    for it in findings:
        st = open_rows.get(it["slug"])
        if st == "open":
            continue
        if (st in ("fixed", "resolved") and it["slug"].startswith("harness-health-")):
            last = row_ts.get(it["slug"])
            if last and (now_utc() - last).total_seconds() < FIX_COOLDOWN_H * 3600:
                continue
        new_rows.append({"ts": now_iso(), **it, "status": "open"})
        open_rows[it["slug"]] = "open"
        n += 1
    # self-resolve: an open finding this script owns that did NOT recur this
    # run is cleared — a transient (cold-start) flag must not live forever.
    for slug, st in list(open_rows.items()):
        if st == "open" and slug.startswith("harness-health-") and slug not in current:
            new_rows.append({"ts": now_iso(), "slug": slug,
                             "status": "resolved",
                             "note": "condition cleared on re-check"})
    if new_rows:
        atomic_append(HARNESS_FIX, new_rows)
    return n


def main():
    import argparse
    # --help/-h gate (2026-10-16): bare main() wrote a heartbeat row (and
    # report/queue rows on findings) even on a naive --help.
    ap = argparse.ArgumentParser(
        description="harness-health sweep (bare run = the real sweep)")
    ap.parse_args()
    findings = []
    jobs = check_fleet(findings)
    runners = check_runner_paths(findings)
    jobfiles = check_jobfile_parity(findings)
    ledgers = check_ledgers(findings)
    integrity = check_ledger_integrity(findings)
    shrink = check_ledger_shrink(findings)
    dupes = check_dedup(findings)
    parity = check_queue_outcome_parity(findings)
    defects = check_known_defects(findings)
    art_checked, art_unmapped = check_artifacts(findings)
    new = append_findings(findings)

    day = now_utc().strftime("%Y-%m-%d")
    rep = G / f"harness-health-{day}.md"
    G.mkdir(parents=True, exist_ok=True)
    L = [f"# Harness health — {now_iso()}", ""]
    L.append(f"**{len(findings)} finding(s), {new} newly filed** to harness-fix/queue.jsonl.")
    L.append(f"Consumer-artifact freshness: {art_checked} job(s) checked, {art_unmapped} scheduled job(s) "
             f"still have no artifact mapping (add them to ARTIFACTS as their consumer outputs are identified).")
    L.append("")
    L.append("## Fleet liveness (last heartbeat age)")
    L.append("")
    L.append("| job | last heartbeat |")
    L.append("|---|---|")
    for name, age in jobs:
        L.append(f"| {name} | {'never (past first fire)' if age is None else age} |")
    L.append("")
    L.append("## Ledger integrity (corrupt JSONL lines)")
    L.append("")
    L.append("| ledger | state |")
    L.append("|---|---|")
    for name, state in integrity:
        L.append(f"| {name} | {state} |")
    L.append("")
    L.append("## Ledger line counts vs last run (shrink alarm)")
    L.append("")
    L.append("| ledger | lines |")
    L.append("|---|---|")
    for name, state in shrink:
        L.append(f"| {name} | {state} |")
    L.append("")
    L.append("## Ledger freshness")
    L.append("")
    L.append("| ledger | age |")
    L.append("|---|---|")
    for name, age in ledgers:
        L.append(f"| {name} | {age} |")
    L.append("")
    L.append("## Runner paths (canonical = the kit repo)")
    L.append("")
    L.append("| job | runner |")
    L.append("|---|---|")
    for name, status in runners:
        L.append(f"| {name} | {status} |")
    L.append("")
    L.append(f"## Queue dedup: {'OK' if not dupes else f'{len(dupes)} duplicate open slug(s): ' + ', '.join(dupes[:8])}")
    L.append("")
    L.append(f"## Queue/outcomes parity: {'OK' if not parity else f'BROKEN — {len(parity)} row(s)'}")
    L.append("")
    if parity:
        for s, (q_side, o_side) in parity[:10]:
            L.append(f"- {s}: {q_side} vs {o_side}")
    L.append("")
    L.append("## Fleet job-file parity (canonical vs kit repo)")
    L.append("")
    for name, status in jobfiles:
        L.append(f"- {name}: {status}")
    L.append("")
    L.append("## Known-defect probes")
    L.append("")
    for name, status in defects:
        L.append(f"- {name}: **{status}**")
    L.append("")
    if findings:
        L.append("## Findings this run")
        L.append("")
        for it in findings:
            L.append(f"- {it['title']}  (`{it['slug']}`)")
    rep.write_text("\n".join(L) + "\n")

    atomic_append(HEARTBEAT, {"ts": now_iso(), "job": "harness-health"})

    print(f"harness-health: {len(findings)} findings, {new} new -> {rep}")
    for it in findings:
        print(f"  - {it['slug']}: {it['title']}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
