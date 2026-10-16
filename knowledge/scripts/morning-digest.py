#!/usr/bin/env python3
"""morning-digest.py — SessionStart hook: serve Josh the harness decisions.

Prints a compact block ONLY when attention is needed:
  - dreamer proposals awaiting decision / ready to build
  - fleet timers late or overdue
Silent otherwise (zero noise for zero news). Target <0.5s.
"""
import json, os, subprocess, sys, time
from pathlib import Path

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, ".claude", "knowledge", "scripts")


def pipeline_counts():
    try:
        r = subprocess.run(["python3", os.path.join(SCRIPTS, "proposal-pipeline.py"), "--json"],
                           capture_output=True, text=True, timeout=10)
        return json.loads(r.stdout).get("counts", {})
    except Exception:
        return {}


def late_timers():
    """Overdue/late timers via the dashboard's own collector."""
    try:
        sys.path.insert(0, SCRIPTS)
        import brain_dashboard as bd
        return [t for t in bd.timers() if t["state"] in ("late", "overdue")]
    except Exception:
        return []


def owned_failures():
    """Failing owned Workato assets from the latest health sweep."""
    try:
        latest = json.load(open(os.path.join(SCRIPTS, "..", "workato-health", "health-latest.json")))
        return latest.get("failures", []), latest.get("ts", "")
    except Exception:
        return [], ""


def queue_hygiene():
    """Claims/queue/liveness sweep (P4 REAPER). Reuses claims-sweep-latest.json if
    fresher than 6h; otherwise shells claims-sweep.py --json (timeout 20s, fail-open:
    any error yields {} and the section prints nothing)."""
    latest = os.path.join(HOME, ".claude", "knowledge", "reports", "claims-sweep-latest.json")
    try:
        if time.time() - os.path.getmtime(latest) > 6 * 3600:
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "claims-sweep.py"), "--json"],
                           capture_output=True, text=True, timeout=20)
    except Exception:
        pass  # fail-open: stale cache below is better than nothing, silence better than noise
    try:
        return json.load(open(latest))
    except Exception:
        return {}


def main():
    c = pipeline_counts()
    lines = []
    np, na = c.get("proposed", 0), c.get("accepted", 0)
    if np or na:
        parts = []
        if np:
            parts.append(f"{np} awaiting your decision")
        if na:
            parts.append(f"{na} accepted, ready to build")
        lines.append(f"HARNESS PROPOSALS: {', '.join(parts)}. See: dashboard.html 'Proposal pipeline' "
                     f"section. Approve in one line, e.g.:")
        lines.append('  proposal-decide.py replay-gym accept "notes here"')
    fails, ts = owned_failures()
    if fails:
        fl = "; ".join(f'{f["id"]} {f["verdict"]} [{f["server"]}] {f.get("name","")[:40]}' for f in fails[:4])
        lines.append(f"OWNED ASSET FAILURES (sweep {ts[:16]}): {fl}. Triage: /triage or dashboard #owned")
    q = queue_hygiene()
    h = q.get("headline", {}) if isinstance(q, dict) else {}
    x, y = h.get("stale_claims", 0), h.get("possible_unfinished_prod_state", 0)
    z, n = h.get("needs_josh_over_7d", 0), h.get("silent_agents", 0)
    if x or y or z or n:
        lines.append(f"QUEUE HYGIENE: {x} stale claims ({y} flagged POSSIBLE UNFINISHED PROD STATE), "
                     f"{z} needs-josh >7d, {n} silent agents. Details: reports/claims-sweep-latest.json")
    late = late_timers()
    if late:
        names = ", ".join(f'{t["name"]} ({t["detail"]})' for t in late[:4])
        lines.append(f"HARNESS TIMERS LATE: {names}. Detail: dashboard.html #fleet")
    drops = {}
    drops_file = Path.home() / ".claude" / "knowledge" / "mission-control" / "dropped-sessions.jsonl"
    if drops_file.exists():
        import time as _t
        for l in open(drops_file):
            try:
                r = json.loads(l)
            except Exception:
                continue
            if _t.time() - float(r.get("ts", 0)) >= 48 * 3600:
                continue
            # the sweep re-appends the same sessions every startup — dedupe by
            # session_id so the banner counts SESSIONS, not sweep history
            drops[r.get("session_id") or f"anon-{len(drops)}"] = r
    if drops:
        lines.append(f"DROPPED SESSIONS (no closeout, last 48h): {len(drops)}. "
                     "Absorb before continuing that work:")
        for sid, r in list(drops.items())[:3]:
            # resolvable pointer: the transcript file under ~/.claude/projects,
            # not just "absorb from transcript" — the session_id in the ledger
            # is a truncated prefix, so glob it
            hits = sorted((Path.home() / ".claude" / "projects").glob(f"*/{sid}*.jsonl")) if sid and not sid.startswith("anon-") else []
            where = f" — transcript: {hits[0]}" if hits else " — no transcript found (state unrecoverable from files)"
            lines.append(f'  - "{r.get("last_prompt","")[:80]}" ({r.get("turns","?")} turns, '
                         f"{len(r.get('files_touched',[]))} files) [{sid}]{where}")
    if lines:
        print("\n".join(lines))


if __name__ == "__main__":
    main()
