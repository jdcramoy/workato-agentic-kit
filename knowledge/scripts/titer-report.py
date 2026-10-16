#!/usr/bin/env python3
"""titer-report.py — immune-tolerance / titer review (proposal #10, folded ECO3).

Joins the regression canon (knowledge/regression-canon/canon.jsonl) against
docs-watch environment deltas (garden-reports/platform-delta.jsonl, kind
"changed") and reports canon failure classes whose environment may have moved
under them. Report-ONLY: no retirement logic, ever. Retirement decisions
belong to the canon collector + Josh.

KNOWN STRUCTURE GAPS (measured, not assumed — see the report's gaps section):
the canon has NO last_fired, NO tier (advisory vs enforced), NO subsystem
field. This script uses `kind` as the failure-class key and max(`found`) per
class as a LAST-FIRED PROXY — but `found` is the DISCOVERY date, not the last
occurrence, so real fire counts are unknown. The gaps are reported verbatim
rather than papered over with invented fields.

Zero-LLM. Output: garden-reports/titer-<date>.md (atomic_write).
"""
from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import re
import sys
from collections import defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))
from atomic_io import atomic_write  # noqa: E402

HOME = Path(os.path.expanduser("~"))
K = HOME / ".claude" / "knowledge"
CANON = K / "regression-canon" / "canon.jsonl"
DELTA = K / "garden-reports" / "platform-delta.jsonl"

UNFIRED_DAYS = 90  # proposal #10 threshold
STOPWORDS = set("""the a an and or of to in on for with by from at is are was
were this that it its as be been into over under via per not no new changes
change added excerpt window function style display var if else return true
false null http https www com md txt json""".split())


def parse_date(s):
    try:
        return dt.date.fromisoformat(str(s)[:10])
    except ValueError:
        return None


def load_jsonl(path):
    rows = []
    try:
        for line in path.read_text().splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                continue
    except FileNotFoundError:
        pass
    return rows


