#!/usr/bin/env python3
"""autonomy.py — earned-autonomy engine (zero-LLM, stdlib only).

Trust earned from data, not granted by prose. Three subcommands:

  score       Compute the calibration evidence base from three read-only
              ledgers (predictions, decisions/outcomes, proposal outcomes)
              plus mission-control needs-josh closure history. Writes
              ~/.claude/knowledge/autonomy/evidence.json.

  authority   Derive ~/.claude/knowledge/autonomy/authority.json — the
              per-class authority table. Every class is born mode=josh-only.
              Evidence can only make a class ELIGIBLE for recommend.
              The engine NEVER writes mode=auto-close and NEVER mutates
              mission-control, proposals, or any claim store. It reads,
              scores, recommends.

  recommend   Read the claims-sweep needs_josh buckets and emit
              ~/.claude/knowledge/autonomy/recommendations-latest.json —
              batch-decision candidates with the historical rows that drive
              each suggestion. No honest pattern -> "no-pattern", confidence
              null. Never invents confidence.

With no arguments: score -> authority -> recommend in sequence.

Exit 0 on success, 1 on validation error.
"""
import argparse
import glob
import json
import os
import re
import sys
import tempfile
from collections import defaultdict
from datetime import datetime, timedelta, timezone

KNOWLEDGE = os.path.expanduser("~/.claude/knowledge")
PREDICTIONS = os.path.join(KNOWLEDGE, "predictions", "predictions.jsonl")
DECISIONS = os.path.join(KNOWLEDGE, "decisions", "decisions.jsonl")
OUTCOMES = os.path.join(KNOWLEDGE, "decisions", "outcomes.jsonl")
PROPOSAL_OUTCOMES = os.path.join(KNOWLEDGE, "garden-reports", "proposal-outcomes.jsonl")
PROPOSALS_DIR = os.path.join(KNOWLEDGE, "dreams", "proposals")
MISSION_EVENTS = os.path.join(KNOWLEDGE, "mission-control", "events.jsonl")
CLAIMS_SWEEP = os.path.join(KNOWLEDGE, "reports", "claims-sweep-latest.json")

AUTONOMY_DIR = os.path.join(KNOWLEDGE, "autonomy")
EVIDENCE_JSON = os.path.join(AUTONOMY_DIR, "evidence.json")
AUTHORITY_JSON = os.path.join(AUTONOMY_DIR, "authority.json")
RECOMMENDATIONS_JSON = os.path.join(AUTONOMY_DIR, "recommendations-latest.json")

WINDOW_DAYS = 30
PROMOTION_RULE = "n>=20 AND accuracy>=0.8 AND trend not inverted"
N_MIN = 20
ACC_MIN = 0.8
TREND_INVERT_MARGIN = 0.05

LAW = ("Every class is born josh-only. Evidence can only make a class ELIGIBLE "
       "for recommend. auto-close exists as a mode value but is only ever set "
       "by Josh hand-editing this file.")


class ValidationError(Exception):
    pass


# ---------------------------------------------------------------- utilities

def parse_ts(value):
    """Parse the timestamp formats found across the ledgers.

    Handles: 2026-10-23T01:02:03Z, ...+00:00, ...-0400 (no colon), and bare
    dates 2026-10-23 (day granularity, proposal outcomes). Returns an aware
    datetime in UTC, or None.
    """
    if not value or not isinstance(value, str):
        return None
    s = value.strip()
    try:
        if re.match(r"^\d{4}-\d{2}-\d{2}$", s):
            return datetime(s[:4], s[5:7], s[8:10], tzinfo=timezone.utc)
        if s.endswith("Z"):
            s = s[:-1] + "+00:00"
        # normalize -0400 / +0530 (no colon) to -04:00 for fromisoformat
        m = re.search(r"([+-]\d{2})(\d{2})$", s)
        if m:
            s = s[:m.start()] + m.group(1) + ":" + m.group(2)
        dt = datetime.fromisoformat(s)
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)
    except (ValueError, TypeError):
        return None


