#!/usr/bin/env python3
"""claim-latency.py — claim born-to-closed latency distribution across the harness.

Read-only measurement instrument over three claim ledgers:
  1. Mission control  ~/.claude/knowledge/mission-control/events.jsonl
  2. Dreamer proposals ~/.claude/knowledge/dreams/proposals/*.md
     + outcomes        ~/.claude/knowledge/garden-reports/proposal-outcomes.jsonl
  3. Predictions      ~/.claude/knowledge/predictions/predictions.jsonl

Answers: is claim latency bimodal (machine claims closing in minutes vs
Josh-gated claims rotting for days)?

Usage:
  claim-latency.py            collect: append one snapshot row to
                              knowledge/claim-latency/snapshots.jsonl and
                              write report-latest.json / report-latest.md;
                              print short stdout summary
  claim-latency.py --report   compute fresh and print the human report
                              (no writes, no snapshot append)
  claim-latency.py --json     compute fresh and print machine JSON
                              (no writes, no snapshot append)
  claim-latency.py --help     this help

Exit codes: 0 = success, 1 = validation error (missing ledger, empty data,
unwritable output).
"""
import argparse
import glob
import json
import os
import re
import sys
from datetime import datetime, timezone, timedelta

HOME = os.path.expanduser("~")
EVENTS_PATH = os.path.join(HOME, ".claude/knowledge/mission-control/events.jsonl")
PROPOSALS_DIR = os.path.join(HOME, ".claude/knowledge/dreams/proposals")
OUTCOMES_PATH = os.path.join(HOME, ".claude/knowledge/garden-reports/proposal-outcomes.jsonl")
PREDICTIONS_PATH = os.path.join(HOME, ".claude/knowledge/predictions/predictions.jsonl")
OUT_DIR = os.path.join(HOME, ".claude/knowledge/claim-latency")
SNAPSHOTS_PATH = os.path.join(OUT_DIR, "snapshots.jsonl")
REPORT_JSON_PATH = os.path.join(OUT_DIR, "report-latest.json")
REPORT_MD_PATH = os.path.join(OUT_DIR, "report-latest.md")

MIN_SNAPSHOT_DAYS = 7  # trend claim honesty gate


def fail(msg):
    print("ERROR: %s" % msg, file=sys.stderr)
    sys.exit(1)


# ---------------------------------------------------------------- time utils
def parse_ts(raw):
    """Parse the ISO-ish timestamps the harness actually emits.

    Handles: 2026-10-11T20:57:27Z, 2026-10-11T17:35:02-0400,
    2026-10-11T17:35:02+00:00, 2026-10-11 (day granularity, assumed UTC).
    Returns an aware datetime (UTC) or None.
    """
    if raw is None:
        return None
    s = str(raw).strip()
    if not s:
        return None
    # normalize 'Z' and colon-less offsets for fromisoformat
    t = s
    if t.endswith("Z"):
        t = t[:-1] + "+00:00"
    m = re.match(r"^(.*[+-]\d{2})(\d{2})$", t)
    if m and not re.search(r"[+-]\d{2}:\d{2}$", t):
        t = m.group(1) + ":" + m.group(2)
    try:
        dt = datetime.fromisoformat(t)
    except ValueError:
        # date-only or odd formats
        for fmt in ("%Y-%m-%d", "%Y-%m-%d %H:%M:%S", "%Y/%m/%d"):
            try:
                dt = datetime.strptime(s, fmt)
                break
            except ValueError:
                continue
        else:
            return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc)


def now_utc():
    return datetime.now(timezone.utc)


def hours_since(dt, ref=None):
    ref = ref or now_utc()
    return max(0.0, (ref - dt).total_seconds() / 3600.0)


def percentile(values, p):
    """Linear-interpolated percentile; None when no data."""
    if not values:
        return None
    vs = sorted(values)
    if len(vs) == 1:
        return float(vs[0])
    k = (len(vs) - 1) * (p / 100.0)
    f = int(k)
    c = min(f + 1, len(vs) - 1)
    if f == c:
        return float(vs[f])
    return float(vs[f] + (vs[c] - vs[f]) * (k - f))


def median(values):
    return percentile(values, 50)


def fmt_h(h):
    if h is None:
        return "-"
    if h >= 48:
        return "%.1fd" % (h / 24.0)
    if h >= 1:
        return "%.1fh" % h
    if h * 60.0 < 1.0:
        return "<1m"
    return "%.0fm" % (h * 60.0)