def tokens(text):
    return {t for t in re.findall(r"[a-z][a-z0-9_-]{3,}", text.lower())
            if t not in STOPWORDS}


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--unfired-days", type=int, default=UNFIRED_DAYS)
    args = ap.parse_args()
    today = dt.date.today()

    canon = load_jsonl(CANON)
    deltas = [r for r in load_jsonl(DELTA) if r.get("kind") == "changed"]

    # failure-class key = canon kind; last_seen = max(found) per class
    classes: dict[str, dict] = {}
    for row in canon:
        kind = str(row.get("kind", "?"))
        c = classes.setdefault(kind, {
            "n": 0, "open": 0, "last_seen": None, "signatures": set(),
            "text": "", "recipes": set(),
        })
        c["n"] += 1
        if row.get("status") == "open":
            c["open"] += 1
        d = parse_date(row.get("found", ""))
        if d and (c["last_seen"] is None or d > c["last_seen"]):
            c["last_seen"] = d
        c["signatures"].add(str(row.get("signature", "")))
        if row.get("recipe_id"):
            c["recipes"].add(row["recipe_id"])
        c["text"] += " " + " ".join(str(row.get(f, "")) for f in
                                    ("signature", "kind", "line"))

    # docs deltas: tokenized environment-change evidence
    delta_tokens: dict[str, set] = {}
    for d in deltas:
        blob = " ".join(str(d.get(f, "")) for f in
                        ("url", "label", "added_excerpt"))
        delta_tokens[f"{d.get('ts')}|{d.get('url', '')}"] = tokens(blob)

    # join: token overlap between class text and each delta
    rows_out = []
    for kind, c in sorted(classes.items()):
        age = (today - c["last_seen"]).days if c["last_seen"] else None
        ctokens = tokens(c["text"])
        hits = []
        for dkey, dtoks in delta_tokens.items():
            overlap = ctokens & dtoks
            # ignore tiny generic overlaps; 2+ distinct content tokens = a hit
            if len(overlap) >= 2:
                hits.append((dkey, sorted(overlap)[:6]))
        rows_out.append({
            "class": kind,
            "n": c["n"], "open": c["open"],
            "last_seen": c["last_seen"].isoformat() if c["last_seen"] else None,
            "days_since_last_seen": age,
            "unfired_ge_90d": age is not None and age >= args.unfired_days,
            "docs_delta_hits": hits,
        })

    unfired_w_delta = [r for r in rows_out
                       if r["unfired_ge_90d"] and r["docs_delta_hits"]]

    date_s = today.isoformat()
    out = []
    out.append(f"# Titer review (canon x docs-watch) — {date_s}")
    out.append("")
    out.append(f"Canon classes: {len(classes)} over {len(canon)} rows · "
               f"docs-watch changed deltas: {len(deltas)}. Report-only — "
               f"no retirement logic runs here (proposal #10: retire "
               f"advisory-tier rules only on environment delta, never on "
               f"incident-absence, and retirement decisions are Josh's).")
    out.append("")

    out.append("## Canon structure gaps (exactly what the join cannot do)")
    out.append("")
    out.append("The canon file (regression-canon/canon.jsonl) does NOT carry:")
    out.append("")
    out.append("1. `last_fired` — `found` is the DISCOVERY date, not the last "
               "occurrence; a class that fired yesterday after a 90d silence "
               "looks identical to one discovered 90d ago and never seen since. "
               "Every 'days unfired' below is a LOWER BOUND computed from "
               "discovery dates.")
    out.append("2. `tier` — proposal #10 gates retirement on advisory-tier "
               "rules; the canon does not distinguish advisory from enforced "
               "entries, so no row below can be auto-classified as "
               "retirement-eligible.")
    out.append("3. `subsystem` — the docs-delta join runs on token overlap "
               "between the class's own text (signature + line) and the delta "
               "excerpts; there is no explicit subsystem mapping to join on.")
    out.append("")

    out.append(f"## Failure classes {args.unfired_days}d+ unfired WITH a docs delta "
               "(retirement-review candidates)")
    out.append("")
    if unfired_w_delta:
        out.append("| class | rows | open | last seen | days | docs delta | overlapping tokens |")
        out.append("|---|---|---|---|---|---|---|")
        for r in unfired_w_delta:
            for dkey, toks in r["docs_delta_hits"]:
                out.append(f"| {r['class']} | {r['n']} | {r['open']} | "
                           f"{r['last_seen']} | {r['days_since_last_seen']} | "
                           f"{dkey} | {', '.join(toks)} |")
    else:
        out.append("(none — see class table below for the honest reason)")
    out.append("")

    out.append("## All canon failure classes (titer panel)")
    out.append("")
    out.append("| class | rows | open | last seen | days since | 90d+ unfired | docs-delta hits |")
    out.append("|---|---|---|---|---|---|---|")
    for r in rows_out:
        hits = len(r["docs_delta_hits"])
        out.append(f"| {r['class']} | {r['n']} | {r['open']} | {r['last_seen']} | "
                   f"{r['days_since_last_seen']} | {'YES' if r['unfired_ge_90d'] else 'no'} | {hits} |")
    out.append("")

    out.append(f"*Why the candidate list is {'populated' if unfired_w_delta else 'empty'}: "
               f"the newest canon entry is dated "
               f"{max((r['last_seen'] for r in rows_out if r['last_seen']), default='?')} — "
               f"the canon itself is only days old, so no class can be 90d+ "
               f"unfired yet. This report becomes live when the canon ages or "
               f"when the collector adds last_fired/tier fields (proposal #10's "
               f"actual ask).*")

    dest = K / "garden-reports" / f"titer-{date_s}.md"
    atomic_write(dest, "\n".join(out) + "\n")
    print(f"wrote {dest}")
    print("\n".join(out))


if __name__ == "__main__":
    main()
