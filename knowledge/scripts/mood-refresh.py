#!/usr/bin/env python3
"""mood-refresh.py — periodic refresh of the mood register's set_at anchor.

Born 2026-10-22 (triage mood-register-stale-baseline): mood.json's set_at
froze at 2026-10-13T23:48 and readers only stayed honest because mood.py
decays toward baseline on read. Every writer/reader path was one-shot or
conditional; nothing refreshed the register.

This runs NIGHTLY from the harness-health job (23:20 local, launchd
com.josh.fleet.harness-health). It reads the CURRENT effective posture (the
decay-on-read values every consumer actually sees) and persists them through
mood.py's set path — set_by "nightly-refresh" — so the register is re-anchored
on real current posture data, never a fake constant. Idempotent and safe to
run any time.
"""

import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import mood  # noqa: E402


def main():
    current = mood._decayed(mood._read())  # what every reader sees right now
    reason = ("periodic nightly refresh — re-anchor set_at on the current "
              "decayed posture (triage mood-register-stale-baseline)")
    for field in mood.BASELINE:
        value = max(0.0, min(1.0, float(current.get(field,
                                                    mood.BASELINE[field]))))
        mood.set_field(field, value, by="nightly-refresh", reason=reason)
    out = mood._decayed(mood._read())
    out["refreshed_fields"] = list(mood.BASELINE)
    print(json.dumps(out, indent=2))


if __name__ == "__main__":
    main()
