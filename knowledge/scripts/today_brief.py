#!/usr/bin/env python3
"""today_brief.py — the chief-of-staff data stage (the /today skill orchestrates).

Pre-computes everything scriptable about Josh's day so the /today skill can
assemble a ranked agenda with work PRE-STAGED:

  - the proposal queue (needs-decision + accepted-not-built)
  - the triage queue (discovered work, by urgency)
  - last night's machine health (heartbeats, gym, watchdog P1s)
  - the dreamer's verdict + calibration card
  - Jira attention items (assigned/new-comment) — via JQL at runtime (MCP)
  - calendar + Slack DMs — MCP tools at runtime (headless can't)

  today_brief.py            # the scriptable stage -> stdout JSON
"""

from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path

K = Path.home() / ".claude/knowledge"


def _tail_jsonl(path: Path, n: int = 12) -> list[dict]:
    if not path.exists():
        return []
    lines = path.read_text().splitlines()[-n:]
    out = []
    for l in lines:
        try:
            out.append(json.loads(l))
        except json.JSONDecodeError:
            pass
    return out


def _pipeline() -> str:
    r = subprocess.run(
        ["python3", str(K / "scripts/proposal-pipeline.py")], capture_output=True, text=True
    )
    return r.stdout.strip()


def _triage(n: int = 8) -> list[dict]:
    q = K / "triage/queue.jsonl"
    if not q.exists():
        return []
    items = _tail_jsonl(q, 40)
    return [i for i in items if i.get("status", "open") == "open"][-n:]


def build() -> dict:
    # machine health: heartbeats in the last 24h by job
    import datetime as dt

    beats = _tail_jsonl(K / "garden-reports/heartbeat.jsonl", 60)
    cutoff = (dt.datetime.now() - dt.timedelta(hours=24)).isoformat()
    last_24 = {}
    for b in beats:
        if str(b.get("ts", "")) >= cutoff:
            last_24[b.get("job", "?")] = str(b.get("ts", ""))[:16]
    # newest dream + entropy + calibration
    dreams = sorted((K / "dreams").glob("2*.md"))
    entropy = K / "dreams/entropy-report.json"
    cal = sorted((K / "dreams/calibration").glob("*.md"))
    return {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "machine_health": {
            "heartbeats_24h": last_24,
            "missing_jobs_note": "compare against the schedule table; a silent job is the headline",
        },
        "proposal_pipeline": _pipeline(),
        "triage_open": _triage(),
        "latest_dream": str(dreams[-1]) if dreams else None,
        "entropy_report": json.loads(entropy.read_text()) if entropy.exists() else None,
        "calibration_card": str(cal[-1]) if cal else None,
        "mcp_runtime": ["calendar+Slack+Jira are gathered live by the /today skill via MCP tools"],
    }


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    ap.add_argument("--pretty", action="store_true")
    a = ap.parse_args()
    out = build()
    print(json.dumps(out, indent=2 if a.pretty else None))
