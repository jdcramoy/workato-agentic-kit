#!/usr/bin/env python3
"""queue-append.py — the ONLY way agents append to a shared JSONL queue.

Agents hand-composing `echo '{...}'` is how triage/queue.jsonl got 3 corrupt
lines (2026-10-10: an LLM wrote the keys, then a bare nested object, plus a
doubled close brace — valid-looking shell, unparsable JSON). This helper takes
typed flags, builds valid JSON, and appends atomically through atomic_io.py
(flock + os.replace), so concurrent writers can't interleave or truncate.

Usage:
  queue-append.py --queue triage --slug kebab-slug --kind bugfix \
      --source workato-watchdog --title "one line" \
      [--work "the proposed fix"] [--evidence "job id / path"] \
      [--urgency high] [--points 2] [--jira KEY] [--status open]
  queue-append.py --queue harness-fix --slug ... --title ... --work ...

Queues: triage      -> knowledge/triage/queue.jsonl
        harness-fix -> knowledge/harness-fix/queue.jsonl

Dedupes on slug for re-FILED rows only (status=open, the default; returns
"already open/decided", exit 0, appends nothing) — the re-append-instead-of-
update drift seen on recipe-health-* slugs. Status-CHANGE rows
(--status fixed/resolved/...) always pass through: the ledger closes a slug
by appending the new status, last row wins.
"""
import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
QUEUES = {
    "triage": K / "triage" / "queue.jsonl",
    "harness-fix": K / "harness-fix" / "queue.jsonl",
}
sys.path.insert(0, str(K / "scripts"))
from atomic_io import atomic_append  # noqa: E402

KINDS = {"bugfix", "build", "playbook", "test", "hygiene"}
URGENCIES = {"high", "medium", "low", ""}


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def open_slugs(path):
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            r = json.loads(s)
        except json.JSONDecodeError:
            continue  # corrupt lines are the integrity probe's job, not ours
        if r.get("slug"):
            out[r["slug"]] = r.get("status")
    return out


def open_rows_by_jira(path):
    """Open rows grouped by uppercase Jira key: {key: [(slug, row), ...]}."""
    out = {}
    if not path.exists():
        return out
    for line in path.read_text(errors="replace").splitlines():
        s = line.strip()
        if not s:
            continue
        try:
            r = json.loads(s)
        except json.JSONDecodeError:
            continue
        if r.get("slug") and r.get("status") == "open" and r.get("jira"):
            out.setdefault(r["jira"].upper(), []).append((r["slug"], r))
    return out


def main():
    p = argparse.ArgumentParser(description="safe append to a shared JSONL queue")
    p.add_argument("--queue", required=True, choices=sorted(QUEUES))
    p.add_argument("--slug", required=True)
    p.add_argument("--title", required=True)
    p.add_argument("--kind", default="hygiene", choices=sorted(KINDS))
    p.add_argument("--source", required=True)
    p.add_argument("--work", default="")
    p.add_argument("--evidence", default="")
    p.add_argument("--urgency", default="")
    p.add_argument("--points", type=int)
    p.add_argument("--jira", default="")
    p.add_argument("--status", default="open")
    p.add_argument("--note", default="")
    a = p.parse_args()

    if a.urgency and a.urgency not in URGENCIES:
        print(f"error: urgency must be one of {sorted(URGENCIES)}", file=sys.stderr)
        return 2
    path = QUEUES[a.queue]
    slugs = open_slugs(path)
    if a.slug in slugs and a.status == "open":
        # Re-FILING an already-tracked slug is always deduped — that is the
        # whole point (2026-10-11: 49 decided findings re-filed overnight).
        # Re-raising needs materially new evidence -> file a NEW slug
        # (date-stamped, e.g. recipe-health-<id>-new-failures-20261012).
        # A status-CHANGE row (--status fixed/resolved/...) still passes
        # through: the queues are append-only ledgers where the last row per
        # slug wins, and blocking those broke the harness-fix close-out
        # (fleet job 2026-10-11).
        state = slugs[a.slug]
        label = "already decided" if state != "open" else "already open"
        print(f"{label}: {a.slug} ({state}) — deduped, no row appended; "
              f"materially new evidence files a NEW slug")
        return 0

    row = {
        "ts": now_iso(), "slug": a.slug, "kind": a.kind, "source": a.source,
        "title": a.title, "work": a.work, "evidence": a.evidence,
        "status": a.status,
    }
    if a.urgency:
        row["urgency"] = a.urgency
    if a.points is not None:
        row["points"] = a.points
    if a.jira:
        row["jira"] = a.jira
    if a.note:
        row["note"] = a.note

    path.parent.mkdir(parents=True, exist_ok=True)
    # Jira-key collision warning (2026-10-16: BTSUP-78227 reached 8 open slugs,
    # BTSUP-76729 7, BSYS-29519 6 — same ask rendered as many decision cards).
    # Not a block: materially different asks on one ticket are legal — but the
    # filing agent sees the warning and can supersede instead of duplicating.
    if a.jira and a.status == "open":
        for slug, r in open_rows_by_jira(path).get(a.jira.upper(), []):
            if slug != a.slug:
                print(f"WARNING: {a.jira.upper()} already has open row '{slug}' "
                      f"— consider superseding it instead of duplicating the ask",
                      file=sys.stderr)
    atomic_append(path, json.dumps(row))
    print(f"appended to {a.queue}: {a.slug}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
