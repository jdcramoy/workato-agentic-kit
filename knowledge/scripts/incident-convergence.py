#!/usr/bin/env python3
"""incident-convergence.py — P3 FIXLOOP (estate fusion audit 2026-10-13).

Counts repeated incidents of the same root cause per (recipe-id, class) key
over a trailing 14-day window, so read-only triage loops converge instead of
autopsying the same external cause forever (Seismic 82256903:stop hit 13).

Inputs (READ-ONLY):
  ~/.claude/knowledge/mission-control/events.jsonl
  ~/.claude/knowledge/dreams/bus/workato-watchdog.jsonl

Modes:
  --json              machine-readable key counts + converged list
  --check <key>       exit 0 = under threshold, 2 = CONVERGED (>=3 in window)
  --report            human-readable table
  --dry-run card --key <k>   render the escalation card to STDOUT ONLY

Pure stdlib. Never writes anything. Never files a real card.
"""

import argparse
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
SOURCES = [
    os.path.join(HOME, ".claude/knowledge/mission-control/events.jsonl"),
    os.path.join(HOME, ".claude/knowledge/dreams/bus/workato-watchdog.jsonl"),
]

WINDOW_DAYS = 14
THRESHOLD = 3

# 8-digit recipe IDs (e.g. 82256903, 82272892). Calendar-date-shaped tokens
# (19xxxxxx / 20xxxxxx, e.g. 20261011) are excluded — they are dates, not
# Workato recipe IDs, and would poison the key space.
RECIPE_RE = re.compile(r"\b(?!19\d{6}\b|20\d{6}\b)(\d{8})\b")

# Incident-class vocabulary -> canonical class word. Longest/most specific
# patterns first so "recipe_stop_user" counts as stop, "timed out" as timeout.
CLASS_PATTERNS = [
    (re.compile(r"recipe_stop_user|\bstop(?:ped|ping)?\b", re.I), "stop"),
    (re.compile(r"\bstall(?:ed|ing)?\b|\bstal l\b", re.I), "stalled"),
    (re.compile(r"\bfail(?:ed|ure|ing|s)?\b|\bfailing\b", re.I), "fail"),
    (re.compile(r"\b401\b|\bunauthorized\b", re.I), "401"),
    (re.compile(r"\b403\b|\bforbidden\b", re.I), "403"),
    (re.compile(r"\b429\b|\brate.?limit", re.I), "429"),
    (re.compile(r"\b500\b", re.I), "500"),
    (re.compile(r"\btimed.?out\b|\btimeouts?\b", re.I), "timeout"),
    (re.compile(r"\bcrash(?:ed|ing)?\b", re.I), "crash"),
    (re.compile(r"\bconnection\b|\bdisconnect", re.I), "connection"),
    (re.compile(r"\bauth\b|\bcredential|\bre.?auth", re.I), "auth"),
    (re.compile(r"\berrors?\b", re.I), "error"),
]

TS_RE = re.compile(r"\b(\d{4}-\d{2}-\d{2})[T ](\d{2}:\d{2}:\d{2})")


def parse_ts(raw):
    """Parse an ISO-ish ts; None if absent/unparseable."""
    if not raw or not isinstance(raw, str):
        return None
    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).astimezone(timezone.utc)
    except ValueError:
        m = TS_RE.search(raw)
        if not m:
            return None
        try:
            return datetime.strptime(m.group(1) + " " + m.group(2),
                                     "%Y-%m-%d %H:%M:%S").replace(tzinfo=timezone.utc)
        except ValueError:
            return None


def row_texts(row):
    """Free-text fields to mine, in priority order."""
    out = []
    for field in ("what", "summary", "note", "jira_title", "thread"):
        val = row.get(field)
        if isinstance(val, str) and val:
            out.append(val)
    return out


def classify(text):
    """Return (class_word, offset) of the first (highest-priority) class match."""
    for pattern, name in CLASS_PATTERNS:
        m = pattern.search(text)
        if m:
            return name, m.start()
    return "incident", len(text)


def extract_key(row):
    """Extract '<recipe-id>:<class>' from a row, or None.

    For each recipe ID found, the class word is the highest-priority class
    pattern whose match lands nearest that ID in the text.
    """
    for text in row_texts(row):
        ids = [(m, m.start()) for m in RECIPE_RE.finditer(text)]
        if not ids:
            continue
        best = None
        for _match, pos in ids:
            cls, cls_pos = classify(text)
            dist = abs(cls_pos - pos)
            if best is None or dist < best[0]:
                best = (dist, cls, cls_pos, text)
        if best is None:
            continue
        _dist, cls, cls_pos, _text = best
        ids_sorted = sorted(ids, key=lambda t: abs(t[1] - cls_pos))
        rid = ids_sorted[0][0].group(1)
        return "%s:%s" % (rid, cls)
    return None


