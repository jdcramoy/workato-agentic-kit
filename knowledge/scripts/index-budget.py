#!/usr/bin/env python3
"""index-budget.py — the session-start INDEX.md budget gate (proposal #5).

INDEX.md is the one file loaded at every session start; its cost is paid
every session whether or not the lines are relevant. This gate word/byte-
counts EVERY INDEX.md line, joins the usage-ledger read count for INDEX.md,
and emits the over-budget shortlist:

  >400 bytes/line  HARD FLAG  (shrink via the librarian branch lane)
  >200 bytes/line  warning

Report-only — it never edits INDEX.md. Zero-LLM.
Output: garden-reports/index-budget-<date>.md (atomic_write).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from atomic_io import atomic_write  # noqa: E402

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude/knowledge"
INDEX = K / "INDEX.md"
USAGE = K / "garden-reports" / "usage-ledger.jsonl"

HARD_BYTES = 400
WARN_BYTES = 200


def parse_iso(ts):
    if not ts:
        return None
    try:
        parsed = dt.datetime.fromisoformat(str(ts).replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=dt.timezone.utc)


def index_reads(days):
    """Read events for INDEX.md inside the window. The usage ledger logs
    INDEX.md reads under kind 'index-read' (knowledge files under
    'knowledge-read') — count both."""
    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=days)
    n = 0
    try:
        for line in USAGE.read_text().splitlines():
            if "index-read" not in line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                continue
            if row.get("kind") not in ("index-read", "knowledge-read"):
                continue
            if os.path.basename(str(row.get("target", ""))).lower() != "index.md":
                continue
            ts = parse_iso(row.get("ts", ""))
            if ts and ts >= cutoff:
                n += 1
    except FileNotFoundError:
        pass
    return n


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--hard", type=int, default=HARD_BYTES)
    ap.add_argument("--warn", type=int, default=WARN_BYTES)
    ap.add_argument("--read-window-days", type=int, default=7)
    args = ap.parse_args()

    lines = INDEX.read_text(errors="ignore").splitlines()
    reads = index_reads(args.read_window_days)
    total_bytes = len(INDEX.read_bytes())

    rows = []
    for i, text in enumerate(lines, 1):
        b = len(text.encode())
        if not text.strip():
            continue
        rows.append({
            "line": i,
            "bytes": b,
            "words": len(text.split()),
            "chars": len(text),
            "target": None,
            "class": ("HARD" if b > args.hard else
                      "warn" if b > args.warn else "ok"),
        })
        import re
        m = re.search(r"\]\(([^)]+)\)", text)
        if m:
            rows[-1]["target"] = m.group(1)

    over = [r for r in rows if r["class"] in ("HARD", "warn")]
    over.sort(key=lambda r: r["bytes"], reverse=True)
    hard_n = sum(1 for r in over if r["class"] == "HARD")

    today = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%d")
    out = []
    out.append(f"# INDEX budget gate — {today}")
    out.append("")
    out.append(f"INDEX.md: {total_bytes:,} bytes total · {len(rows)} non-blank lines · "
               f"{reads} knowledge-read events in the last {args.read_window_days}d "
               f"(paid every session start). Budget: {args.warn}B warning / "
               f"{args.hard}B hard per line.")
    out.append("")
    out.append(f"## Over-budget shortlist ({hard_n} hard, {len(over) - hard_n} warn)")
    out.append("")
    out.append("| line | bytes | x-hard | words | target | class |")
    out.append("|---|---|---|---|---|---|")
    for r in over:
        mult = f"{r['bytes'] / args.hard:.1f}x"
        out.append(f"| {r['line']} | {r['bytes']:,} | {mult} | {r['words']:,} | "
                   f"{r['target'] or '—'} | {r['class']} |")
    if not over:
        out.append("(none — INDEX is inside budget)")
    out.append("")
    out.append("## Row one (largest over-budget line)")
    out.append("")
    if over:
        r = over[0]
        out.append(f"Line {r['line']} ({r['target']}): {r['bytes']:,} bytes, "
                   f"{r['words']:,} words — {r['bytes'] / args.hard:.1f}x the hard budget. "
                   f"Shrink via the librarian branch lane (demote-never-delete: "
                   f"move history to the file, keep the routing line).")
    else:
        out.append("(none)")
    out.append("")
    out.append("*Report-only gate. It never edits INDEX.md; shrink work goes "
               "through the librarian branch lane per proposal #5.*")

    dest = K / "garden-reports" / f"index-budget-{today}.md"
    atomic_write(dest, "\n".join(out) + "\n")
    print(f"wrote {dest}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
