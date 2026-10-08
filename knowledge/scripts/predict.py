#!/usr/bin/env python3
"""predict.py — prediction-error protocol for the harness (Predictive Processing).

The brain doesn't wait for input; it predicts and processes the error. The
harness analog: an agent records the EXPECTED signal before a consequential
action, compares after, and deviations spike to the bus as attention events.
Calibration emerges over time: per-agent, per-action-class prediction accuracy.

  predict.py open --agent X --action "wt recipes start 12345" --expect "running=true; jobs grow"
  predict.py check --id <id> --observed "running=true; +1 job" --verdict matched|deviated|failed
  predict.py stats [--agent X]
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
from collections import defaultdict
from pathlib import Path

STORE = Path.home() / ".claude/knowledge/dreams/predictions.jsonl"
BUS = Path.home() / ".claude/knowledge/dreams/bus"


def _append(path: Path, rec: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a") as f:
        f.write(json.dumps(rec, ensure_ascii=False) + "\n")


def _load() -> list[dict]:
    if not STORE.exists():
        return []
    return [json.loads(l) for l in STORE.read_text().splitlines() if l.strip()]


def open_prediction(agent: str, action: str, expect: str, stakes: str = "normal") -> dict:
    rec = {
        "id": f"pred-{dt.datetime.now().strftime('%Y%m%d-%H%M%S')}-{len(_load())}",
        "agent": agent,
        "action": action,
        "expect": expect,
        "stakes": stakes,
        "opened": dt.datetime.now().isoformat(timespec="seconds"),
        "closed": None,
        "verdict": None,
    }
    _append(STORE, rec)
    print(json.dumps(rec, indent=2))
    return rec


def check_prediction(pid: str, observed: str, verdict: str) -> dict:
    recs = _load()
    found = None
    for r in recs:
        if r["id"] == pid and r["closed"] is None:
            found = r
            break
    if not found:
        raise SystemExit(f"no open prediction {pid}")
    found["closed"] = dt.datetime.now().isoformat(timespec="seconds")
    found["observed"] = observed
    found["verdict"] = verdict
    STORE.write_text("".join(json.dumps(r, ensure_ascii=False) + "\n" for r in recs))
    if verdict in ("deviated", "failed"):
        # attention spike to the bus: the prediction error IS the signal
        _append(
            BUS / "prediction-errors.jsonl",
            {
                "ts": found["closed"],
                "agent": found["agent"],
                "type": "prediction_error",
                "summary": f"{verdict.upper()}: predicted [{found['expect'][:120]}] but got [{observed[:120]}]",
                "details": {"prediction_id": pid, "action": found["action"], "stakes": found["stakes"]},
            },
        )
        print(f"spike posted to bus (prediction-errors)")
    print(json.dumps(found, indent=2))
    return found


def stats(agent: str | None) -> dict:
    recs = [r for r in _load() if r.get("verdict")]
    if agent:
        recs = [r for r in recs if r["agent"] == agent]
    by_class: dict[str, dict] = defaultdict(lambda: {"matched": 0, "deviated": 0, "failed": 0})
    for r in recs:
        cls = r["action"].split()[0] if r["action"] else "?"
        by_class[cls][r["verdict"]] += 1
    out = {"total": len(recs), "by_action_class": {}}
    for cls, counts in by_class.items():
        n = sum(counts.values())
        out["by_action_class"][cls] = {**counts, "accuracy": round(counts["matched"] / n, 3)}
    overall_ok = sum(c["matched"] for c in by_class.values())
    out["overall_accuracy"] = round(overall_ok / len(recs), 3) if recs else None
    return out


def main() -> None:
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    o = sub.add_parser("open")
    o.add_argument("--agent", required=True)
    o.add_argument("--action", required=True)
    o.add_argument("--expect", required=True)
    o.add_argument("--stakes", default="normal", choices=["low", "normal", "high"])
    c = sub.add_parser("check")
    c.add_argument("--id", required=True)
    c.add_argument("--observed", required=True)
    c.add_argument("--verdict", required=True, choices=["matched", "deviated", "failed"])
    s = sub.add_parser("stats")
    s.add_argument("--agent", default=None)
    a = ap.parse_args()
    if a.cmd == "open":
        open_prediction(a.agent, a.action, a.expect, a.stakes)
    elif a.cmd == "check":
        check_prediction(a.id, a.observed, a.verdict)
    elif a.cmd == "stats":
        print(json.dumps(stats(a.agent), indent=2))


if __name__ == "__main__":
    main()