def read_jsonl(path):
    """Yield (row, lineno); malformed lines are skipped and counted."""
    rows = []
    bad = 0
    if not os.path.exists(path):
        return rows, bad
    with open(path, "r", encoding="utf-8") as fh:
        for lineno, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append((json.loads(line), lineno))
            except json.JSONDecodeError:
                bad += 1
    return rows, bad


def atomic_write_json(path, payload):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as fh:
            json.dump(payload, fh, indent=2, sort_keys=False)
            fh.write("\n")
        os.replace(tmp, path)
    except BaseException:
        if os.path.exists(tmp):
            os.remove(tmp)
        raise


def mean(values):
    return sum(values) / len(values) if values else None


def trend_inverted(pairs):
    """pairs: list of (ts, accuracy). Split window in half by time; inverted
    when the recent half is materially worse than the older half."""
    if len(pairs) < 6:
        return False, None
    pairs = sorted(pairs, key=lambda x: (x[0] or datetime.min.replace(tzinfo=timezone.utc)))
    mid = len(pairs) // 2
    older = [a for _, a in pairs[:mid]]
    recent = [a for _, a in pairs[mid:]]
    o, r = mean(older), mean(recent)
    if o is None or r is None:
        return False, None
    return (r < o - TREND_INVERT_MARGIN), {"older_half": round(o, 3), "recent_half": round(r, 3)}


def now_utc():
    return datetime.now(timezone.utc)


# ---------------------------------------------------------------- score

def score_predictions(window_start):
    """Per-agent Brier over resolved predictions in the trailing window."""
    rows, bad = read_jsonl(PREDICTIONS)
    subs = {}
    for row, _ in rows:
        if row.get("type") in ("resolution", "flag", "extension"):
            continue
        rid = row.get("id")
        if rid and row.get("agent"):
            subs[rid] = row
    per_agent = defaultdict(lambda: {"briers": [], "pairs": []})
    resolved = 0
    skipped_flags = 0
    unmatched = 0
    for row, _ in rows:
        rtype = row.get("type")
        if rtype == "flag":
            skipped_flags += 1
            continue
        if rtype != "resolution":
            continue
        rid = row.get("id")
        sub = subs.get(rid)
        if sub is None:
            unmatched += 1
            continue
        brier = row.get("brier")
        ts = parse_ts(row.get("resolved_at") or row.get("ts"))
        agent = sub.get("agent")
        if not isinstance(brier, (int, float)) or agent is None:
            continue
        if ts and ts < window_start:
            continue
        resolved += 1
        per_agent[agent]["briers"].append(brier)
        per_agent[agent]["pairs"].append((ts, 1.0 - brier))
    table = {}
    for agent in sorted(per_agent):
        d = per_agent[agent]
        b = mean(d["briers"])
        table[agent] = {
            "n": len(d["briers"]),
            "brier": round(b, 4) if b is not None else None,
            "accuracy": round(1.0 - b, 4) if b is not None else None,
        }
        inv, halves = trend_inverted(d["pairs"])
        if halves:
            table[agent]["trend"] = halves
    return {
        "agents": table,
        "resolved_in_window": resolved,
        "agents_with_records": len(table),
        "resolution_rows_unmatched_to_submission": unmatched,
        "flag_rows_skipped": skipped_flags,
        "malformed_lines_skipped": bad,
        "source": PREDICTIONS,
    }


