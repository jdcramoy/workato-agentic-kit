#!/usr/bin/env python3
"""watchdog-liveness.py — visible alarm when the fleet watchdog goes dark.

Born from triage watchdog-dark-3-nights-cwd-fail (Josh, 2026-10-22): the
watchdog died cwd-fail on 10-20 AND emitted nothing on 10-21, and nothing
paged — a dark watchdog passed silently for two nights because every other
liveness surface keys on the watchdog's own report existing.

Signal contract (two channels, both fire when dark):
  1. Bus post to thread "watchdog-liveness" via bus_post.py (the standard
     bus writer; the /today skill and cortex read the bus live).
  2. One alarm row appended to garden-reports/heartbeat.jsonl with
     job "watchdog-liveness-ALARM" — today_brief.py reads the last 60
     heartbeat rows into the morning brief's machine-health block, so the
     next morning brief carries the alarm line verbatim.

Check logic: the watchdog's scheduled fire is 23:13 local. If more than
GRACE_HOURS (default 4) have elapsed since the most recent scheduled fire
and the newest ~/.claude/knowledge/watchdog-reports/<date>.md predates that
fire's run-date, the watchdog is DARK -> alarm. Before grace elapses the
run is a no-op status line, so manual/testing runs never false-page.
Idempotent per run-date: one alarm max per night (state file).
"""
import json
import subprocess
import sys
from datetime import datetime, timedelta
from pathlib import Path

HOME = Path.home()
REPORTS = HOME / ".claude" / "knowledge" / "watchdog-reports"
STATE = HOME / ".claude" / "knowledge" / "reports" / "watchdog-liveness-state.json"
HEARTBEAT = HOME / ".claude" / "knowledge" / "garden-reports" / "heartbeat.jsonl"
ATOMIC_IO = HOME / ".claude" / "knowledge" / "scripts" / "atomic_io.py"
BUS_POST = HOME / ".claude" / "knowledge" / "scripts" / "bus_post.py"
THREAD = "watchdog-liveness"

FIRE_HOUR, FIRE_MIN = 23, 13  # com.josh.fleet.watchdog StartCalendarInterval
GRACE_HOURS = 4.0             # hours after the fire before "dark" is declared


def main():
    now = datetime.now()

    # most recent scheduled fire (23:13 local)
    fire = now.replace(hour=FIRE_HOUR, minute=FIRE_MIN, second=0, microsecond=0)
    if now < fire:
        fire -= timedelta(days=1)
    hours_since_fire = (now - fire).total_seconds() / 3600.0

    reports = sorted(REPORTS.glob("????-??-??.md"))
    newest = reports[-1] if reports else None
    newest_date = newest.stem if newest else None

    if hours_since_fire < GRACE_HOURS:
        print(f"OK (grace window, {hours_since_fire:.1f}h since fire): newest report {newest_date or 'none'}")
        return 0

    if newest_date and newest_date >= fire.strftime("%Y-%m-%d"):
        print(f"OK: watchdog report for run-date {fire:%Y-%m-%d} present ({newest.name})")
        return 0

    dark_reason = (
        f"no watchdog report for run-date {fire:%Y-%m-%d} "
        f"{hours_since_fire:.1f}h after the 23:13 fire "
        f"(grace {GRACE_HOURS:g}h; newest report: {newest_date or 'none'})"
    )

    # Idempotency: one alarm per run-date.
    state = {}
    if STATE.exists():
        try:
            state = json.loads(STATE.read_text())
        except (ValueError, OSError):
            state = {}
    if state.get("last_alarm_date") == fire.strftime("%Y-%m-%d"):
        print(f"ALREADY-PAGED: {dark_reason}; alarm already posted for {fire:%Y-%m-%d}")
        return 0

    # Channel 1: standard bus writer -> thread watchdog-liveness
    claim = (
        f"ALARM watchdog-liveness: {dark_reason}. Watchdog is DARK — estate "
        f"health unmonitored tonight. Check ~/.local/state/fleet/watchdog.log "
        f"and launchctl print gui/$(id -u)/com.josh.fleet.watchdog."
    )
    r = subprocess.run(
        [sys.executable, str(BUS_POST), "post",
         "--agent", "watchdog-liveness",
         "--type", "finding",
         "--subject", "watchdog-liveness",
         "--stance", "action",
         "--claim", claim,
         "--thread", THREAD],
        capture_output=True, text=True,
    )
    bus_ok = r.returncode == 0

    # Channel 2: alarm row in the heartbeat ledger (morning-brief input)
    row = {
        "ts": now.isoformat(),
        "job": "watchdog-liveness-ALARM",
        "status": "dark",
        "detail": dark_reason,
    }
    hb = subprocess.run(
        [sys.executable, str(ATOMIC_IO), str(HEARTBEAT)],
        input=json.dumps(row), capture_output=True, text=True,
    )
    hb_ok = hb.returncode == 0

    if state.get("last_alarm_date") != fire.strftime("%Y-%m-%d"):
        state["last_alarm_date"] = fire.strftime("%Y-%m-%d")
        state["last_alarm_ts"] = now.isoformat()
        state["last_alarm_detail"] = dark_reason
        STATE.parent.mkdir(parents=True, exist_ok=True)
        STATE.write_text(json.dumps(state, indent=1))

    print(f"ALARM (bus={'ok' if bus_ok else 'FAIL'} heartbeat={'ok' if hb_ok else 'FAIL'}): {dark_reason}")
    return 0 if (bus_ok and hb_ok) else 1


if __name__ == "__main__":
    sys.exit(main())
