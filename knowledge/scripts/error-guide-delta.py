#!/usr/bin/env python3
"""error-guide-delta.py — does the airo-error-guide hook actually work?

P5 SKILLCULL hook half (estate-fusion-audit-2026-10-13): 191+ fires are logged,
but effectiveness (fire -> repeat-error delta) was never measured.

Method:
  1. Load fires from ~/.claude/knowledge/reports/error-guide-fires.jsonl.
     Schema per row: {ts: epoch_float, tool, advice} — NO session attribution.
  2. Derive linkage: walk ~/.claude/projects/**/*.jsonl transcripts, index every
     tool_result with is_error=true (tool name resolved via its tool_use_id),
     and match each fire to an error event with the SAME tool within ±WINDOW_S
     seconds. The matched error's transcript gives the session_id.
  3. For each session with >=1 matched fire: count same-class (same tool) error
     events BEFORE the first fire and AFTER the last fire in that session.
     Errors between the first and last fire count as neither.

Outputs:
  ~/.claude/knowledge/reports/error-guide-delta.jsonl  (one row per session)
  stdout verdict line, e.g.
    error-guide effect: post-fire repeat-error rate 33% vs pre-fire 100% (n=12 sessions)
  or, if linkage fails:
    INSUFFICIENT LINKAGE — fires carry no session attribution; delta
    unmeasurable without hook change

Does NOT edit the hook.

Usage: error-guide-delta.py [--fires <jsonl>] [--transcripts-dir <dir>]
                            [--out <jsonl>] [--window 3.0]
"""
import argparse
import datetime as dt
import json
import os
import sys

HOME = os.path.expanduser("~")
FIRES_DEFAULT = os.path.join(
    HOME, ".claude/knowledge/reports/error-guide-fires.jsonl")
OUT_DEFAULT = os.path.join(
    HOME, ".claude/knowledge/reports/error-guide-delta.jsonl")
TRANSCRIPTS_DEFAULT = os.path.join(HOME, ".claude/projects")


def parse_iso(ts):
    try:
        return dt.datetime.fromisoformat(ts.replace("Z", "+00:00")).timestamp()
    except (AttributeError, ValueError, TypeError):
        return None


def load_fires(path):
    fires = []
    with open(path) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            ts = rec.get("ts")
            if not isinstance(ts, (int, float)):
                continue
            fires.append({"ts": float(ts), "tool": rec.get("tool") or "?"})
    fires.sort(key=lambda r: r["ts"])
    return fires


def load_error_events(transcripts_dir, min_ts):
    """Index error events (ts, tool, session_id) from all transcripts.

    Only files whose mtime is on/after min_ts minus 1 day are read (fires are
    recent); tool names resolve via tool_use_id -> name from assistant blocks.
    """
    import datetime as dt2
    cutoff = dt2.datetime.fromtimestamp(
        max(0, min_ts - 86400), dt2.timezone.utc)
    events = []
    files = []
    for root, _dirs, names in os.walk(transcripts_dir):
        for name in names:
            if not name.endswith(".jsonl"):
                continue
            p = os.path.join(root, name)
            try:
                mtime = dt2.datetime.fromtimestamp(
                    os.path.getmtime(p), dt2.timezone.utc)
            except OSError:
                continue
            if mtime >= cutoff:
                files.append(p)

    for path in files:
        id2name = {}
        with open(path, encoding="utf-8", errors="replace") as f:
            for line in f:
                if '"tool_use"' not in line and '"tool_result"' not in line:
                    continue
                try:
                    obj = json.loads(line)
                except json.JSONDecodeError:
                    continue
                msg = obj.get("message") or {}
                content = msg.get("content")
                if not isinstance(content, list):
                    continue
                ts = parse_iso(obj.get("timestamp"))
                for block in content:
                    if not isinstance(block, dict):
                        continue
                    if block.get("type") == "tool_use":
                        if block.get("id") and block.get("name"):
                            id2name[block["id"]] = block["name"]
                    elif block.get("type") == "tool_result" and block.get("is_error"):
                        tool = id2name.get(block.get("tool_use_id"), "?")
                        sid = obj.get("sessionId") or os.path.basename(path)[:-6]
                        events.append({
                            "ts": ts, "tool": tool, "session_id": sid,
                        })
    events.sort(key=lambda e: (e["ts"] is None, e["ts"]))
    return events


