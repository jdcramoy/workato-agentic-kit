#!/usr/bin/env python3
"""incident-convergence.py — P3 FIXLOOP (estate fusion audit 2026-10-13;
self-counting fix 2026-10-20, triage card fixloop-counter-self-counting).

Counts repeated incidents of the same root cause per (recipe-id, class) key
over a trailing 14-day window, so read-only triage loops converge instead of
autopsying the same external cause forever (Seismic 82256903:stop hit 13).

2026-10-20 fix (cortex investigation fixloop-recurrence-cluster.md, dispatch
2026-10-19T18:57Z — 85 counted rows behind 12 escalated keys were ~21 self,
~33 meta, ~21 fix-announcements, 2 all-clears; only ~10 real failures, all
already fixed):

  1. GROUND-TRUTH GATE: before escalating, consult regression-canon status
     (regression-canon/canon.jsonl), the build ledger (build-ledger.jsonl),
     and — with --live — live job state (wt jobs list <id> --status failed).
  2. SELF/META EXCLUSION: the counter's own escalation rows, meta-discussion
     rows (cortex-pulse, jira-triage, dropped-session absorbs, ...) and
     fix-announcement / all-clear rows are excluded from counts.
  3. NO 'incident' DEFAULT CLASS: a row with no class keyword is NOT an
     incident — it is build chatter; it is not counted at all.
  4. KEY DEDUPE: escalation cards are deduped by <recipe-id>:<class> KEY
     across mission-control registry + events + triage queue, regardless of
     the slug a prior card was filed under. --check exits 0 (do not file)
     when the key is already carded.

Inputs (READ-ONLY):
  ~/.claude/knowledge/mission-control/events.jsonl
  ~/.claude/knowledge/dreams/bus/workato-watchdog.jsonl
  ~/.claude/knowledge/regression-canon/canon.jsonl        (gate)
  ~/.claude/knowledge/build-ledger.jsonl                  (gate)
  ~/.claude/knowledge/mission-control/registry.json       (dedupe)
  ~/.claude/knowledge/triage/queue.jsonl                  (dedupe)

Modes:
  --json              machine-readable key counts + converged + gate verdicts
  --check <key>       exit 0 = do not escalate (under threshold, gated, or
                      already carded); exit 2 = ESCALATE
  --report            human-readable table (default)
  --live              include live job-state check via `wt jobs list` (slow)
  --dry-run card --key <k>   render the escalation card to STDOUT ONLY

Pure stdlib for counting. Never writes anything. Never files a real card.
"""

import argparse
import json
import os
import re
import subprocess
import sys
from datetime import datetime, timedelta, timezone

HOME = os.path.expanduser("~")
SOURCES = [
    os.path.join(HOME, ".claude/knowledge/mission-control/events.jsonl"),
    os.path.join(HOME, ".claude/knowledge/dreams/bus/workato-watchdog.jsonl"),
]
CANON = os.path.join(HOME, ".claude/knowledge/regression-canon/canon.jsonl")
LEDGER = os.path.join(HOME, ".claude/knowledge/build-ledger.jsonl")
REGISTRY = os.path.join(HOME, ".claude/knowledge/mission-control/registry.json")
TRIAGE_QUEUE = os.path.join(HOME, ".claude/knowledge/triage/queue.jsonl")

WINDOW_DAYS = 14
THRESHOLD = 3
WT_BIN = os.path.join(HOME, ".local/bin/wt")

# 8-digit recipe IDs (e.g. 82256903, 82272892). Calendar-date-shaped tokens
# (19xxxxxx / 20xxxxxx, e.g. 20261011) are excluded — they are dates, not
# Workato recipe IDs, and would poison the key space.
RECIPE_RE = re.compile(r"\b(?!19\d{6}\b|20\d{6}\b)(\d{8})\b")

