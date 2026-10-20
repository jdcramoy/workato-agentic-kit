#!/usr/bin/env python3
"""fleet-config-receipts.py — fleet config receipts (bounded first move, DEV-side).

Implements the smallest-experiment slice of dream proposal
2026-10-16-gws-fleet-receipts.md: a read-only nightly snapshot of version
ground truth for the Google Workspace Semantic fleet (dev folder 35404884),
appended as receipt rows to a local JSONL ledger. Data-table storage is a
later phase — this is the evidence-gathering detector, deliberately decoupled
from the pusher-participation assumption the fatal dissent identified.

Ground truth: ONE `wt api get /api/recipes?folder_id=<id>&per_page=100` call
per run (josh-us DEV profile, read-only). The folder list embeds each recipe's
full `code` JSON and `version_no` — the same ground truth the versions
endpoint exposes — so no per-recipe fetches are needed (pattern reused from
workato-health.py / env-diff.py's wt-call discipline).

Receipt row schema (JSONL):
  {"ts": "<ISO-8601 Z>", "recipe_id": <int>, "recipe_name": <str>,
   "version_no": <int>, "trigger_block_hash": "sha256:<hex>", "step_count": <int>}

Behavior:
  - Idempotent: a recipe gets a new receipt row ONLY when it is new in the
    ledger or its (version_no, trigger_block_hash, step_count) changed. A run
    with zero deltas appends ZERO rows.
  - Diff-check (external-edit detection): any delta between a recipe's last
    receipt and the current fetch prints an ALERT line — config changed
    without this script being able to attribute a build-ledger reference.

Usage:
  python3 fleet-config-receipts.py [--folder 35404884] [--profile josh-us]
                                   [--ledger <path>] [--json] [--force]

--force writes a full snapshot row set regardless of deltas (baseline runs).
"""
import argparse
import datetime as dt
import hashlib
import json
import os
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_append  # noqa: E402

HOME = os.path.expanduser("~")
DEFAULT_LEDGER = os.path.join(
    HOME, ".claude/knowledge/garden-reports/fleet-config-receipts.jsonl"
)
WT_BIN = os.environ.get("WT_BIN", os.path.join(HOME, ".local/bin/wt"))


def wt_api(path, profile):
    cmd = [WT_BIN, "api", "--profile", profile, "get", path]
    r = subprocess.run(cmd, capture_output=True, text=True, timeout=60)
    out = r.stdout.strip()
    if r.returncode != 0 or not out.startswith("{"):
        raise RuntimeError(f"wt api get {path} failed: {(out or r.stderr)[:200]}")
    return json.loads(out)


def trigger_block(code_obj):
    """The trigger step is the code document root (number 0, keyword 'trigger')."""
    if isinstance(code_obj, dict) and code_obj.get("keyword") == "trigger":
        return code_obj
    first = code_obj.get("block", [None])[0] if isinstance(code_obj, dict) else None
    if isinstance(first, dict) and first.get("keyword") == "trigger":
        return first
    return None


def step_count(code_obj):
    """Count every step node (dict carrying number+keyword) in the block tree."""
    n = 0
    stack = [code_obj] if isinstance(code_obj, dict) else []
    while stack:
        node = stack.pop()
        if not isinstance(node, dict):
            continue
        if "keyword" in node and "number" in node:
            n += 1
        for v in node.values():
            if isinstance(v, list):
                stack.extend(x for x in v if isinstance(x, dict))
            elif isinstance(v, dict):
                stack.append(v)
    return n


def trigger_hash(trig):
    """SHA-256 of the trigger block EXCLUDING nested steps — the schedule config
    itself (input, dynamicPickListSelection, visible_config_fields, provider...).
    Canonicalized: sorted keys, separators stripped, so key order never
    masquerades as drift (the 358-row key-order false-positive class)."""
    if trig is None:
        return "sha256:none"
    cfg = {k: v for k, v in trig.items() if k != "block"}
    blob = json.dumps(cfg, sort_keys=True, separators=(",", ":"))
    return "sha256:" + hashlib.sha256(blob.encode("utf-8")).hexdigest()


def load_last_receipts(ledger):
    last = {}
    if not os.path.exists(ledger):
        return last
    with open(ledger, "r", encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except ValueError:
                continue  # torn tail line — atomic_append prevents, but skip loudly-proof
            last[row.get("recipe_id")] = row
    return last


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--folder", default="35404884")
    ap.add_argument("--profile", default="josh-us")
    ap.add_argument("--ledger", default=DEFAULT_LEDGER)
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--force", action="store_true",
                    help="write a full snapshot regardless of deltas (baseline runs)")
    args = ap.parse_args()

    folder_rows = wt_api(f"/api/recipes?folder_id={args.folder}&per_page=100",
                         args.profile)
    items = (folder_rows.get("items") if isinstance(folder_rows, dict)
             else folder_rows) or []
    ts = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    last = load_last_receipts(args.ledger)
    new_rows, alerts, unchanged = [], [], 0

    for it in items:
        rid = it.get("id")
        try:
            code_obj = json.loads(it["code"]) if it.get("code") else {}
        except (ValueError, TypeError):
            code_obj = {}
        trig = trigger_block(code_obj)
        row = {
            "ts": ts,
            "recipe_id": rid,
            "recipe_name": it.get("name"),
            "version_no": it.get("version_no"),
            "trigger_block_hash": trigger_hash(trig),
            "step_count": step_count(code_obj),
        }
        prev = last.get(rid)
        if prev:
            delta_keys = [k for k in ("version_no", "trigger_block_hash", "step_count")
                          if prev.get(k) != row[k]]
            if delta_keys:
                alerts.append(
                    f"ALERT {rid} {row['recipe_name']}: delta in {', '.join(delta_keys)} — "
                    f"v{prev.get('version_no')}/{prev.get('trigger_block_hash')[:19]}.../"
                    f"{prev.get('step_count')} steps -> v{row['version_no']}/"
                    f"{row['trigger_block_hash'][:19]}.../{row['step_count']} steps "
                    f"(no manifest reference — external-edit class)"
                )
                new_rows.append(row)
            elif args.force:
                new_rows.append(row)  # full snapshot for trend history
            else:
                unchanged += 1
        else:
            new_rows.append(row)  # first receipt for this recipe (baseline)

    if new_rows:
        os.makedirs(os.path.dirname(os.path.abspath(args.ledger)), exist_ok=True)
        atomic_append(args.ledger, new_rows)

    if args.json:
        print(json.dumps({
            "ts": ts, "ledger": args.ledger,
            "recipes_seen": len(items),
            "rows_appended": len(new_rows),
            "unchanged_skipped": unchanged,
            "alerts": [a for a in alerts],
        }, indent=1))
    else:
        print(f"fleet-config-receipts {ts}: {len(items)} recipes seen, "
              f"{len(new_rows)} receipt row(s) appended, {unchanged} unchanged (skipped)")
        for a in alerts:
            print(a)
        if not alerts:
            print("diff-check: no deltas — fleet config matches last receipts")
    return 0


if __name__ == "__main__":
    sys.exit(main())
