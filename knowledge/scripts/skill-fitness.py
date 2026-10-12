#!/usr/bin/env python3
"""skill-fitness.py — Skill League telemetry for Josh's Claude Code skills.

Usage:
  skill-fitness.py log --skill <name> [--session-id <id>] [--outcome applied|loaded_only|unknown] [--latency-ms <n>] [--data '<json>']
  skill-fitness.py backfill --transcripts-dir <dir> [--days 14] [--sample 20]
  skill-fitness.py report

Data: ~/.claude/knowledge/skills-telemetry/invocations.jsonl (append-only)
Line: {"ts","skill","session_id","outcome","latency_ms"}  (latency_ms optional)
Backfill writes only NEW (session_id, skill, ts) tuples never seen before.
Report is read-only: writes fitness-report-<ts>.md, quarantines nothing.
"""
import argparse
import datetime as dt
import json
import os
import sys
import tempfile

HOME = os.path.expanduser("~")
TELEMETRY_DIR = os.path.join(HOME, ".claude/knowledge/skills-telemetry")
LEDGER = os.path.join(TELEMETRY_DIR, "invocations.jsonl")
VALID_OUTCOMES = ("applied", "loaded_only", "unknown")


def now_iso():
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%S.%f")[:-3] + "Z"


def ensure_dir():
    os.makedirs(TELEMETRY_DIR, exist_ok=True)


def append_record(rec):
    """Append one JSON line atomically (append + fsync)."""
    ensure_dir()
    with open(LEDGER, "a") as f:
        f.write(json.dumps(rec, separators=(",", ":")) + "\n")
        f.flush()
        os.fsync(f.fileno())


def load_ledger():
    """Load dedupe keys and records; tolerate a truncated final line."""
    keys, records = set(), []
    if not os.path.exists(LEDGER):
        return keys, records
    with open(LEDGER) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                rec = json.loads(line)
            except json.JSONDecodeError:
                continue
            records.append(rec)
            keys.add((rec.get("session_id"), rec.get("skill"), rec.get("ts")))
    return keys, records


# ---------------------------------------------------------------- log ----
def cmd_log(args):
    if args.data:
        try:
            blob = json.loads(args.data)
        except json.JSONDecodeError as e:
            print(f"FAIL --data is not valid JSON: {e}", file=sys.stderr)
            return 1
        rec = {
            "ts": blob.get("ts") or now_iso(),
            "skill": blob.get("skill") or args.skill,
            "session_id": str(blob.get("session_id") or args.session_id or "unknown"),
            "outcome": blob.get("outcome") or args.outcome,
        }
        if blob.get("latency_ms") is not None:
            rec["latency_ms"] = blob["latency_ms"]
        elif args.latency_ms is not None:
            rec["latency_ms"] = args.latency_ms
    else:
        if not args.skill:
            print("FAIL --skill is required (or pass --data '<json>')", file=sys.stderr)
            return 1
        rec = {
            "ts": now_iso(),
            "skill": args.skill,
            "session_id": args.session_id or "unknown",
            "outcome": args.outcome,
        }
        if args.latency_ms is not None:
            rec["latency_ms"] = args.latency_ms

    if not rec["skill"]:
        print("FAIL no skill name resolved", file=sys.stderr)
        return 1
    if rec["outcome"] not in VALID_OUTCOMES:
        print(f"FAIL outcome must be one of {VALID_OUTCOMES}", file=sys.stderr)
        return 1

    append_record(rec)
    print(f"logged: skill={rec['skill']} outcome={rec['outcome']} "
          f"session={rec['session_id']} ts={rec['ts']}")
    return 0


# ------------------------------------------------------------ backfill ----
def iter_skill_uses(path):
    """Yield (index, ts, skill, line) for every Skill tool_use in a transcript.

    Cheap prefilter: only json.loads lines that literally contain '"Skill"'.
    """
    with open(path, encoding="utf-8", errors="replace") as f:
        for idx, line in enumerate(f):
            if '"Skill"' not in line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            msg = obj.get("message") or {}
            content = msg.get("content") or []
            if not isinstance(content, list):
                continue
            for block in content:
                if (isinstance(block, dict) and block.get("type") == "tool_use"
                        and block.get("name") == "Skill"):
                    skill = (block.get("input") or {}).get("skill")
                    if skill:
                        yield idx, obj.get("timestamp"), skill, obj


def is_user_text_event(obj):
    """True when a transcript line is a genuine new user prompt (not a tool_result)."""
    if obj.get("type") != "user" or obj.get("isMeta"):
        return False
    msg = obj.get("message") or {}
    if msg.get("role") != "user":
        return False
    content = msg.get("content")
    if isinstance(content, str) and content.strip():
        return True
    if isinstance(content, list):
        for block in content:
            if isinstance(block, dict) and block.get("type") == "text" and block.get("text", "").strip():
                return True
    return False


def line_has_tool_use(line_bytes):
    """Cheap check whether a raw transcript line contains any tool_use block."""
    return b'"tool_use"' in line_bytes