def link_fires(fires, events, window):
    """Greedy same-tool, nearest-time match of fires to error events."""
    used = set()
    unmatched = 0
    matches = []  # (fire_ts, fire_tool, session_id)
    for fire in fires:
        best, best_dt = None, None
        for i, ev in enumerate(events):
            if i in used or ev["ts"] is None:
                continue
            if ev["tool"] != fire["tool"]:
                continue
            delta = abs(ev["ts"] - fire["ts"])
            if delta <= window and (best is None or delta < best_dt):
                best, best_dt = i, delta
        if best is None:
            unmatched += 1
            continue
        used.add(best)
        ev = events[best]
        matches.append((fire["ts"], fire["tool"], ev["session_id"]))
    return matches, unmatched


def compute_deltas(matches, events, window):
    """Per-session same-class error counts before first fire / after last fire."""
    sessions = {}
    for ts, tool, sid in matches:
        s = sessions.setdefault(sid, {"fires": [], "classes": set()})
        s["fires"].append(ts)
        s["classes"].add(tool)

    # Bucketing: the triggering error (matched to the first fire, within
    # `window` of it) IS a pre-guidance error — guidance was delivered in
    # response to it. So pre = everything before first_fire + window;
    # post = everything after last_fire + window (margin keeps the last
    # fire's own trigger from leaking into the post bucket).
    rows = []
    for sid, s in sorted(sessions.items()):
        first, last = min(s["fires"]), max(s["fires"])
        pre = post = mid = 0
        for ev in events:
            if ev["session_id"] != sid or ev["tool"] not in s["classes"]:
                continue
            if ev["ts"] is None:
                continue
            if ev["ts"] < first + window:
                pre += 1
            elif ev["ts"] > last + window:
                post += 1
            else:
                mid += 1
        rows.append({
            "session_id": sid,
            "pre_count": pre,
            "post_count": post,
            "n_fires": len(s["fires"]),
            "classes": sorted(s["classes"]),
            "between_fires": mid,
        })
    return rows


def main():
    ap = argparse.ArgumentParser(
        prog="error-guide-delta.py",
        description="Measure airo-error-guide effectiveness: same-class error "
                    "recurrence before vs after hook fires, per session.")
    ap.add_argument("--fires", default=FIRES_DEFAULT)
    ap.add_argument("--transcripts-dir", default=TRANSCRIPTS_DEFAULT)
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--window", type=float, default=3.0,
                    help="seconds of slack matching a fire to a transcript error")
    args = ap.parse_args()

    if not os.path.exists(args.fires):
        print(f"FAIL fires file not found: {args.fires}", file=sys.stderr)
        return 1

    fires = load_fires(args.fires)
    if not fires:
        print("error-guide effect: no fires on record — nothing to measure (n=0 sessions)")
        return 0

    events = load_error_events(args.transcripts_dir, min(f["ts"] for f in fires))
    matches, unmatched = link_fires(fires, events, args.window)

    link_rate = len(matches) / len(fires) if fires else 0.0
    if not matches or link_rate < 0.5:
        print(f"INSUFFICIENT LINKAGE — fires carry no session attribution; "
              f"delta unmeasurable without hook change "
              f"(matched {len(matches)}/{len(fires)} fires at ±{args.window}s; "
              f"{len(events)} transcript error events indexed)")
        return 0

    rows = compute_deltas(matches, events, args.window)

    with open(args.out, "w") as f:
        for row in rows:
            f.write(json.dumps(row, separators=(",", ":")) + "\n")

    n = len(rows)
    pre_sessions = sum(1 for r in rows if r["pre_count"] > 0)
    post_sessions = sum(1 for r in rows if r["post_count"] > 0)
    pre_rate = pre_sessions / n if n else 0.0
    post_rate = post_sessions / n if n else 0.0
    total_pre = sum(r["pre_count"] for r in rows)
    total_post = sum(r["post_count"] for r in rows)
    print(f"error-guide effect: post-fire repeat-error rate "
          f"{post_rate:.0%} vs pre-fire {pre_rate:.0%} (n={n} sessions) — "
          f"same-class errors {total_pre} before first fire vs {total_post} "
          f"after last fire; linked {len(matches)}/{len(fires)} fires "
          f"({unmatched} unmatched)")
    return 0


if __name__ == "__main__":
    sys.exit(main())