def score_decisions(window_start):
    """Per-(surface, question-name, type) accuracy: Brier for predicates,
    argmax-accuracy for choice, MAE for score. Outcomes last-wins per
    (decision_id, name)."""
    drows, dbad = read_jsonl(DECISIONS)
    orows, obad = read_jsonl(OUTCOMES)
    decisions = {}
    for row, _ in drows:
        did = row.get("id")
        if did:
            decisions[did] = row
    last_wins = {}
    seen = 0
    for row, _ in orows:
        key = (row.get("decision_id"), row.get("name"))
        if key[0] and key[1]:
            last_wins[key] = row
            seen += 1
    matched = 0
    no_decision = 0
    skipped_ts = 0
    per_key = defaultdict(lambda: {"pred": [], "acc": [], "mae": [], "pairs": []})
    for (did, name), out in sorted(last_wins.items()):
        dec = decisions.get(did)
        if dec is None:
            no_decision += 1
            continue
        ts = parse_ts(out.get("ts"))
        if ts and ts < window_start:
            skipped_ts += 1
            continue
        surface = dec.get("surface", "unknown")
        answers = {a.get("name"): a for a in dec.get("answers", [])}
        questions = {q.get("name"): q for q in dec.get("questions", [])}
        ans = answers.get(name)
        if ans is None:
            continue
        qtype = ans.get("type") or questions.get(name, {}).get("type") or "unknown"
        observed = out.get("observed")
        key = (surface, name, qtype)
        if qtype == "predicate":
            if not isinstance(observed, bool):
                continue
            p_true = (ans.get("probabilities") or {}).get("true")
            if not isinstance(p_true, (int, float)):
                continue
            y = 1.0 if observed else 0.0
            per_key[key]["pred"].append((p_true - y) ** 2)
            per_key[key]["acc"].append(1.0 if (p_true >= 0.5) == observed else 0.0)
            per_key[key]["pairs"].append((ts, 1.0 if (p_true >= 0.5) == observed else 0.0))
            matched += 1
        elif qtype == "choice":
            probs = ans.get("probabilities") or {}
            if not probs or observed is None:
                continue
            argmax = max(probs, key=lambda k: probs[k])
            obs_key = str(observed)
            per_key[key]["acc"].append(1.0 if argmax == obs_key else 0.0)
            per_key[key]["pairs"].append((ts, 1.0 if argmax == obs_key else 0.0))
            matched += 1
        elif qtype == "score":
            val = ans.get("value")
            if not isinstance(val, (int, float)) or not isinstance(observed, (int, float)):
                continue
            per_key[key]["mae"].append(abs(val - observed))
            matched += 1
    table = {}
    for (surface, name, qtype), d in sorted(per_key.items()):
        entry = {
            "surface": surface, "name": name, "type": qtype,
            "n": len(d["pred"]) + len(d["acc"]) + len(d["mae"]),
        }
        if d["pred"]:
            b = mean(d["pred"])
            entry["brier"] = round(b, 4)
            entry["accuracy"] = round(mean(d["acc"]), 4)
        elif d["acc"]:
            entry["accuracy"] = round(mean(d["acc"]), 4)
        elif d["mae"]:
            entry["mae"] = round(mean(d["mae"]), 4)
        inv, halves = trend_inverted(d["pairs"])
        if halves:
            entry["trend"] = halves
        table["%s|%s|%s" % (surface, name, qtype)] = entry
    return {
        "metrics": table,
        "outcome_rows": seen,
        "outcome_rows_matched": matched,
        "outcome_rows_without_decision_row": no_decision,
        "outcome_rows_outside_window": skipped_ts,
        "malformed_lines_skipped": {"decisions": dbad, "outcomes": obad},
        "sources": [DECISIONS, OUTCOMES],
    }


def parse_proposal_frontmatter(path):
    """Return (kind, risk) from the proposal frontmatter, or (None, None).
    First occurrence of each key in the frontmatter block is authoritative
    (a duplicate-status bug exists; same discipline applied here)."""
    try:
        with open(path, "r", encoding="utf-8") as fh:
            text = fh.read(8192)
    except OSError:
        return None, None
    if not text.startswith("---"):
        return None, None
    block = text.split("---", 2)
    fm = block[1] if len(block) > 1 else ""
    kind = risk = None
    for line in fm.splitlines():
        m = re.match(r"^kind:\s*(\S+)", line)
        if m and kind is None:
            kind = m.group(1)
        m = re.match(r"^risk:\s*(\S+)", line)
        if m and risk is None:
            risk = m.group(1)
    return kind, risk


def norm_title(s):
    return frozenset(re.findall(r"[a-z0-9]+", (s or "").lower()))