def outcome_for_use(path, use_idx, window_lines=400):
    """applied = any later tool_use by the assistant before the next real user prompt.

    Cheap scan: re-read a bounded slice of raw lines after the Skill invocation;
    a user text line closes the turn; a tool_use line inside the turn means the
    session did real work after loading the skill.
    """
    applied = False
    seen = 0
    with open(path, encoding="utf-8", errors="replace") as f:
        for i, raw in enumerate(f):
            if i <= use_idx:
                continue
            if seen >= window_lines:
                break
            seen += 1
            if not ('"tool_use"' in raw or '"type": "user"' in raw or '"type":"user"' in raw):
                continue
            try:
                obj = json.loads(raw)
            except json.JSONDecodeError:
                continue
            if is_user_text_event(obj):
                break
            msg = obj.get("message") or {}
            content = msg.get("content") or []
            if isinstance(content, list):
                for block in content:
                    if (isinstance(block, dict) and block.get("type") == "tool_use"
                            and block.get("name") != "Skill"):
                        applied = True
                        break
            if applied:
                break
    return applied


def cmd_backfill(args):
    tdir = os.path.expanduser(args.transcripts_dir)
    if not os.path.isdir(tdir):
        print(f"FAIL transcripts dir not found: {tdir}", file=sys.stderr)
        return 1

    cutoff = dt.datetime.now(dt.timezone.utc) - dt.timedelta(days=args.days)
    sessions = []
    for root, _dirs, files in os.walk(tdir):
        for name in files:
            if not name.endswith(".jsonl"):
                continue
            p = os.path.join(root, name)
            try:
                mtime = dt.datetime.fromtimestamp(os.path.getmtime(p), dt.timezone.utc)
            except OSError:
                continue
            if mtime >= cutoff:
                sessions.append((mtime, p))
    sessions.sort(reverse=True)  # newest first

    sampled, note = sessions, ""
    if len(sessions) > args.sample:
        sampled = sessions[:args.sample]
        note = (f"SAMPLED: {len(sessions)} session files modified in the last "
                f"{args.days} days; processed only the {args.sample} most recent.")
    if not sampled:
        print(f"No transcript files modified in the last {args.days} days under {tdir}.")
        return 0

    known_keys, _ = load_ledger()
    new_records, skipped_dupes, files_with_usage = [], 0, 0

    for _mtime, path in sampled:
        file_had_usage = False
        file_uses = list(iter_skill_uses(path))
        if not file_uses:
            continue
        file_had_usage = True
        # Cache outcome lookups per (use_idx) — cheap anyway, but keep order.
        for use_idx, ts, skill, obj in file_uses:
            session_id = obj.get("sessionId") or "unknown"
            ts = ts or now_iso()
            key = (session_id, skill, ts)
            if key in known_keys:
                skipped_dupes += 1
                continue
            known_keys.add(key)
            outcome = "applied" if outcome_for_use(path, use_idx) else "loaded_only"
            new_records.append({"ts": ts, "skill": skill,
                                "session_id": session_id, "outcome": outcome})
        _ = file_had_usage

    # Re-sort chronologically so the ledger reads naturally.
    new_records.sort(key=lambda r: r["ts"])
    for rec in new_records:
        append_record(rec)

    files_with_usage = sum(
        1 for _m, p in sampled if any(True for _ in iter_skill_uses(p)))
    print(note)
    print(f"backfill done: sessions_scanned={len(sampled)} "
          f"sessions_with_skill_usage={files_with_usage} "
          f"records_written={len(new_records)} duplicates_skipped={skipped_dupes}")
    return 0


# -------------------------------------------------------------- report ----
def parse_ts(s):
    try:
        return dt.datetime.fromisoformat(s.replace("Z", "+00:00"))
    except (AttributeError, ValueError, TypeError):
        return None