def collect():
    """Aggregate keys over the trailing 14-day window from both sources."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    keys = {}
    for path in SOURCES:
        if not os.path.exists(path):
            continue
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                ts = parse_ts(row.get("ts"))
                if ts is None or ts < cutoff or ts > now:
                    continue
                key = extract_key(row)
                if not key:
                    continue
                entry = keys.setdefault(
                    key, {"count": 0, "last_ts": None, "workstreams": []})
                entry["count"] += 1
                ts_str = ts.strftime("%Y-%m-%dT%H:%M:%SZ")
                if entry["last_ts"] is None or ts_str > entry["last_ts"]:
                    entry["last_ts"] = ts_str
                ws = row.get("workstream") or row.get("agent") or "unknown"
                if ws not in entry["workstreams"]:
                    entry["workstreams"].append(ws)
    return keys


def render_card(key, entry):
    count = entry["count"] if entry else 0
    last = entry["last_ts"] if entry else "n/a"
    rid, cls = (key.split(":", 1) + ["incident"])[:2] if ":" in key else (key, "incident")
    lines = [
        "=" * 72,
        "ESCALATION CARD (DRY-RUN — rendered to stdout, NOT filed anywhere)",
        "=" * 72,
        "event: escalation-card",
        "state: needs-josh",
        "key:   %s" % key,
        "what:  Incident %s has recurred %d times in %dd — same root cause; "
        "autopsies exist in prior rows; needs Josh decision (fix or risk-accept)"
        % (key, count, WINDOW_DAYS),
        "last seen: %s" % last,
        "",
        "FIXLOOP GATE context:",
        "  - recipe-id: %s" % rid,
        "  - incident class: %s" % cls,
        "  - count in trailing %dd window: %d (threshold %d => CONVERGED)"
        % (WINDOW_DAYS, count, THRESHOLD),
        "  - A read-only autopsy of this key is FORBIDDEN by the gate.",
        "  - If the root cause is EXTERNAL (another system/actor cycling the",
        "    asset, e.g. the Workato AHQ | AI federated identity stop/start",
        "    cycling recipe 82256903), it belongs here, not in autopsy #N+1.",
        "",
        "Josh decision requested: fix the root cause, or explicitly risk-accept it.",
        "=" * 72,
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Incident convergence counter (read-only).")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--report", action="store_true", help="human-readable output")
    ap.add_argument("--check", metavar="KEY", help="exit 0 under threshold, 2 if converged")
    ap.add_argument("--dry-run", action="store_true", help="render escalation card to stdout only")
    ap.add_argument("card", nargs="?", help="literal 'card' after --dry-run")
    ap.add_argument("--key", metavar="KEY", help="key for --check / --dry-run card")
    args = ap.parse_args()

    if args.dry_run:
        if args.card != "card" or not args.key:
            ap.error("usage: --dry-run card --key <recipe-id>:<class>")
        entry = collect().get(args.key)
        print(render_card(args.key, entry))
        return 0

    keys = collect()

    if args.check:
        count = keys.get(args.check, {}).get("count", 0)
        if count >= THRESHOLD:
            print("CONVERGED: %s count=%d (>= %d in %dd)" %
                  (args.check, count, THRESHOLD, WINDOW_DAYS))
            return 2
        print("under threshold: %s count=%d (< %d in %dd)" %
              (args.check, count, THRESHOLD, WINDOW_DAYS))
        return 0

    if args.json:
        converged = sorted(k for k, v in keys.items() if v["count"] >= THRESHOLD)
        print(json.dumps({"keys": keys, "converged": converged},
                         indent=2, sort_keys=True))
        return 0

    # --report (default when no mode given)
    converged = sorted(k for k, v in keys.items() if v["count"] >= THRESHOLD)
    print("incident-convergence — trailing %dd, threshold %d (%d distinct keys)"
          % (WINDOW_DAYS, THRESHOLD, len(keys)))
    print("-" * 72)
    for key in sorted(keys, key=lambda k: -keys[k]["count"]):
        e = keys[key]
        flag = " <-- CONVERGED (autopsies barred, escalate once)"
        if key not in converged:
            flag = ""
        print("%-24s count=%-3d last=%s  ws=%s%s"
              % (key, e["count"], e["last_ts"], ",".join(e["workstreams"][:3]), flag))
    if not converged:
        print("(no key has reached the convergence threshold)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