def score_proposals(window_start):
    """Verdict base rates by kind/risk. Join outcome rows to proposal files
    by exact normalized title match; unmatched rows count under 'unknown'."""
    orows, bad = read_jsonl(PROPOSAL_OUTCOMES)
    files = {}
    for path in glob.glob(os.path.join(PROPOSALS_DIR, "*.md")):
        kind, risk = parse_proposal_frontmatter(path)
        base = os.path.basename(path)
        h1 = None
        try:
            with open(path, "r", encoding="utf-8") as fh:
                for line in fh:
                    m = re.match(r"^#\s+(.+)$", line)
                    if m:
                        h1 = m.group(1)
                        break
        except OSError:
            pass
        if h1:
            files[norm_title(h1)] = {"file": base, "kind": kind, "risk": risk}
    favorable = {"accepted", "built", "accepted-modified"}
    by_risk = defaultdict(lambda: {"n": 0, "favorable": 0})
    by_kind = defaultdict(lambda: {"n": 0, "favorable": 0})
    matched_title = 0
    unmatched_title = 0
    for row, _ in orows:
        ts = parse_ts(row.get("date"))
        if ts and ts < window_start:
            continue
        action = row.get("action")
        if action is None:
            continue
        fav = 1 if action in favorable else 0
        meta = files.get(norm_title(row.get("proposal")))
        if meta is not None:
            matched_title += 1
        else:
            unmatched_title += 1
        risk = (meta or {}).get("risk") or "unknown"
        kind = (meta or {}).get("kind") or "unknown"
        by_risk[risk]["n"] += 1
        by_risk[risk]["favorable"] += fav
        by_kind[kind]["n"] += 1
        by_kind[kind]["favorable"] += fav
    def shape(d):
        out = {}
        for k in sorted(d):
            n = d[k]["n"]
            out[k] = {
                "n": n,
                "favorable": d[k]["favorable"],
                "base_rate": round(d[k]["favorable"] / n, 4) if n else None,
            }
        return out
    return {
        "by_risk": shape(by_risk),
        "by_kind": shape(by_kind),
        "outcome_rows_in_window": matched_title + unmatched_title,
        "outcome_rows_matched_to_proposal_file": matched_title,
        "outcome_rows_unmatched_title": unmatched_title,
        "proposal_files_with_h1": len(files),
        "malformed_lines_skipped": bad,
        "note": ("favorable = accepted|built|accepted-modified; rejected-false-alarm "
                 "is unfavorable. Title join is exact-normalized-token-set only — "
                 "no fuzzy pairing."),
        "source": PROPOSAL_OUTCOMES,
    }


def score_needs_josh(window_start):
    """Per-project needs-josh closure history from mission-control events.

    A needs-josh row resolves when a LATER event for the same workstream
    carries state=done|blocked|in-flight (fold: last event per workstream
    wins). Accuracy per project = fraction of resolved rows whose first
    post-needs-josh resolution was state=done. Also records within-24h
    close rate (resolution within 24h of the needs-josh row)."""
    rows, bad = read_jsonl(MISSION_EVENTS)
    events = []
    for row, _ in rows:
        ts = parse_ts(row.get("ts"))
        if ts is None:
            continue
        events.append((ts, row))
    events.sort(key=lambda x: x[0])
    total_needs_josh = 0
    for _, row in events:
        if row.get("state") == "needs-josh":
            total_needs_josh += 1
    # workstream -> last seen project (for needs-josh rows that omit project)
    ws_project = {}
    for ts, row in events:
        if row.get("project") and row.get("workstream"):
            ws_project[row["workstream"]] = row["project"]
    # fold closure outcomes: a needs-josh row resolves at the next state event
    per_project = defaultdict(lambda: {"n": 0, "done": 0, "within24h": 0, "pairs": []})
    open_rows = {}  # workstream -> (ts, project) of most recent needs-josh row
    for ts, row in events:
        ws = row.get("workstream")
        state = row.get("state")
        if row.get("event") == "note":
            continue
        if state == "needs-josh":
            project = row.get("project") or ws_project.get(ws)
            if ws and project:
                open_rows[ws] = (ts, project)
        elif state in ("done", "blocked", "in-flight") and ws in open_rows:
            opened_ts, project = open_rows.pop(ws)
            d = per_project[project]
            d["n"] += 1
            if state == "done":
                d["done"] += 1
            if ts - opened_ts <= timedelta(hours=24):
                d["within24h"] += 1
            acc = 1.0 if state == "done" else 0.0
            d["pairs"].append((ts, acc))
    table = {}
    for project in sorted(per_project):
        d = per_project[project]
        if d["n"] == 0:
            continue
        entry = {
            "n": d["n"],
            "closed_done": d["done"],
            "done_rate": round(d["done"] / d["n"], 4),
            "closed_within_24h": d["within24h"],
            "within_24h_rate": round(d["within24h"] / d["n"], 4),
        }
        inv, halves = trend_inverted(d["pairs"])
        if halves:
            entry["trend"] = halves
        table[project] = entry
    return {
        "projects": table,
        "needs_josh_rows_seen_total": total_needs_josh,
        "still_open_workstreams": len(open_rows),
        "malformed_lines_skipped": bad,
        "source": MISSION_EVENTS,
    }