def cmd_report(args):
    _keys, records = load_ledger()
    if not records:
        print("No telemetry yet. Run `log` or `backfill` first.")
        return 0

    now = dt.datetime.now(dt.timezone.utc)
    week = dt.timedelta(days=7)
    cutoff_7d = now - week
    cutoff_14d = now - dt.timedelta(days=14)

    stats = {}
    for rec in records:
        skill = rec.get("skill") or "(none)"
        s = stats.setdefault(skill, {"n": 0, "applied": 0, "last": None,
                                     "n7": 0, "nprior7": 0})
        s["n"] += 1
        if rec.get("outcome") == "applied":
            s["applied"] += 1
        ts = parse_ts(rec.get("ts"))
        if ts:
            if not s["last"] or ts > s["last"]:
                s["last"] = ts
            if ts >= cutoff_7d:
                s["n7"] += 1
            elif ts >= cutoff_14d:
                s["nprior7"] += 1

    rows = []
    for skill, s in stats.items():
        ratio = s["applied"] / s["n"] if s["n"] else 0.0
        rows.append({
            "skill": skill, "n": s["n"], "applied": s["applied"],
            "ratio": ratio, "last": s["last"], "n7": s["n7"], "nprior7": s["nprior7"],
        })

    # worst-first: lowest applied-ratio, then lowest volume, then oldest use
    rows.sort(key=lambda r: (r["ratio"], r["n"],
                             r["last"] or dt.datetime.min.replace(tzinfo=dt.timezone.utc)))

    n = len(rows)
    # Flags only mean something with enough samples: quarantine/cite ranks are
    # computed over skills with >= 3 invocations; thinner skills get LOW-N.
    # Only skills actually underperforming (applied-ratio < 1.0) are
    # quarantine-eligible — with a perfect 1.0 across the board there is
    # nothing to cull and a forced bottom-quartile would flag arbitrarily.
    failing = [r for r in rows if r["n"] >= 3 and r["ratio"] < 1.0]
    eligible = [r for r in rows if r["n"] >= 3]
    ne = len(eligible)
    n_quar = min(1, len(failing)) if failing else 0
    n_cited = max(1, ne // 10) if ne >= 10 else 0
    for i, r in enumerate(eligible):
        if i < n_quar:
            r["flag"] = "QUARANTINE-CANDIDATE"
        elif i >= ne - n_cited:
            r["flag"] = "CITED"
        else:
            r["flag"] = ""
    for r in rows:
        if r["n"] < 3:
            r["flag"] = "LOW-N"

    total_inv = sum(r["n"] for r in rows)
    total_applied = sum(r["applied"] for r in rows)
    inv7 = sum(r["n7"] for r in rows)
    invprior = sum(r["nprior7"] for r in rows)

    lines = []
    lines.append(f"# Skill League fitness report — {now.strftime('%Y-%m-%d %H:%M UTC')}")
    lines.append("")
    lines.append(f"Skills tracked: {n} | total invocations: {total_inv} | "
                 f"overall applied-ratio: {total_applied}/{total_inv} "
                 f"({total_applied / total_inv:.0%}) | last 7d: {inv7} vs prior 7d: {invprior}")
    lines.append("")
    lines.append("| skill | invocations | last used | applied | applied-ratio | 7d | prior 7d | trend | flag |")
    lines.append("|---|---|---|---|---|---|---|---|---|")
    for r in rows:
        last = r["last"].strftime("%Y-%m-%d") if r["last"] else "?"
        if r["nprior7"] == 0 and r["n7"] > 0:
            trend = "new/rising"
        elif r["nprior7"] == 0:
            trend = "-"
        else:
            delta = (r["n7"] - r["nprior7"]) / r["nprior7"]
            trend = f"{delta:+.0%}"
        lines.append(
            f"| {r['skill']} | {r['n']} | {last} | {r['applied']} | "
            f"{r['ratio']:.0%} | {r['n7']} | {r['nprior7']} | {trend} | {r['flag']} |")

    lines.append("")
    low_n = [r["skill"] for r in rows if r["flag"] == "LOW-N"]
    if low_n:
        lines.append(f"Insufficient data (<3 invocations, {len(low_n)}): " + ", ".join(low_n))
    q = [r["skill"] for r in rows if r["flag"] == "QUARANTINE-CANDIDATE"]
    c = [r["skill"] for r in rows if r["flag"] == "CITED"]
    lines.append(f"Quarantine candidates (bottom quartile by applied-ratio, {len(q)}): "
                 + (", ".join(q) if q else "none"))
    lines.append(f"Cited (top decile, {len(c)}): " + (", ".join(c) if c else "none"))
    lines.append("")
    lines.append("Report-only: nothing was quarantined or removed. "
                 "Flags are advisory for Josh's review.")

    report_text = "\n".join(lines) + "\n"
    ensure_dir()
    out_path = os.path.join(
        TELEMETRY_DIR,
        "fitness-report-" + now.strftime("%Y%m%dT%H%M%S") + ".md")
    with open(out_path, "w") as f:
        f.write(report_text)

    print(report_text)
    print(f"report written: {out_path}")
    return 0


# ---------------------------------------------------------------- main ----
def main():
    ap = argparse.ArgumentParser(
        prog="skill-fitness.py",
        description="Skill League: usage/outcome telemetry for Claude Code skills.")
    sub = ap.add_subparsers(dest="cmd", required=True)

    p_log = sub.add_parser("log", help="append one skill invocation to the ledger")
    p_log.add_argument("--skill")
    p_log.add_argument("--session-id")
    p_log.add_argument("--outcome", default="unknown", choices=VALID_OUTCOMES)
    p_log.add_argument("--latency-ms", type=float)
    p_log.add_argument("--data", help="single JSON blob with ts/skill/session_id/outcome/latency_ms")
    p_log.set_defaults(func=cmd_log)

    p_bf = sub.add_parser("backfill", help="mine Claude Code transcripts for Skill invocations")
    p_bf.add_argument("--transcripts-dir", default=os.path.join(HOME, ".claude/projects"))
    p_bf.add_argument("--days", type=int, default=14)
    p_bf.add_argument("--sample", type=int, default=20,
                      help="cap on most-recent session files processed (default 20)")
    p_bf.set_defaults(func=cmd_backfill)

    p_rep = sub.add_parser("report", help="write + print the per-skill fitness table")
    p_rep.set_defaults(func=cmd_report)

    args = ap.parse_args()
    sys.exit(args.func(args))


if __name__ == "__main__":
    main()
