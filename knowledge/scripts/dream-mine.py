#!/usr/bin/env python3
"""dream-mine.py — mine recent Claude Code session transcripts for the
harness dreamer. Stdlib only, read-only, bounded output.

Writes a digest JSON the dreamer agent interprets:
  ~/.claude/knowledge/dreams/data/<YYYY-MM-DD>-mine.json

Signals extracted (per last N days):
  sessions        count, per-project counts, total assistant turns
  corrections     user messages matching correction heuristics (verbatim,
                  with session refs) — the highest-signal mining target
  errors          recurring error-ish strings from tool results, deduped,
                  top 25 with counts
  tool_freq       most-used tools
  ngrams          repeated 4-gram tool sequences (>= 3 occurrences) —
                  skill candidates
  cost            summed cost-state USD where present

Usage: dream-mine.py [--days 3] [--max-file-bytes 30000000]
Config defaults read from knowledge/dreams/config.json when present.
"""

import argparse
import collections
import datetime as dt
import json
import os
import re
import sys

HOME = os.path.expanduser("~")
PROJECTS = os.path.join(HOME, ".claude", "projects")
CONFIG = os.path.join(HOME, ".claude", "knowledge", "dreams", "config.json")
OUT_DIR = os.path.join(HOME, ".claude", "knowledge", "dreams", "data")

# verify-class tools: a trajectory ending in a read-back is a completed
# build-verify loop, not just repetition (used by trajectory mining)
VERIFY = ("job_get", "recipe_get", "read_thread", "read_channel_messages",
          "data_table_query", "get_recipe", "Read", "browser_evaluate",
          "recipe_builder_get_input_schema", "mcp_server_get")

# User phrases that indicate a correction/redo of agent behavior.
CORRECTION_RE = re.compile(
    r"^\s*(no\b|no,|nope|not that|I meant|i meant|actually,|actually |that's wrong|"
    r"thats wrong|wrong\b|don't\b|dont\b|stop\b|revert\b|undo\b|again\b|"
    r"you (broke|missed|misread|forgot|deleted|overwrote)|why did you|"
    r"I (said|asked|told you)|as I said|like I said|that's not|thats not)",
    re.I,
)
# Noise guards: short acks and injected/system lines aren't corrections.
NOT_CORRECTION_RE = re.compile(
    r"^\s*(no problem|no worries|not now|note that|stop hook feedback|"
    r"caveat:|<command|<local-command|system-reminder|"
    r"no[,,]?\s*(that'?s|this is|you'?re)\s*(perfect|great|good|exactly|"
    r"right|fine|awesome|amazing|it|the one)\b)\b", re.I)
ERROR_RE = re.compile(
    r"(?i)\b(error|exception|traceback|failed to|failure|denied|refused|"
    r"ECONNRESET|ETIMEDOUT|EPIPE|429|500 Internal|502|503|504|"
    r"not on the appropriate screen|report_rendering_failed|silent(ly)? (no-?op|fail))\b"
)


def load_config():
    defaults = {"mine_days_back": 3, "transcript_max_bytes_per_file": 30_000_000,
                "max_correction_lines": 200, "max_ngrams": 20, "max_errors": 25}
    try:
        with open(CONFIG) as f:
            defaults.update(json.load(f))
    except Exception:
        pass
    return defaults


def iter_lines(path, max_bytes):
    try:
        if os.path.getsize(path) > max_bytes:
            return
        with open(path, "r", errors="replace") as f:
            for line in f:
                if line.strip():
                    yield line
    except OSError:
        return