def cmd_score():
    ws = now_utc() - timedelta(days=WINDOW_DAYS)
    evidence = {
        "generated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "window_days": WINDOW_DAYS,
        "window_start": ws.strftime("%Y-%m-%dT%H:%M:%SZ"),
        "predictions": score_predictions(ws),
        "decisions": score_decisions(ws),
        "proposals": score_proposals(ws),
        "needs_josh_projects": score_needs_josh(ws),
    }
    atomic_write_json(EVIDENCE_JSON, evidence)
    # stdout summary
    p = evidence["predictions"]
    print("score: evidence written -> %s" % EVIDENCE_JSON)
    print("  predictions: %d agents with Brier records (%d resolved in %dd window, %d rows unmatched)"
          % (p["agents_with_records"], p["resolved_in_window"], WINDOW_DAYS,
             p["resolution_rows_unmatched_to_submission"]))
    for agent, d in sorted(p["agents"].items()):
        print("    %-22s n=%-3d brier=%s accuracy=%s" % (agent, d["n"], d["brier"], d["accuracy"]))
    d = evidence["decisions"]
    print("  decisions: %d outcome rows matched to decision rows (%d had no decision row)"
          % (d["outcome_rows_matched"], d["outcome_rows_without_decision_row"]))
    for key, m in sorted(d["metrics"].items()):
        parts = ["n=%d" % m["n"]]
        if "brier" in m:
            parts.append("brier=%s acc=%s" % (m["brier"], m["accuracy"]))
        elif "accuracy" in m:
            parts.append("acc=%s" % m["accuracy"])
        if "mae" in m:
            parts.append("mae=%s" % m["mae"])
        print("    %-48s %s" % (key, ", ".join(parts)))
    pr = evidence["proposals"]
    print("  proposals: %d outcome rows in window (%d title-matched to proposal files)"
          % (pr["outcome_rows_in_window"], pr["outcome_rows_matched_to_proposal_file"]))
    for risk, m in sorted(pr["by_risk"].items()):
        print("    risk=%-8s n=%-3d favorable=%-3d base_rate=%s"
              % (risk, m["n"], m["favorable"], m["base_rate"]))
    nj = evidence["needs_josh_projects"]
    print("  needs-josh: %d projects with closure history (%d needs-josh rows seen, %d still open)"
          % (len(nj["projects"]), nj["needs_josh_rows_seen_total"], nj["still_open_workstreams"]))
    for proj, m in sorted(nj["projects"].items()):
        print("    %-28s n=%-3d done_rate=%s within24h=%s"
              % (proj, m["n"], m["done_rate"], m["within_24h_rate"]))
    return 0


# ---------------------------------------------------------------- authority

def eligible_for_recommend(n, accuracy, inverted):
    """Promotion rule: n>=20 AND accuracy>=0.8 AND trend not inverted.
    Returns (bool, blocked_by list)."""
    blocked = []
    if n is None or n < N_MIN:
        blocked.append("n<%d (%s<%d)" % (N_MIN, n, N_MIN))
    if accuracy is None or accuracy < ACC_MIN:
        blocked.append("accuracy<%s (%s<%s)" % (ACC_MIN, accuracy, ACC_MIN))
    if inverted:
        blocked.append("trend inverted")
    return (not blocked), blocked