# Incident-class vocabulary -> canonical class word. Longest/most specific
# patterns first so "recipe_stop_user" counts as stop, "timed out" as timeout.
# NOTE: there is deliberately NO fallback class — a row with no class keyword
# is not an incident (old behaviour defaulted to 'incident', which turned
# every piece of build chatter naming a recipe ID into a counted occurrence).
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

# Rows whose own workstream is the mechanism's exhaust or pure meta-discussion.
# A row that LISTS converged keys (cortex pulse, jira-triage "FIXLOOP gate ran
# first"), quotes a dropped session's transcript, or announces a fix is not an
# occurrence of the failure. (Investigation rec #1, 2026-10-19.)
SELF_WS_PATTERNS = [re.compile(p, re.I) for p in (
    r"^fixloop-escalation",       # this mechanism's own output
    r"escalation",                # escalation-*, *-escalation
    r"-incident$",                # seismic-incident-*, *-incident
    r"-recurrence",               # hr-genie-collector-recurrence, ...
    r"^cortex-pulse",
    r"^jira-triage",
    r"^jira-autotriage",
    r"^triage-pass",
    r"^dropped-",                 # deadman auto-absorbs quoting transcripts
    r"^harness-dreamer",
)]

# Text-level fix-announcement / all-clear / self-card markers, applied to any
# row regardless of workstream ("shipping the fix feeds the failure counter").
SELF_TEXT_PATTERNS = [re.compile(p, re.I) for p in (
    r"\bhas recurred\b",                      # this mechanism's own card prose
    r"\bESCALATION CARD\b",
    r"\bFIXLOOP GATE\b",
    r"\bfix[- ]or[- ]risk[- ]accept\b",
    r"built and shipped",
    r"built and live-verified",
    r"\bhotfix\b",
    r"\bshipped (?:the |amended |a )?(?:fix|amend|v\d)",
    r"\bfix (?:built|shipped|closed|filed)\b",
    r"^\s*fixed\b",                           # "Fixed the ... dedupe in recipe X"
    r"\bbug filed\b",
    r"\bfiled the (?:deploy-record|ticket|bug)\b",
    r"\ball[- ]clear\b",
    r"did NOT fail",
    r"ticking green",
    r"\bzero new P1s\b",
)]

# Escalation-card fingerprint for KEY-based dedupe: a registry/event/queue row
# counts as "this key already has an open escalation card" when it carries an
# escalation marker AND names the key.
CARD_MARKERS = [re.compile(p, re.I) for p in (
    r"\bESCALATION CARD\b", r"\bhas recurred\b", r"\bfix[- ]or[- ]risk[- ]accept\b",
    r"\bFIXLOOP GATE\b", r"escalation",
)]
KEY_NAME_RE_TMPL = r"incident[ (:]%s(?::%s)?\b"

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


def ts_str(dt):
    return dt.strftime("%Y-%m-%dT%H:%M:%SZ") if dt else None


def row_texts(row):
    """Free-text fields to mine, in priority order."""
    out = []
    for field in ("what", "summary", "note", "jira_title", "thread"):
        val = row.get(field)
        if isinstance(val, str) and val:
            out.append(val)
    return out


def classify(text):
    """Return (class_word, offset) of the first (highest-priority) class match,
    or None when no class keyword is present. No 'incident' default: rows
    without an incident-class keyword are not incidents."""
    for pattern, name in CLASS_PATTERNS:
        m = pattern.search(text)
        if m:
            return name, m.start()
    return None


def row_is_self_or_meta(row):
    """True when the row is the mechanism's own exhaust, a meta-discussion
    row, a fix announcement, or an all-clear — none of those is an
    occurrence of a failure."""
    ws = row.get("workstream") or row.get("agent") or ""
    for p in SELF_WS_PATTERNS:
        if p.search(ws):
            return True
    for text in row_texts(row):
        for p in SELF_TEXT_PATTERNS:
            if p.search(text):
                return True
    return False


