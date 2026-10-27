#!/usr/bin/env python3
"""mood.py — the harness's neuromodulation register (one broadcast state file).

Brains shift global state with neuromodulators; the fleet shifts with mood.json.
Writers: the watchdog (P1 spikes arousal), the dreamer (nightly decay toward
baseline), anyone Josh directs. Readers: every agent's config-first step and
(eventually) hooks.

  mood.py                       # current state (decay applied on read)
  mood.py set arousal 0.9 --by watchdog --reason "P1: connector outage"
  mood.py decay                 # step back toward baseline (run nightly)

Fields (0..1): arousal (adrenaline: verification up, speed down),
exploration (dopamine: dreaming/vision budget), risk_tolerance (low = tighter
gates), verification_depth (acetylcholine: attention to evidence).
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import re
import subprocess
from pathlib import Path

MOOD = Path.home() / ".claude/knowledge/dreams/mood.json"
BASELINE = {
    "arousal": 0.3,
    "exploration": 0.6,
    "risk_tolerance": 0.5,
    "verification_depth": 0.5,
}
HALF_LIFE_H = 24.0  # mood halves toward baseline per day

# Reason hygiene (2026-10-26, triage mood-register-stale-reason-decay): the
# register once held a stale incident reason 5+ hours (cited sweeper 83291436
# fail-loop while live state was stopped-clean). Two guards, both in the decay
# pass, both fail-open (a broken probe must never wedge the register):
#   1. LIVE PROBE — if the reason cites Workato recipe IDs, probe recent job
#      outcomes; when the cited incident no longer holds (all probed recipes
#      healthy or gone), the reason is rewritten, never silently deleted.
#   2. STALENESS TTL — an incident reason older than REASON_TTL_H that the
#      probe could NOT confirm still holds is expired.
REASON_TTL_H = 6.0        # incident reason TTL (hours) without live confirmation
PROBE_TIMEOUT_S = 20      # per wt subprocess call
PROBE_MAX_RECIPES = 2     # bounded probes per decay cycle
PROBE_RECENT_JOBS = 5     # recent job window that decides "healthy"
BASELINE_REASON_MARKERS = (
    "baseline", "nightly refresh", "periodic nightly refresh", "decay-pass",
    "reason-cleared", "reason-expired",
)


def _read() -> dict:
    if not MOOD.exists():
        return {**BASELINE, "reason": "baseline", "set_by": "init", "set_at": dt.datetime.now().isoformat(timespec="seconds")}
    return json.loads(MOOD.read_text())


def _decayed(m: dict) -> dict:
    """Exponential decay toward baseline since set_at."""
    try:
        set_at = dt.datetime.fromisoformat(m["set_at"])
    except (KeyError, ValueError):
        return m
    hours = (dt.datetime.now() - set_at).total_seconds() / 3600
    factor = 0.5 ** (hours / HALF_LIFE_H)
    out = dict(m)
    for k, base in BASELINE.items():
        v = m.get(k, base)
        out[k] = round(base + (v - base) * factor, 3)
    out["hours_since_set"] = round(hours, 1)
    return out


def set_field(field: str, value: float, by: str, reason: str) -> dict:
    if field not in BASELINE:
        raise SystemExit(f"unknown field {field}; fields: {list(BASELINE)}")
    m = _decayed(_read())
    m[field] = max(0.0, min(1.0, value))
    m["reason"] = reason
    m["set_by"] = by
    m["set_at"] = dt.datetime.now().isoformat(timespec="seconds")
    # coupling: arousal spike tightens gates automatically
    if field == "arousal" and value > 0.7:
        m["verification_depth"] = max(m["verification_depth"], value)
        m["exploration"] = min(m["exploration"], 0.3)
        m["risk_tolerance"] = min(m["risk_tolerance"], 0.2)
    MOOD.parent.mkdir(parents=True, exist_ok=True)
    MOOD.write_text(json.dumps(m, indent=2))
    return m


def _is_incident_reason(m: dict) -> bool:
    reason = str(m.get("reason", "") or "")
    if not reason or reason.strip().lower() == "baseline":
        return False
    low = reason.lower()
    return not any(marker in low for marker in BASELINE_REASON_MARKERS)


def _extract_recipe_ids(reason: str) -> list[str]:
    """Recipe IDs cited in a reason: 7-9 digit numbers (excludes years, counts)."""
    seen, out = set(), []
    for tok in re.findall(r"\b(\d{7,9})\b", reason):
        if tok not in seen:
            seen.add(tok)
            out.append(tok)
    return out[:PROBE_MAX_RECIPES]


def _recipe_healthy(rid: str):
    """Read-only live probe: None of the recent jobs in error = healthy.

    Returns True (healthy), False (still failing), None (probe failed /
    inconclusive / recipe missing -> treated as inconclusive for TTL, cleared
    only via TTL, never on a guess). Fail-open on any wt/tooling error.
    """
    try:
        r = subprocess.run(
            ["/usr/bin/env", "wt", "jobs", "list", rid],
            capture_output=True, text=True, timeout=PROBE_TIMEOUT_S,
        )
        if r.returncode != 0:
            return None
        d = json.loads(r.stdout)
        items = (d.get("items") or [])[:PROBE_RECENT_JOBS]
        if not items:
            return None  # no job evidence either way: inconclusive
        return not any(item.get("is_error") for item in items)
    except (subprocess.TimeoutExpired, OSError, ValueError):
        return None


def _reason_hygiene(m: dict) -> dict:
    """Rewrite/clear the reason when it no longer holds; else leave it."""
    if not _is_incident_reason(m):
        return m
    reason = str(m.get("reason", ""))
    try:
        set_at = dt.datetime.fromisoformat(m["set_at"])
        age_h = (dt.datetime.now() - set_at).total_seconds() / 3600
    except (KeyError, ValueError):
        return m  # unparseable anchor: leave the row alone
    rids = _extract_recipe_ids(reason)
    verdicts = {rid: _recipe_healthy(rid) for rid in rids} if rids else {}
    if verdicts:
        if any(v is False for v in verdicts.values()):
            m["reason_verified_at"] = dt.datetime.now().isoformat(timespec="seconds")
            m["reason_probe"] = verdicts
            return m  # incident still live: keep the reason, stamp the probe
        if all(v is True for v in verdicts.values()):
            m["reason"] = ("reason-cleared (live probe %s healthy %s): %s"
                           % (",".join(verdicts),
                              dt.datetime.now().strftime("%Y-%m-%dT%H:%M:%S"),
                              reason[:160]))
            m["reason_probe"] = verdicts
            return m
    # no probeable IDs, probes inconclusive, or recipe missing: TTL decides
    if age_h >= REASON_TTL_H:
        m["reason"] = ("reason-expired (TTL %.0fh, probe %s): %s"
                       % (REASON_TTL_H,
                          "confirmed" if any(v is False for v in verdicts.values())
                          else "inconclusive",
                          reason[:160]))
    return m


def decay() -> dict:
    m = _decayed(_read())
    m = _reason_hygiene(m)
    m["set_at"] = dt.datetime.now().isoformat(timespec="seconds")
    m["set_by"] = "decay-pass"
    MOOD.write_text(json.dumps(m, indent=2))
    return m


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd")
    s = sub.add_parser("set")
    s.add_argument("field")
    s.add_argument("value", type=float)
    s.add_argument("--by", required=True)
    s.add_argument("--reason", required=True)
    sub.add_parser("decay")
    a = ap.parse_args()
    if a.cmd == "set":
        print(json.dumps(set_field(a.field, a.value, a.by, a.reason), indent=2))
    elif a.cmd == "decay":
        print(json.dumps(decay(), indent=2))
    else:
        print(json.dumps(_decayed(_read()), indent=2))
