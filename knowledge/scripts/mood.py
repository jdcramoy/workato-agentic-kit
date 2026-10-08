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
from pathlib import Path

MOOD = Path.home() / ".claude/knowledge/dreams/mood.json"
BASELINE = {
    "arousal": 0.3,
    "exploration": 0.6,
    "risk_tolerance": 0.5,
    "verification_depth": 0.5,
}
HALF_LIFE_H = 24.0  # mood halves toward baseline per day


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


def decay() -> dict:
    m = _decayed(_read())
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