def cmd_authority():
    if not os.path.exists(EVIDENCE_JSON):
        raise ValidationError("evidence.json not found at %s — run `autonomy.py score` first" % EVIDENCE_JSON)
    with open(EVIDENCE_JSON, "r", encoding="utf-8") as fh:
        ev = json.load(fh)
    classes = {}

    def add(slug, n, accuracy, brier, inverted, note=None):
        ok, blocked = eligible_for_recommend(n, accuracy, inverted)
        entry = {
            "mode": "josh-only",           # born josh-only; engine never changes this
            "eligible_mode": "recommend",  # the only rung evidence can earn; never auto-close
            "eligible": ok,
            "evidence": {
                "n": n or 0,
                "accuracy": round(accuracy, 4) if isinstance(accuracy, (int, float)) else None,
                "brier": round(brier, 4) if isinstance(brier, (int, float)) else None,
                "window_days": WINDOW_DAYS,
            },
            "promotion_rule": PROMOTION_RULE,
            "since": ev.get("generated", "")[:10],
        }
        if blocked:
            entry["promotion_blocked_by"] = blocked
        if note:
            entry["note"] = note
        classes[slug] = entry

    # needs-josh.<project> — accuracy = historical done-rate of resolutions
    for project, m in sorted(ev.get("needs_josh_projects", {}).get("projects", {}).items()):
        inv = m.get("trend") and (m["trend"]["recent_half"] < m["trend"]["older_half"] - TREND_INVERT_MARGIN)
        add("needs-josh.%s" % project, m["n"], m["done_rate"], None, inv)

    # proposal.<risk> — accuracy = favorable base rate
    for risk, m in sorted(ev.get("proposals", {}).get("by_risk", {}).items()):
        add("proposal.%s" % risk, m["n"], m["base_rate"], None, False)

    # prediction.<agent> — accuracy = 1 - mean Brier
    for agent, m in sorted(ev.get("predictions", {}).get("agents", {}).items()):
        inv = m.get("trend") and (m["trend"]["recent_half"] < m["trend"]["older_half"] - TREND_INVERT_MARGIN)
        add("prediction.%s" % agent, m["n"], m["accuracy"], m["brier"], inv)

    payload = {
        "generated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "classes": classes,
        "law": LAW,
    }
    atomic_write_json(AUTHORITY_JSON, payload)
    print("authority: %d classes born (all mode=josh-only) -> %s" % (len(classes), AUTHORITY_JSON))
    eligible = [(s, c) for s, c in classes.items() if c["eligible"]]
    print("  eligible for recommend (rule met): %d of %d" % (len(eligible), len(classes)))
    for slug, c in sorted(classes.items()):
        ev_ = c["evidence"]
        flag = "ELIGIBLE" if c["eligible"] else "blocked: " + "; ".join(c.get("promotion_blocked_by", []))
        print("    %-44s mode=%s n=%-4s acc=%s  %s"
              % (slug, c["mode"], ev_["n"], ev_["accuracy"], flag))
    return 0


# ---------------------------------------------------------------- recommend