def text_of(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return " ".join(
            b.get("text", "") for b in content
            if isinstance(b, dict) and b.get("type") == "text")
    return ""


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--days", type=int, default=None)
    args = ap.parse_args()
    cfg = load_config()
    days = args.days or cfg["mine_days_back"]
    max_bytes = cfg["transcript_max_bytes_per_file"]
    cutoff = dt.datetime.now() - dt.timedelta(days=days)

    sessions = 0
    per_project = collections.Counter()
    turns = 0
    corrections = []
    errors = collections.Counter()
    tool_freq = collections.Counter()
    ngrams = collections.Counter()
    trajectories = collections.Counter()

    if not os.path.isdir(PROJECTS):
        print("no projects dir", file=sys.stderr)
        return 1

    for proj in sorted(os.listdir(PROJECTS)):
        pdir = os.path.join(PROJECTS, proj)
        if not os.path.isdir(pdir):
            continue
        for name in os.listdir(pdir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, name)
            try:
                if dt.datetime.fromtimestamp(os.path.getmtime(path)) < cutoff:
                    continue
            except OSError:
                continue
            sessions += 1
            per_project[proj] += 1
            seq = []
            for line in iter_lines(path, max_bytes):
                try:
                    ev = json.loads(line)
                except Exception:
                    continue
                et = ev.get("type")
                if et == "assistant":
                    turns += 1
                    msg = ev.get("message") or {}
                    for b in msg.get("content") or []:
                        if isinstance(b, dict) and b.get("type") == "tool_use":
                            tool_freq[b.get("name", "?")] += 1
                            seq.append(b.get("name", "?"))
                        if isinstance(b, dict) and b.get("type") == "text":
                            for m in ERROR_RE.finditer(b.get("text", "")):
                                errors[m.group(0).lower()] += 1
                elif et == "user":
                    msg = ev.get("message") or {}
                    txt = text_of(msg.get("content"))
                    # tool_result blocks carry provider/API errors too
                    if isinstance(msg.get("content"), list):
                        for b in msg["content"]:
                            if isinstance(b, dict) and b.get("type") == "tool_result":
                                blob = str(b.get("content", ""))[:2000]
                                for m in ERROR_RE.finditer(blob):
                                    errors[m.group(0).lower()] += 1
                    if txt and not txt.startswith(("<", "[{")):
                        line1 = txt.strip().splitlines()[0][:200]
                        # Josh's rule: a bare connective ("NO", "However",
                        # "ok") resolves to nothing — a correction candidate
                        # needs substantive text around the signal word.
                        words = line1.split()
                        if (len(line1) >= 15 and len(words) >= 3
                                and CORRECTION_RE.search(line1)
                                and not NOT_CORRECTION_RE.search(line1)
                                and len(corrections) < cfg["max_correction_lines"]):
                            corrections.append({
                                "session": name[:12], "project": proj[-40:],
                                "text": line1,
                            })
                elif et == "cost-state":
                    cs = ev.get("cost") or {}
                    if isinstance(cs.get("total_cost_usd"), (int, float)):
                        cost_total = cs["total_cost_usd"]
            # n-gram accumulation per session
            for i in range(len(seq) - 3):
                ngrams[" > ".join(seq[i:i + 4])] += 1
            # trajectory mining: 4-grams whose last tool is a read-back/verify
            # — a completed build-verify loop, not just repetition
            for i in range(len(seq) - 3):
                if any(v in seq[i + 3] for v in VERIFY):
                    trajectories[" > ".join(seq[i:i + 4])] += 1

    out = {
        "generated": dt.datetime.now().isoformat(timespec="seconds"),
        "window_days": days,
        "sessions": sessions,
        "assistant_turns": turns,
        "per_project": per_project.most_common(15),
        "corrections": corrections,
        "top_errors": errors.most_common(cfg["max_errors"]),
        "top_tools": tool_freq.most_common(25),
        "verify_trajectories": [
            {"seq": k, "count": v}
            for k, v in trajectories.most_common(15) if v >= 2
        ],
        "repeated_4grams": [
            {"seq": k, "count": v}
            for k, v in ngrams.most_common(cfg["max_ngrams"]) if v >= 3
        ],
    }
    os.makedirs(OUT_DIR, exist_ok=True)
    stamp = dt.date.today().isoformat()
    out_path = os.path.join(OUT_DIR, f"{stamp}-mine.json")
    with open(out_path, "w") as f:
        json.dump(out, f, indent=1)
    print(out_path)
    print(f"sessions={sessions} turns={turns} corrections={len(corrections)} "
          f"error_kinds={len(errors)} repeated_seqs={len(out['repeated_4grams'])}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