# --------------------------------------------------------- mission control
MC_BUCKETS = [
    ("lt1h", 1.0), ("h1_24", 24.0), ("d1_3", 72.0), ("d3_7", 168.0), ("gt7d", None),
]


def bucketize_hours(values, buckets):
    out = {name: 0 for name, _ in buckets}
    for v in values:
        for name, hi in buckets:
            if hi is None or v < hi:
                out[name] += 1
                break
    return out


def load_mission_control(now):
    """Episode analysis over events.jsonl.

    born  = first event ts of an episode
    closed = ts of first later event with state=done
    Any event after a done row starts a NEW episode (re-opening).
    Episodes still open at end-of-log: fold state = last event state;
    needs-josh => Josh-gated open claim.
    """
    if not os.path.exists(EVENTS_PATH):
        fail("mission-control ledger missing: %s" % EVENTS_PATH)
    rows = []
    skipped = 0
    with open(EVENTS_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            ts = parse_ts(r.get("ts"))
            if ts is None or not r.get("workstream"):
                skipped += 1
                continue
            r["_ts"] = ts
            rows.append(r)
    if not rows:
        fail("mission-control ledger parsed to zero usable rows")

    by_ws = {}
    for r in rows:
        by_ws.setdefault(r["workstream"], []).append(r)
    for ws in by_ws:
        by_ws[ws].sort(key=lambda r: r["_ts"])

    episodes = []  # dicts: born, closed, last_state, workstream, needs
    for ws, evs in by_ws.items():
        cur = None
        for ev in evs:
            state = ev.get("state", "")
            if cur is None:
                cur = {"born": ev["_ts"],
                       "closed": ev["_ts"] if state == "done" else None,
                       "last_state": state,
                       "workstream": ws, "needs": ev.get("needs") or ""}
                episodes.append(cur)
            elif cur["closed"] is not None:
                # re-opening: done workstream got a later event
                cur = {"born": ev["_ts"],
                       "closed": ev["_ts"] if state == "done" else None,
                       "last_state": state,
                       "workstream": ws, "needs": ev.get("needs") or ""}
                episodes.append(cur)
            else:
                if state == "done":
                    cur["closed"] = ev["_ts"]
                    cur["last_state"] = state
                else:
                    cur["last_state"] = state
                    cur["needs"] = ev.get("needs") or cur["needs"]
    closed = [e for e in episodes if e["closed"] is not None]
    open_eps = [e for e in episodes if e["closed"] is None]
    needs_josh = [e for e in open_eps if e["last_state"] == "needs-josh"]
    missing_cond = [e for e in needs_josh if not (e.get("needs") or "").strip()]

    ttc_h = [hours_since(e["born"], e["closed"]) for e in closed]
    open_age_h = [hours_since(e["born"], now) for e in open_eps]

    detail_open = sorted(open_eps, key=lambda e: e["born"])[:8]
    return {
        "skipped_rows": skipped,
        "episodes_total": len(episodes),
        "closed": len(closed),
        "open": len(open_eps),
        "needs_josh_open": len(needs_josh),
        "needs_josh_missing_close_condition": len(missing_cond),
        "ttc_h": ttc_h,
        "open_age_h": open_age_h,
        "oldest_open": [
            {"workstream": e["workstream"], "state": e["last_state"],
             "age_h": round(hours_since(e["born"], now), 1),
             "needs": (e.get("needs") or "")[:90]}
            for e in detail_open
        ],
    }


def mc_snapshot(mc, now):
    open_age = mc["open_age_h"]
    ttc = mc["ttc_h"]
    return {
        "open": mc["open"],
        "open_age_median_h": round(median(open_age), 1) if open_age else 0.0,
        "open_age_p90_h": round(percentile(open_age, 90), 1) if open_age else 0.0,
        "closed": mc["closed"],
        "ttc_median_h": round(median(ttc), 1) if ttc else 0.0,
        "ttc_p90_h": round(percentile(ttc, 90), 1) if ttc else 0.0,
        "buckets": bucketize_hours(ttc, MC_BUCKETS),
        "needs_josh_open": mc["needs_josh_open"],
        "needs_josh_missing_close_condition": mc["needs_josh_missing_close_condition"],
    }


# ---------------------------------------------------------------- proposals
PROP_BUCKETS = [
    ("lt1d", 1.0), ("d1_3", 3.0), ("d3_7", 7.0), ("d7_14", 14.0), ("gt14d", None),
]


def norm_title(s):
    return re.sub(r"\s+", " ", (s or "").strip().lower())


def slug_from_filename(fname):
    base = os.path.basename(fname)
    stem = re.sub(r"\.md$", "", base)
    stem = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", stem)
    return norm_title(stem.replace("-", " "))


def first_status_line(path):
    """FIRST 'status:' line in frontmatter only (duplicate-status bug)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            in_fm = False
            fm_count = 0
            for line in fh:
                s = line.rstrip("\n")
                if s.strip() == "---":
                    fm_count += 1
                    if fm_count == 1:
                        in_fm = True
                        continue
                    else:
                        break  # frontmatter closed
                if in_fm:
                    m = re.match(r"^status:\s*(.+?)\s*$", s)
                    if m:
                        return m.group(1)
    except OSError:
        return None
    return None


def load_proposals(now):
    files = sorted(glob.glob(os.path.join(PROPOSALS_DIR, "*.md")))
    if not files:
        fail("no proposal files found in %s" % PROPOSALS_DIR)
    outcomes = []
    skipped_out = 0
    if os.path.exists(OUTCOMES_PATH):
        with open(OUTCOMES_PATH, "r", encoding="utf-8") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    r = json.loads(line)
                except ValueError:
                    skipped_out += 1
                    continue
                if not r.get("proposal"):
                    skipped_out += 1
                    continue
                outcomes.append(r)
    else:
        fail("outcomes ledger missing: %s" % OUTCOMES_PATH)

    proposals = []
    for path in files:
        fname = os.path.basename(path)
        m = re.match(r"^(\d{4}-\d{2}-\d{2})-", fname)
        if not m:
            proposals.append({"file": fname, "error": "no date prefix", "skipped": True})
            continue
        born_d = parse_ts(m.group(1))
        if born_d is None:
            proposals.append({"file": fname, "error": "bad date prefix", "skipped": True})
            continue
        proposals.append({
            "file": fname,
            "slug": slug_from_filename(fname),
            "born": born_d,
            "status": first_status_line(path),
            "skipped": False,
        })

    usable = [p for p in proposals if not p.get("skipped")]
    # match outcomes -> proposals by normalized title
    by_slug = {}
    for p in usable:
        by_slug.setdefault(p["slug"], []).append(p)
    matched = {}
    unmatched_outcomes = []
    for o in outcomes:
        title = norm_title(o.get("proposal"))
        d = parse_ts(o.get("date"))
        hit = by_slug.get(title)
        if not hit:
            # fallback: unique containment either way
            cands = [p for p in usable
                     if title and (title in p["slug"] or p["slug"] in title)]
            if len(cands) == 1:
                hit = [cands[0]]
        if hit and d is not None:
            target = hit[0]
            prev = matched.get(target["file"])
            if prev is None or d < prev[1]:
                matched[target["file"]] = (o, d)  # earliest outcome wins
        else:
            unmatched_outcomes.append({
                "proposal": o.get("proposal"),
                "date": o.get("date"),
                "action": o.get("action"),
                "reason": "no proposal file matched" if d is not None else "bad outcome date",
            })

    closed_days, open_eps = [], []
    for p in usable:
        hit = matched.get(p["file"])
        if hit:
            closed_days.append((hit[1] - p["born"]).total_seconds() / 86400.0)
        else:
            age_d = max(0.0, (now - p["born"]).total_seconds() / 86400.0)
            open_eps.append({"file": p["file"], "status": p["status"], "age_d": age_d})

    detail_open = sorted(open_eps, key=lambda e: e["age_d"], reverse=True)[:8]
    return {
        "files": len(proposals),
        "skipped_files": len(proposals) - len(usable),
        "outcome_rows": len(outcomes),
        "skipped_outcome_rows": skipped_out,
        "matched_outcomes": len(matched),
        "unmatched_outcomes": unmatched_outcomes,
        "open": len(open_eps),
        "closed": len(closed_days),
        "ttc_d": closed_days,
        "open_age_d": [e["age_d"] for e in open_eps],
        "open_statuses": sorted({(e["status"] or "none") for e in open_eps}),
        "oldest_open": [
            {"file": e["file"], "status": e["status"], "age_d": round(e["age_d"], 1)}
            for e in detail_open
        ],
    }


def prop_snapshot(pr, now):
    open_age = pr["open_age_d"]
    ttc = pr["ttc_d"]
    buckets = {name: 0 for name, _ in PROP_BUCKETS}
    for v in ttc:
        for name, hi in PROP_BUCKETS:
            if hi is None or v < hi:
                buckets[name] += 1
                break
    return {
        "open": pr["open"],
        "open_age_median_d": round(median(open_age), 1) if open_age else 0.0,
        "closed": pr["closed"],
        "ttc_median_d": round(median(ttc), 1) if ttc else 0.0,
        "buckets": buckets,
    }


# -------------------------------------------------------------- predictions
def load_predictions(now):
    if not os.path.exists(PREDICTIONS_PATH):
        fail("predictions ledger missing: %s" % PREDICTIONS_PATH)
    skipped = 0
    subs, res = {}, {}
    with open(PREDICTIONS_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                skipped += 1
                continue
            typ = r.get("type", "submission") if "type" in r else "submission"
            if typ in ("flag", "extension"):
                continue
            pid = r.get("id")
            ts = parse_ts(r.get("ts"))
            if not pid or ts is None:
                skipped += 1
                continue
            if typ == "resolution":
                res.setdefault(pid, []).append((ts, r))
            else:
                subs[pid] = (ts, r)  # last-wins on duplicate ids
    closed_h, briers = [], []
    for pid, (ts, r) in subs.items():
        rr = res.get(pid)
        if rr:
            rts, row = min(rr, key=lambda x: x[0])  # first resolution wins
            closed_h.append(max(0.0, (rts - ts).total_seconds() / 3600.0))
            b = row.get("brier")
            try:
                briers.append(float(b))
            except (TypeError, ValueError):
                pass
    open_eps = [
        {"id": pid, "age_h": hours_since(ts, now), "claim": (r.get("claim") or "")[:80]}
        for pid, (ts, r) in subs.items() if pid not in res
    ]
    detail_open = sorted(open_eps, key=lambda e: e["age_h"], reverse=True)[:8]
    return {
        "skipped_rows": skipped,
        "submissions": len(subs),
        "resolved": sum(1 for pid in subs if pid in res),
        "open": len(open_eps),
        "ttc_h": closed_h,
        "open_age_h": [e["age_h"] for e in open_eps],
        "brier_mean": (sum(briers) / len(briers)) if briers else None,
        "oldest_open": [
            {"id": e["id"], "age_h": round(e["age_h"], 1), "claim": e["claim"]}
            for e in detail_open
        ],
    }


def pred_snapshot(pd, now):
    open_age = pd["open_age_h"]
    ttc = pd["ttc_h"]
    return {
        "open": pd["open"],
        "open_age_median_h": round(median(open_age), 1) if open_age else 0.0,
        "closed": pd["resolved"],
        "ttc_median_h": round(median(ttc), 1) if ttc else 0.0,
        "brier_mean": round(pd["brier_mean"], 3) if pd["brier_mean"] is not None else 0.0,
    }


# -------------------------------------------------------------- bimodality
def bimodality_verdict(mc, pr, pd):
    """One honest sentence: is open-claim latency bimodal (machine minutes vs
    Josh-gated days)? Test: do both a fast mode (<24h) and a slow mode
    (>3d) each hold at least a quarter of the open-claim age distribution?"""
    ages = list(mc["open_age_h"]) + [a * 24.0 for a in pr["open_age_d"]]
    fast = sum(1 for a in ages if a < 24.0)
    slow = sum(1 for a in ages if a >= 72.0)
    n = len(ages)
    mc_med = median(mc["ttc_h"]) if mc["ttc_h"] else None
    josh_share = (mc["needs_josh_open"] / n) if n else 0.0
    if n and fast >= 0.25 * n and slow >= 0.25 * n:
        return ("Bimodal: %d of %d open claims are under 24h old while %d are over "
                "3 days old (%d%% Josh-gated), with closed claims closing in median %s"
                % (fast, n, slow, round(josh_share * 100), fmt_h(mc_med)))
    if n and slow > 0.5 * n:
        return ("Not bimodal yet: the open-claim population is dominated by slow "
                "claims (%d of %d over 3 days old, %d%% Josh-gated) with no fast mode"
                % (slow, n, round(josh_share * 100)))
    if n:
        return ("Not bimodal on current data: %d open claims cluster in one mode "
                "(fast %d, slow %d) so the distribution is unimodal"
                % (n, fast, slow))
    return "No open claims to assess bimodality on"


# ----------------------------------------------------------------- reports
def snapshot_days():
    """Days spanned by snapshots.jsonl (for the honesty gate)."""
    if not os.path.exists(SNAPSHOTS_PATH):
        return 0
    days = set()
    with open(SNAPSHOTS_PATH, "r", encoding="utf-8") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                r = json.loads(line)
            except ValueError:
                continue
            ts = parse_ts(r.get("ts"))
            if ts:
                days.add(ts.date())
    return len(days)


def build_report():
    now = now_utc()
    mc = load_mission_control(now)
    pr = load_proposals(now)
    pd = load_predictions(now)

    snap = {
        "ts": now.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sources": {
            "mission_control": mc_snapshot(mc, now),
            "proposals": prop_snapshot(pr, now),
            "predictions": pred_snapshot(pd, now),
        },
        "bimodality_note": bimodality_verdict(mc, pr, pd),
    }
    detail = {
        "ts": snap["ts"],
        "snapshot_days_so_far": snapshot_days(),
        "mission_control": {
            "episodes_total": mc["episodes_total"],
            "skipped_rows": mc["skipped_rows"],
            "oldest_open": mc["oldest_open"],
        },
        "proposals": {
            "files": pr["files"],
            "skipped_files": pr["skipped_files"],
            "outcome_rows": pr["outcome_rows"],
            "skipped_outcome_rows": pr["skipped_outcome_rows"],
            "matched_outcomes": pr["matched_outcomes"],
            "unmatched_outcomes": pr["unmatched_outcomes"],
            "open_statuses": pr["open_statuses"],
            "oldest_open": pr["oldest_open"],
        },
        "predictions": {
            "skipped_rows": pd["skipped_rows"],
            "submissions": pd["submissions"],
            "oldest_open": pd["oldest_open"],
        },
    }
    report = dict(snap)
    report["detail"] = detail
    return snap, report


def hist_md(buckets, total):
    mx = max(buckets.values()) if buckets else 0
    lines = []
    for name, n in buckets.items():
        width = int(round(40.0 * n / mx)) if mx else 0
        bar = "#" * width if n else ""
        lines.append("| %s | %d | %s |" % (name, n, bar))
    return "\n".join(lines)


def render_md(snap, report):
    s = snap["sources"]
    d = report["detail"]
    mc, pr, pdj = s["mission_control"], s["proposals"], s["predictions"]
    out = []
    out.append("# Claim latency report")
    out.append("")
    out.append("Generated %s from the live ledgers (read-only)." % snap["ts"])
    out.append("")
    out.append("## Mission control claims (hours)")
    out.append("")
    out.append("- Open claims: %d (Josh-gated needs-josh: %d, missing close condition: %d)"
               % (mc["open"], mc["needs_josh_open"], mc["needs_josh_missing_close_condition"]))
    out.append("- Open age: median %s, p90 %s"
               % (fmt_h(mc["open_age_median_h"]), fmt_h(mc["open_age_p90_h"])))
    out.append("- Closed episodes: %d; time-to-close: median %s, p90 %s"
               % (mc["closed"], fmt_h(mc["ttc_median_h"]), fmt_h(mc["ttc_p90_h"])))
    out.append("- TTC histogram (h):")
    out.append("")
    out.append("| bucket | n | |")
    out.append("|---|---|---|")
    out.append(hist_md(mc["buckets"], mc["closed"]))
    out.append("- Detail: %d episodes total, %d malformed rows skipped; oldest open:"
               % (d["mission_control"]["episodes_total"], d["mission_control"]["skipped_rows"]))
    for e in d["mission_control"]["oldest_open"][:5]:
        out.append("    - %s (%s, %s old)%s"
                   % (e["workstream"], e["state"], fmt_h(e["age_h"]),
                      (" needs: " + e["needs"]) if e["needs"] else ""))
    out.append("")
    out.append("## Proposals (days, day granularity — never hour precision)")
    out.append("")
    out.append("- Open proposals: %d; open age median %.1fd" % (pr["open"], pr["open_age_median_d"]))
    out.append("  - open statuses (no outcome row matched): %s"
               % ", ".join(d["proposals"]["open_statuses"]))
    out.append("- Closed proposals: %d; time-to-decision median %.1fd" % (pr["closed"], pr["ttc_median_d"]))
    out.append("- TTC histogram (d):")
    out.append("")
    out.append("| bucket | n | |")
    out.append("|---|---|---|")
    out.append(hist_md(pr["buckets"], pr["closed"]))
    out.append("- Detail: %d files (%d skipped), %d outcome rows (%d skipped, %d matched)"
               % (d["proposals"]["files"], d["proposals"]["skipped_files"],
                  d["proposals"]["outcome_rows"], d["proposals"]["skipped_outcome_rows"],
                  d["proposals"]["matched_outcomes"]))
    for u in d["proposals"]["unmatched_outcomes"]:
        out.append("    - UNMATCHED outcome row: \"%s\" (%s, %s)"
                   % (u["proposal"], u["date"], u["action"]))
    for e in d["proposals"]["oldest_open"][:5]:
        out.append("    - open: %s (status %s, %.1fd old)" % (e["file"], e["status"], e["age_d"]))
    out.append("")
    out.append("## Predictions (hours)")
    out.append("")
    out.append("- Open predictions: %d; open age median %s"
               % (pdj["open"], fmt_h(pdj["open_age_median_h"])))
    out.append("- Resolved predictions: %d; time-to-resolution median %s; mean Brier %.3f"
               % (pdj["closed"], fmt_h(pdj["ttc_median_h"]), pdj["brier_mean"]))
    out.append("- Detail: %d submission rows, %d malformed rows skipped"
               % (d["predictions"]["submissions"], d["predictions"]["skipped_rows"]))
    for e in d["predictions"]["oldest_open"][:5]:
        out.append("    - open: %s (%s old) %s" % (e["id"], fmt_h(e["age_h"]), e["claim"]))
    out.append("")
    days = d["snapshot_days_so_far"]
    out.append("**Days of data: %d snapshot day(s).**" % days)
    if days < MIN_SNAPSHOT_DAYS:
        out.append("INSUFFICIENT — the trend claim needs at least %d days of "
                   "snapshots; today is snapshot day %d." % (MIN_SNAPSHOT_DAYS, max(days, 1)))
    else:
        out.append("Trend window satisfied (%d days of snapshots)." % days)
    out.append("")
    out.append("**Verdict:** %s" % snap["bimodality_note"])
    out.append("")
    return "\n".join(out)


def short_summary(snap, report):
    s = snap["sources"]
    mc, pr, pdj = s["mission_control"], s["proposals"], s["predictions"]
    days = report["detail"]["snapshot_days_so_far"]
    note = "INSUFFICIENT (<%dd of snapshots)" % MIN_SNAPSHOT_DAYS if days < MIN_SNAPSHOT_DAYS \
        else "%dd of snapshots" % days
    return ("claim-latency: mission_control open=%d closed=%d ttc_med=%s "
            "(josh-gated %d) | proposals open=%d closed=%d ttc_med=%.1fd | "
            "predictions open=%d resolved=%d brier=%.3f | %s | %s"
            % (mc["open"], mc["closed"], fmt_h(mc["ttc_median_h"]), mc["needs_josh_open"],
               pr["open"], pr["closed"], pr["ttc_median_d"],
               pdj["open"], pdj["closed"], pdj["brier_mean"], note,
               snap["bimodality_note"][:110]))


# -------------------------------------------------------------------- main
def main():
    ap = argparse.ArgumentParser(
        description="Claim born-to-closed latency distribution (mission control, "
                    "proposals, predictions); read-only measurement instrument.",
        epilog="Default mode appends one snapshot row and rewrites the two "
               "report-latest files; --report and --json are read-only.")
    g = ap.add_mutually_exclusive_group()
    g.add_argument("--report", action="store_true",
                   help="print the human report to stdout (no writes)")
    g.add_argument("--json", action="store_true",
                   help="print the machine JSON to stdout (no writes)")
    args = ap.parse_args()

    snap, report = build_report()

    if args.report:
        print(render_md(snap, report))
        return 0
    if args.json:
        print(json.dumps(report, indent=2))
        return 0

    # default: collect + both file writes + short stdout summary
    try:
        os.makedirs(OUT_DIR, exist_ok=True)
    except OSError as e:
        fail("cannot create output dir %s: %s" % (OUT_DIR, e))
    try:
        with open(SNAPSHOTS_PATH, "a", encoding="utf-8") as fh:
            fh.write(json.dumps(snap) + "\n")
        # days-of-data counts the snapshot we just appended
        report["detail"]["snapshot_days_so_far"] = snapshot_days()
        with open(REPORT_JSON_PATH, "w", encoding="utf-8") as fh:
            json.dump(report, fh, indent=2)
            fh.write("\n")
        with open(REPORT_MD_PATH, "w", encoding="utf-8") as fh:
            fh.write(render_md(snap, report))
    except OSError as e:
        fail("cannot write outputs in %s: %s" % (OUT_DIR, e))
    print(short_summary(snap, report))
    return 0


if __name__ == "__main__":
    sys.exit(main())