def cmd_recommend():
    if not os.path.exists(EVIDENCE_JSON):
        raise ValidationError("evidence.json not found at %s — run `autonomy.py score` first" % EVIDENCE_JSON)
    if not os.path.exists(CLAIMS_SWEEP):
        raise ValidationError("claims sweep not found at %s" % CLAIMS_SWEEP)
    with open(EVIDENCE_JSON, "r", encoding="utf-8") as fh:
        ev = json.load(fh)
    with open(CLAIMS_SWEEP, "r", encoding="utf-8") as fh:
        sweep = json.load(fh)
    nj = sweep.get("needs_josh", {})
    projects_ev = ev.get("needs_josh_projects", {}).get("projects", {})
    # workstream -> project from mission-control evidence (workstream attribution)
    rows, _ = read_jsonl(MISSION_EVENTS)
    ws_project = {}
    for row, _ in rows:
        if row.get("project") and row.get("workstream"):
            ws_project[row["workstream"]] = row["project"]

    CONF_MIN_N = 5
    recommendations = []
    for bucket, rows_ in nj.items():
        for row in rows_:
            workstream = row.get("workstream", "")
            project = ws_project.get(workstream)
            rec = {
                "workstream": workstream,
                "jira": row.get("jira", ""),
                "bucket": bucket,
                "age_days": row.get("age_days"),
                "matched_pattern": "no-pattern",
                "evidence_ref": None,
                "confidence": None,
                "suggested_verdict": "needs-josh",
            }
            if project and project in projects_ev:
                m = projects_ev[project]
                slug = "needs-josh.%s" % project
                ref = "autonomy/evidence.json#needs_josh_projects.projects.%s (authority: %s)" % (project, slug)
                rec["evidence_ref"] = ref
                if m["n"] >= CONF_MIN_N:
                    rec["matched_pattern"] = (
                        "%d prior needs-josh rows in project '%s' resolved; %d closed done "
                        "(done_rate %.0f%%), %d within 24h (rate %.0f%%)"
                        % (m["n"], project, m["closed_done"], 100 * m["done_rate"],
                           m["closed_within_24h"], 100 * m["within_24h_rate"]))
                    if m["done_rate"] >= ACC_MIN:
                        rec["suggested_verdict"] = "done"
                        rec["confidence"] = round(m["done_rate"], 2)
                else:
                    rec["matched_pattern"] = (
                        "only %d resolved needs-josh row(s) in project '%s' — below the "
                        "n>=%d confidence floor" % (m["n"], project, CONF_MIN_N))
            recommendations.append(rec)
    payload = {
        "generated": now_utc().strftime("%Y-%m-%dT%H:%M:%SZ"),
        "sweep_generated": sweep.get("generated"),
        "open_needs_josh_rows": len(recommendations),
        "candidates": recommendations,
        "law": ("READ-ONLY against mission control. Suggestions are batch-decision "
                "candidates for Josh; the engine never closes, edits, or writes any "
                "claim store. Confidence is only emitted where n>=%d historical rows "
                "support it." % CONF_MIN_N),
    }
    atomic_write_json(RECOMMENDATIONS_JSON, payload)
    print("recommend: %d open needs-josh rows -> %s" % (len(recommendations), RECOMMENDATIONS_JSON))
    suggestable = [r for r in recommendations if r["suggested_verdict"] == "done"]
    print("  with honest pattern + verdict=done: %d; no-pattern: %d"
          % (len(suggestable), len(recommendations) - len(suggestable)))
    # short stdout table: candidates with a suggestion first, then a sample
    shown = suggestable + [r for r in recommendations if r["suggested_verdict"] != "done"][:5]
    for r in shown:
        jira = r["jira"] or "-"
        print("    %-28s %-11s age=%-5s verdict=%-10s conf=%s"
              % (r["workstream"][:28], jira, r["age_days"], r["suggested_verdict"],
                 r["confidence"] if r["confidence"] is not None else "-"))
    return 0


# ---------------------------------------------------------------- cli

def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="autonomy.py",
        description="Earned-autonomy engine: score evidence, derive the authority table, "
                    "emit batch-approve recommendations. Zero-LLM, read-only against all "
                    "ledgers; never writes mode=auto-close.",
    )
    sub = parser.add_subparsers(dest="command")
    sub.add_parser("score", help="compute evidence.json from the three ledgers + mission control")
    sub.add_parser("authority", help="derive authority.json (classes born josh-only)")
    sub.add_parser("recommend", help="emit recommendations-latest.json from the claims sweep")
    args = parser.parse_args(argv)
    try:
        if args.command == "score":
            return cmd_score()
        if args.command == "authority":
            return cmd_authority()
        if args.command == "recommend":
            return cmd_recommend()
        # default: full sequence
        rc = cmd_score()
        if rc:
            return rc
        rc = cmd_authority()
        if rc:
            return rc
        return cmd_recommend()
    except ValidationError as exc:
        print("ERROR: %s" % exc, file=sys.stderr)
        return 1


if __name__ == "__main__":
    sys.exit(main())