def extract_key(row):
    """Extract '<recipe-id>:<class>' from a row, or None.

    For each recipe ID found, the class word is the highest-priority class
    pattern whose match lands nearest that ID in the text. Text with no class
    keyword yields no key (fix 2026-10-20: no more 'incident' default).
    """
    for text in row_texts(row):
        ids = [(m, m.start()) for m in RECIPE_RE.finditer(text)]
        if not ids:
            continue
        classification = classify(text)
        if classification is None:
            continue
        cls, cls_pos = classification
        ids_sorted = sorted(ids, key=lambda t: abs(t[1] - cls_pos))
        rid = ids_sorted[0][0].group(1)
        return "%s:%s" % (rid, cls)
    return None


def jsonl(path):
    if not os.path.exists(path):
        return
    with open(path, "r", encoding="utf-8", errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                yield json.loads(line)
            except ValueError:
                continue


def load_json(path):
    if not os.path.exists(path):
        return None
    try:
        with open(path, "r", encoding="utf-8", errors="replace") as fh:
            return json.load(fh)
    except (ValueError, OSError):
        return None


def collect():
    """Aggregate keys over the trailing 14-day window from both sources,
    excluding self/meta/fix-announcement rows (2026-10-20 fix)."""
    now = datetime.now(timezone.utc)
    cutoff = now - timedelta(days=WINDOW_DAYS)
    keys = {}
    excluded = {"self_or_meta": 0, "no_class_keyword": 0}
    for path in SOURCES:
        for row in jsonl(path):
            ts = parse_ts(row.get("ts"))
            if ts is None or ts < cutoff or ts > now:
                continue
            key = extract_key(row)
            if not key:
                # Distinguish "not an incident at all" only when the row at
                # least names a recipe ID; otherwise it is just unrelated text.
                if any(RECIPE_RE.search(t) for t in row_texts(row)):
                    excluded["no_class_keyword"] += 1
                continue
            if row_is_self_or_meta(row):
                excluded["self_or_meta"] += 1
                continue
            entry = keys.setdefault(
                key, {"count": 0, "last_ts": None, "workstreams": []})
            entry["count"] += 1
            s = ts_str(ts)
            if entry["last_ts"] is None or s > entry["last_ts"]:
                entry["last_ts"] = s
            ws = row.get("workstream") or row.get("agent") or "unknown"
            if ws not in entry["workstreams"]:
                entry["workstreams"].append(ws)
    keys = dict(keys)
    keys["_excluded"] = excluded  # popped by callers
    return keys


def canon_status(rid):
    """Return (all_closed, open_count, closed_count) of canon rows for rid."""
    rows = [r for r in jsonl(CANON) if str(r.get("recipe_id")) == rid]
    if not rows:
        return None, 0, 0  # no canon coverage at all
    open_n = sum(1 for r in rows if r.get("status") == "open")
    return open_n == 0, open_n, len(rows) - open_n


def ledger_last_activity(rid):
    """Return the newest build-ledger ts mentioning this recipe (ts string)."""
    newest = None
    for r in jsonl(LEDGER):
        rid_field = r.get("recipe_id")
        cmd = r.get("command") or ""
        if str(rid_field) == rid or (rid_field is None and re.search(r"\b%s\b" % rid, cmd)):
            t = r.get("ts")
            if t and (newest is None or t > newest):
                newest = t
    return newest


def live_failed_since(rid, since_dt):
    """Live job state via `wt jobs list <rid> --status failed --raw`.

    Returns dict {ok, failed_total, failed_since, latest_error, note}.
    failed_since counts failed jobs completed after `since_dt` (None = forever).
    Never raises; ok=False means the probe could not run."""
    out = {"ok": False, "failed_total": None, "failed_since": 0,
           "latest_error": None, "note": ""}
    if not os.path.exists(WT_BIN):
        out["note"] = "wt CLI not found"
        return out
    try:
        proc = subprocess.run(
            [WT_BIN, "jobs", "list", rid, "--status", "failed", "--raw"],
            capture_output=True, text=True, timeout=60)
        if proc.returncode != 0:
            out["note"] = "wt exit %d" % proc.returncode
            return out
        data = json.loads(proc.stdout)
    except (subprocess.TimeoutExpired, ValueError, OSError) as exc:
        out["note"] = "live probe failed: %s" % exc.__class__.__name__
        return out
    out["ok"] = True
    out["failed_total"] = data.get("job_failed_count")
    latest = None
    for item in data.get("items") or []:
        done = parse_ts(item.get("completed_at") or "")
        if done is None:
            continue
        if since_dt is not None and done <= since_dt:
            continue
        out["failed_since"] += 1
        if latest is None or done > latest:
            latest = done
            err = (item.get("error_parts") or {}).get("message") or item.get("error")
            out["latest_error"] = (err or "")[:120]
    return out


def filed_card_keys():
    """Keys that already have an escalation card, deduped by KEY not slug.

    Scans mission-control registry + events + triage queue for rows whose
    text carries an escalation marker and names '<rid>:<class>'.
    """
    filed = {}
    sources = []
    reg = load_json(REGISTRY)
    if isinstance(reg, dict):
        rows = reg.get("rows") or reg.get("entries") or []
        if isinstance(rows, list):
            sources.extend(r for r in rows if isinstance(r, dict))
        for v in reg.values():
            if isinstance(v, dict) and (v.get("workstream") or v.get("what")):
                sources.append(v)
            elif isinstance(v, list):
                sources.extend(x for x in v if isinstance(x, dict))
    for path in (SOURCES[0], TRIAGE_QUEUE):
        sources.extend(r for r in jsonl(path))
    for row in sources:
        text = " ".join(t for t in (row.get("what"), row.get("summary"),
                                    row.get("title"), row.get("workstream"),
                                    row.get("jira_title")) if isinstance(t, str))
        if not text:
            continue
        if not any(p.search(text) for p in CARD_MARKERS):
            continue
        for m in re.finditer(r"incident[ (:]((?!19|20)\d{8})(?::(\w+))?", text, re.I):
            key = "%s:%s" % (m.group(1), m.group(2) or "incident")
            filed.setdefault(key, []).append(
                row.get("workstream") or row.get("slug") or row.get("agent") or "unknown")
    return filed


def ground_truth_gate(key, entry, live=False):
    """Consult canon + build ledger + (optionally) live job state before
    escalating. Returns dict {escalate, reasons, evidence}."""
    rid = key.split(":", 1)[0]
    reasons = []
    evidence = {}
    last_dt = parse_ts(entry["last_ts"]) if entry else None

    all_closed, open_n, closed_n = canon_status(rid)
    evidence["canon"] = {"rows": open_n + closed_n, "open": open_n,
                         "closed": closed_n} if all_closed is not None else \
                        {"rows": 0, "open": 0, "closed": 0, "note": "no canon rows"}
    if all_closed is True:
        reasons.append("canon: all %d canon rows for %s are closed" % (closed_n, rid))
    elif all_closed is None:
        evidence["canon"]["note"] = ("no canon rows (canon lags reality — "
                                     "not decisive either way)")

    ledger_ts = ledger_last_activity(rid)
    evidence["ledger_last_activity"] = ledger_ts
    if ledger_ts:
        led_dt = parse_ts(ledger_ts)
        if last_dt and led_dt and led_dt > last_dt:
            reasons.append("build-ledger: fix/build work for %s at %s is "
                           "AFTER the last counted occurrence %s"
                           % (rid, ledger_ts, entry["last_ts"]))

    if live:
        probe = live_failed_since(rid, last_dt)
        evidence["live"] = probe
        if probe["ok"] and probe["failed_since"] == 0:
            reasons.append("live: 0 failed jobs for %s since last counted "
                           "occurrence %s — recipe is green"
                           % (rid, entry["last_ts"] or "window start"))
        elif not probe["ok"]:
            evidence["live"]["note"] = (evidence["live"].get("note", "") +
                                        " (live check unavailable; gate ran on "
                                        "canon + ledger only)")
    return {"escalate": not reasons, "reasons": reasons, "evidence": evidence}


def split_key(key):
    if ":" in key:
        rid, cls = key.split(":", 1)
    else:
        rid, cls = key, "unclassified"
    return rid, cls


def render_card(key, entry, gate, already_carded):
    count = entry["count"] if entry else 0
    last = entry["last_ts"] if entry else "n/a"
    rid, cls = split_key(key)
    lines = [
        "=" * 72,
        "ESCALATION CARD (DRY-RUN — rendered to stdout, NOT filed anywhere)",
        "=" * 72,
        "event: escalation-card",
        "state: needs-josh",
        "key:   %s" % key,
        "what:  Incident %s has recurred %d times in %dd; needs Josh decision "
        "(fix or risk-accept)" % (key, count, WINDOW_DAYS),
        "last seen: %s" % last,
        "",
        "KEY DEDUPE (dedupe by key, never by slug):",
    ]
    if already_carded:
        lines.append("  - ALREADY CARDED: open escalation card(s) exist for this "
                     "key under slug(s): %s" % ", ".join(sorted(set(
                         already_carded))[:6]))
        lines.append("  - DO NOT file a new card. Work the existing one by key "
                     "%s." % key)
    else:
        lines.append("  - no open escalation card found for this key in "
                     "registry / events / triage queue")
    lines += [
        "",
        "GROUND-TRUTH GATE (canon + build-ledger%s):" % (" + live jobs" if gate and
                                                         gate["evidence"].get("live") else ""),
    ]
    if gate:
        if gate["reasons"]:
            for r in gate["reasons"]:
                lines.append("  - GATED: %s" % r)
            lines.append("  - DO NOT escalate: ground truth says resolved/closed "
                         "or already being worked.")
        else:
            lines.append("  - no gate suppression: canon not fully closed, no "
                         "post-failure ledger fix work%s"
                         % (", live state not green" if gate["evidence"].get("live")
                            else " (live check not run; pass --live)"))
        ev = gate["evidence"]
        lines.append("  - evidence: canon=%s ledger_last=%s%s" % (
            ev.get("canon"), ev.get("ledger_last_activity") or "none",
            (" live_failed_since=%s" % ev["live"].get("failed_since"))
            if ev.get("live") else ""))
    lines += [
        "",
        "FIXLOOP GATE context:",
        "  - recipe-id: %s" % rid,
        "  - incident class: %s" % cls,
        "  - count in trailing %dd window: %d (threshold %d => CONVERGED)"
        % (WINDOW_DAYS, count, THRESHOLD),
        "  - A read-only autopsy of this key is FORBIDDEN by the gate.",
        "  - The class word is a terminal-state label, not a root cause; do",
        "    not assert 'same root cause' across occurrences without comparing",
        "    signatures.",
        "",
        "Josh decision requested: fix the root cause, or explicitly risk-accept it.",
        "=" * 72,
    ]
    return "\n".join(lines)


def main():
    ap = argparse.ArgumentParser(description="Incident convergence counter (read-only).")
    ap.add_argument("--json", action="store_true", help="machine-readable output")
    ap.add_argument("--report", action="store_true", help="human-readable output")
    ap.add_argument("--check", metavar="KEY", help="exit 0 = do not escalate, 2 = ESCALATE")
    ap.add_argument("--dry-run", action="store_true", help="render escalation card to stdout only")
    ap.add_argument("card", nargs="?", help="literal 'card' after --dry-run")
    ap.add_argument("--key", metavar="KEY", help="key for --check / --dry-run card")
    ap.add_argument("--live", action="store_true",
                    help="run the live job-state probe (wt jobs list) in the gate")
    ap.add_argument("--filed-keys", action="store_true",
                    help="print keys that already have escalation cards (key dedupe)")
    args = ap.parse_args()

    if args.filed_keys:
        print(json.dumps({"already_carded_keys":
                          sorted(filed_card_keys().keys())}, indent=2, sort_keys=True))
        return 0

    if args.dry_run:
        if args.card != "card" or not args.key:
            ap.error("usage: --dry-run card --key <recipe-id>:<class>")
        keys = collect()
        keys.pop("_excluded", None)
        entry = keys.get(args.key)
        carded = filed_card_keys().get(args.key, [])
        gate = ground_truth_gate(args.key, entry, live=args.live)
        print(render_card(args.key, entry, gate, carded))
        return 0

    keys = collect()
    excluded = keys.pop("_excluded", {"self_or_meta": 0, "no_class_keyword": 0})
    converged = sorted(k for k, v in keys.items() if v["count"] >= THRESHOLD)
    carded_keys = filed_card_keys()

    if args.check:
        count = keys.get(args.check, {}).get("count", 0)
        if count < THRESHOLD:
            print("under threshold: %s count=%d (< %d in %dd) — do not escalate"
                  % (args.check, count, THRESHOLD, WINDOW_DAYS))
            return 0
        carded = carded_keys.get(args.check, [])
        if carded:
            print("ALREADY CARDED by key %s under slug(s) %s — do not file a "
                  "duplicate; work the existing card" % (args.check, ", ".join(sorted(set(carded)))))
            return 0
        gate = ground_truth_gate(args.check, keys.get(args.check), live=args.live)
        if not gate["escalate"]:
            print("GATED (not escalating): %s" % "; ".join(gate["reasons"]))
            return 0
        print("ESCALATE: %s count=%d (>= %d in %dd), no gate suppression, not "
              "already carded" % (args.check, count, THRESHOLD, WINDOW_DAYS))
        return 2

    if args.json:
        out = {"keys": keys, "converged": converged,
               "excluded_rows": excluded,
               "already_carded_keys": sorted(carded_keys.keys())}
        gates = {}
        for k in converged:
            g = ground_truth_gate(k, keys[k], live=args.live)
            g["already_carded"] = carded_keys.get(k, [])
            g["escalate"] = g["escalate"] and not g["already_carded"]
            gates[k] = g
        out["gate"] = gates
        out["escalate_now"] = sorted(k for k in converged if gates[k]["escalate"])
        print(json.dumps(out, indent=2, sort_keys=True))
        return 0

    # --report (default when no mode given)
    print("incident-convergence — trailing %dd, threshold %d (%d distinct keys)"
          % (WINDOW_DAYS, THRESHOLD, len(keys)))
    print("excluded from counts: %d self/meta/fix-announcement rows, %d "
          "no-class-keyword rows (no 'incident' default)"
          % (excluded["self_or_meta"], excluded["no_class_keyword"]))
    print("-" * 72)
    for key in sorted(keys, key=lambda k: -keys[k]["count"]):
        e = keys[key]
        if key not in converged:
            flag = ""
        elif carded_keys.get(key):
            flag = " <-- CONVERGED but ALREADY CARDED by key (slug(s): %s) — no new card" \
                   % ", ".join(sorted(set(carded_keys[key]))[:3])
        else:
            gate = ground_truth_gate(key, e, live=args.live)
            if gate["reasons"]:
                flag = " <-- CONVERGED but GATED: %s" % gate["reasons"][0]
            else:
                flag = " <-- CONVERGED, ESCALATE"
        print("%-24s count=%-3d last=%s  ws=%s%s"
              % (key, e["count"], e["last_ts"], ",".join(e["workstreams"][:3]), flag))
    if not converged:
        print("(no key has reached the convergence threshold)")
    escalate_now = [k for k in converged
                    if not carded_keys.get(k)
                    and ground_truth_gate(k, keys[k], live=args.live)["escalate"]]
    print("-" * 72)
    print("escalations to file: %d%s"
          % (len(escalate_now), (" — " + ", ".join(escalate_now)) if escalate_now
             else " (all converged keys are gated or already carded)"))
    return 0


if __name__ == "__main__":
    sys.exit(main())
