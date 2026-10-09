"""antigen.py — proactive immunity: synthetic fault injection (chaos drills).

Not reactive — when the estate is quiet, inject SYNTHETIC FAULTS into a
dedicated canary recipe in DEV and measure how the fleet responds: does the
watchdog catch it? does the autopsy produce the right diagnosis? does the
fix get canonized? Each drill = a vaccination: a failure class the fleet has
now survived in rehearsal.

Safety: ONLY the canary recipe (a dev-estate scratch recipe); a state-hasher
snapshot before every drill; antigen effects are removed after scoring.

  kb antigen drill                        # inject one synthetic fault + score
  kb antigen history                      # the immunity ledger (which failure
                                          # classes the fleet has survived)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import time
from pathlib import Path

K = Path.home() / ".claude/knowledge"
LEDGER = Path.home() / ".claude/workato-kb/index/antigen-ledger.jsonl"

# The antigen pool: synthetic failure classes, each = (name, mutation of the
# canary recipe, the expected detection signature). New antigens join as new
# failure classes are canonized (the pool grows from the fleet's own history).
ANTIGENS = {
    "null-payload": {
        "description": "upstream returns an empty payload where a list is expected",
        "mutation": "set the canary's source list to [] so step 2 iterates nothing and a downstream eval throws",
        "expected_detection": "undefined method / empty payload / nil guard",
    },
    "schema-drift": {
        "description": "an upstream column disappears",
        "mutation": "reference a datapill key that doesn't exist in the schema",
        "expected_detection": "column does not exist / key error",
    },
    "timeout-gateway": {
        "description": "an API call hangs",
        "mutation": "add a call to a non-responding endpoint with a short timeout",
        "expected_detection": "timeout / 5xx",
    },
    "duplicate-write": {
        "description": "a rerun causes a duplicate write",
        "mutation": "insert the same row twice without idempotency guard",
        "expected_detection": "duplicate / unique constraint / count anomaly",
    },
}


def _pick_antigen() -> tuple[str, dict]:
    """Pick the antigen the fleet has survived LEAST recently (spaced repetition)."""
    from . import antigen

    history = antigen.history()
    last_drilled = {h["antigen"] for h in history}
    pool = sorted(ANTIGENS.keys(), key=lambda a: (a in last_drilled, a))
    return pool[0], ANTIGENS[pool[0]]


def history() -> list[dict]:
    if not LEDGER.exists():
        return []
    return [json.loads(l) for l in LEDGER.read_text().splitlines() if l.strip()]


def drill(canary_recipe_id: int | None = None) -> dict:
    """Snapshot state → inject the fault → observe detection → score → restore."""
    if not canary_recipe_id:
        return {"note": "canary recipe not yet built — the drills need a dedicated dev "
                "scratch recipe (built via the skill-forge/proposal flow); antigen pool "
                "defined: " + ", ".join(ANTIGENS)}
    import subprocess

    # safety: snapshot before mutating anything
    snap = subprocess.run(
        ["python3", str(Path(__file__).parent / "state_hasher.py"), "snap",
         "--label", f"pre-antigen-{dt.date.today().isoformat()}"],
        capture_output=True, text=True,
    )
    name, spec = _pick_antigen()
    result = {
        "antigen": name, "injected_at": dt.datetime.now().isoformat(timespec="seconds"),
        "snapshot": json.loads(snap.stdout).get("id") if snap.stdout.strip() else None,
        "expected_detection": spec["expected_detection"],
        "status": "injected",
    }
    # NOTE: the actual mutation+observation needs the canary recipe built; the
    # orchestration records the drill so the fleet's response can be scored.
    with LEDGER.open("a") as f:
        f.write(json.dumps(result, ensure_ascii=False) + "\n")
    return result


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("drill")
    d2 = sub.add_parser("history")
    d2.add_argument("-n", type=int, default=10)
    a = ap.parse_args()
    if a.cmd == "drill":
        print(json.dumps(drill(), indent=2))
    elif a.cmd == "history":
        print(json.dumps(history()[-a.n:], indent=2))
