#!/usr/bin/env python3
"""user-model.py — User Model: structured preference store + context compiler.

Installs under a personal name (<user>-model.py) during kit onboarding: the
store directory follows the model name, so each user's rules, precedents,
drafts, and briefing log are private to them. The Python CLI owns all
retrieval, scoring, and briefing logging; the harness hook is a thin fail-open
shim that calls `brief` on the first prompt of a session.

Constitutional boundary: scribe + propose only. Rows with origin "proposed"
enter as drafts and are never served until the user confirms them. No LLM
anywhere in this file; retrieval is deterministic scoring.

Stdlib only, system Python (3.9-safe: no datetime.UTC, no match statement).
"""
import argparse
import json
import os
import re
import sys
import tempfile
from datetime import date, datetime, timezone

HOME = os.path.expanduser("~")
KIT_KNOWLEDGE = os.path.join(HOME, ".claude", "knowledge")


def _model_name():
    """Name the model after: USER_MODEL_NAME env -> user-model.conf ->
    script stem (when installed as <user>-model.py) -> "user"."""
    n = os.environ.get("USER_MODEL_NAME")
    if n:
        return n
    try:
        with open(os.path.join(KIT_KNOWLEDGE, "user-model.conf")) as f:
            n = f.read().strip()
            if n:
                return n
    except OSError:
        pass
    stem = os.path.splitext(os.path.basename(os.path.abspath(__file__)))[0]
    if stem.endswith("-model") and stem != "user-model":
        return stem[: -len("-model")]
    return "user"


JM_DIR = os.environ.get("USER_MODEL_DIR") or os.path.join(
    KIT_KNOWLEDGE, _model_name() + "-model")
PREFS = os.path.join(JM_DIR, "preferences.jsonl")
PRECS = os.path.join(JM_DIR, "precedents.jsonl")
DRAFTS = os.path.join(JM_DIR, "drafts.jsonl")
BRIEF_DIR = os.path.join(JM_DIR, "briefings")
BRIEF_LOG = os.path.join(BRIEF_DIR, "briefings.jsonl")
EVAL_FILE = os.path.join(JM_DIR, "eval", "correction-episodes.jsonl")

TASK_TYPES = [
    "build", "plan", "review", "triage", "docs",
    "comms", "debug", "promote", "investigate",
]

CONFIG = {
    "top_n_prefs": 8,
    "top_n_precedents": 2,
    "precedent_task_types": ["plan", "build", "review"],
    "token_target": 700,          # soft target for briefing body
    "token_cap": 800,             # hard cap; items dropped until under
    "scope_weights": {"project": 100, "task": 60, "global": 30},
    "tag_weight": 10,             # per shared tag between task signal and row
    "recency_30d": 10,
    "recency_90d": 5,
    # "born from a correction" = the row carries the tag "correction".
    "violation_boost": 25,
    "served_demote": -40,
    "demote_window_sessions": 10,  # demote if served in >= threshold of last N
    "demote_threshold": 3,
    # Every type with >=1 keyword hit is matched (best-first); [] = untyped.
    # Untyped prompts may still see task-scoped rows at untyped_task_weight,
    # so a task row with strong tag overlap can surface on an untyped ask.
    "untyped_task_weight": 20,
    "task_keywords": {
        "plan": ["plan", "design", "architect", "spec", "approach", "proposal"],
        "build": ["build", "implement", "scaffold", "wire", "construct"],
        "review": ["review", "red-team", "audit", "inspect"],
        "triage": ["triage", "ticket", "jira", "bsys", "btsup"],
        "docs": ["document", "confluence", "write-up", "runbook", "readme"],
        "comms": ["slack", "email", "message", "reply", "announce", "post",
                  "comment", "draft"],
        "debug": ["debug", "broken", "failing", "error", "autopsy", "flip",
                  "flag", "toggle", "timeout", "missing", "disappeared"],
        "promote": ["promote", "promotion", "deploy", "manifest", "production"],
        "investigate": ["investigate", "research", "dig into", "find out"],
    },
}

STOPWORDS = set(
    "the a an and or of to in for on with this that it is are be how what "
    "when why can could should would do does did me my your we you i".split()
)


# ---- store primitives -------------------------------------------------------

def load_rows(path):
    """Read a JSONL store; malformed rows are skipped, never fatal."""
    rows = []
    skipped = 0
    try:
        with open(path, "r") as f:
            for line in f:
                line = line.strip()
                if not line:
                    continue
                try:
                    rows.append(json.loads(line))
                except json.JSONDecodeError:
                    skipped += 1
    except FileNotFoundError:
        pass
    if skipped:
        print("user-model: skipped %d malformed row(s) in %s" % (skipped, path),
              file=sys.stderr)
    return rows


def append_row(path, row):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "a") as f:
        f.write(json.dumps(row, sort_keys=True) + "\n")


def rewrite_rows(path, rows):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    with os.fdopen(fd, "w") as f:
        for r in rows:
            f.write(json.dumps(r, sort_keys=True) + "\n")
    os.replace(tmp, path)


def next_id(path, prefix):
    top = 0
    for r in load_rows(path):
        m = re.match(r"^%s-(\d+)$" % prefix, str(r.get("id", "")))
        if m:
            top = max(top, int(m.group(1)))
    return "%s-%03d" % (prefix, top + 1)


def find_row(rows, rid):
    for r in rows:
        if r.get("id") == rid:
            return r
    return None


# ---- scoring ----------------------------------------------------------------

def tokenize(text):
    words = re.findall(r"[a-z0-9][a-z0-9-]+", text.lower())
    return [w for w in words if w not in STOPWORDS]


def classify_task(text):
    """Keyword scoring; returns all matched task types, most-hits first.

    Multi-type by design: 'post an update to the BSYS ticket' is both comms
    and triage, and a single-winner classifier starves the loser's rules.
    Empty list = untyped.
    """
    low = text.lower()
    scored = []
    for ttype in TASK_TYPES:
        hits = 0
        for kw in CONFIG["task_keywords"].get(ttype, []):
            hits += len(re.findall(r"\b" + re.escape(kw) + r"\b", low))
        if hits:
            scored.append((hits, ttype))
    scored.sort(key=lambda t: -t[0])
    return [t for _, t in scored]


def infer_project(cwd):
    """Project slug from cwd: nearest git toplevel basename, else cwd basename."""
    if not cwd:
        return None
    d = os.path.abspath(os.path.expanduser(cwd))
    while True:
        if os.path.isdir(os.path.join(d, ".git")):
            return os.path.basename(d)
        parent = os.path.dirname(d)
        if parent == d:
            return os.path.basename(os.path.abspath(os.path.expanduser(cwd))) or None
        d = parent


def days_since(iso_date):
    try:
        return (date.today() - date.fromisoformat(str(iso_date)[:10])).days
    except (ValueError, TypeError):
        return 9999


def served_session_counts():
    """{pref_id: number of the last N briefed sessions that included it}."""
    rows = load_rows(BRIEF_LOG)
    sessions = []
    seen = set()
    for r in reversed(rows):
        sid = r.get("session_id") or "unknown"
        if sid not in seen:
            seen.add(sid)
            sessions.append(r)
        if len(sessions) >= CONFIG["demote_window_sessions"]:
            break
    counts = {}
    for r in sessions:
        for pid in r.get("served_pref_ids", []):
            counts[pid] = counts.get(pid, 0) + 1
    return counts


def row_eligible(row, project, task_types):
    """Scope weight, or None if out of scope. Global always serves; project
    rows need an exact project match; task rows serve when their type is among
    the matched types, or weakly when the prompt is untyped."""
    scope = row.get("scope", "global")
    if scope == "global":
        return CONFIG["scope_weights"]["global"]
    if scope.startswith("project:"):
        return CONFIG["scope_weights"]["project"] if scope[8:] == project else None
    if scope.startswith("task:"):
        if scope[5:] in task_types:
            return CONFIG["scope_weights"]["task"]
        return None if task_types else CONFIG["untyped_task_weight"]
    return CONFIG["scope_weights"]["global"]


def score_row(row, task_tokens, project, task_types, demote_counts, use_demote):
    base = row_eligible(row, project, task_types)
    if base is None:
        return None
    tags = set(row.get("tags", []))
    overlap = len(tags.intersection(task_tokens))
    score = base + CONFIG["tag_weight"] * overlap
    age = days_since(row.get("last_confirmed"))
    if age <= 30:
        score += CONFIG["recency_30d"]
    elif age <= 90:
        score += CONFIG["recency_90d"]
    if "correction" in tags and overlap > 0:
        score += CONFIG["violation_boost"]
    # Phase 1 demote is serve-count only; the "with no violation" clause needs
    # the Phase 2 correction join and is deliberately not approximated here.
    if use_demote and demote_counts.get(row.get("id"), 0) >= CONFIG["demote_threshold"]:
        score += CONFIG["served_demote"]
    return score


def est_tokens(text):
    return len(text) // 4


# ---- briefing ---------------------------------------------------------------

def build_briefing(task, project=None, cwd=None, use_demote=True):
    """Return (markdown, served_pref_ids, served_prec_ids). Empty string = no-op."""
    task = (task or "").strip()
    if not task:
        return "", [], []
    if project is None:
        project = infer_project(cwd or "")
    task_types = classify_task(task)
    task_tokens = set(tokenize(task))
    demote_counts = served_session_counts() if use_demote else {}

    scored = []
    for row in load_rows(PREFS):
        if row.get("status") != "active":
            continue
        s = score_row(row, task_tokens, project, task_types, demote_counts, use_demote)
        if s is not None:
            scored.append((s, row))
    scored.sort(key=lambda t: (-t[0], t[1].get("id", "")))

    header = "--- [user-model] session briefing (task: %s | project: %s) ---" % (
        "+".join(task_types[:2]) if task_types else "untyped",
        project or "unknown")
    lines = [header]
    served_prefs = []
    for _, row in scored[: CONFIG["top_n_prefs"]]:
        rule = row.get("normalized_rule") or row.get("statement", "")
        lines.append("- %s (%s): %s" % (row.get("id", "?"), row.get("scope", "global"), rule))
        served_prefs.append(row.get("id"))

    served_precs = []
    if any(t in CONFIG["precedent_task_types"] for t in task_types):
        prec_scored = []
        for row in load_rows(PRECS):
            tags = set(row.get("context_tags", []))
            overlap = len(tags.intersection(task_tokens))
            recency = 1 if days_since(row.get("date")) <= 90 else 0
            prec_scored.append((overlap * 10 + recency, row))
        prec_scored.sort(key=lambda t: (-t[0], t[1].get("id", "")))
        picked = [r for s, r in prec_scored if s > 0][: CONFIG["top_n_precedents"]]
        if picked:
            lines.append("Precedents:")
            for row in picked:
                lines.append("- %s (%s): chose \"%s\" — %s" % (
                    row.get("id", "?"), row.get("date", "?"),
                    row.get("chosen", "?"), row.get("reason", "")))
                served_precs.append(row.get("id"))

    if not served_prefs and not served_precs:
        return "", [], []
    lines.append("---")

    # Hard token cap: drop lowest-ranked items (never the header) until under.
    while est_tokens("\n".join(lines)) > CONFIG["token_cap"] and len(lines) > 2:
        drop_at = len(lines) - 2  # last content line, above the closing ---
        dropped = lines.pop(drop_at)
        m = re.match(r"- ((?:pref|prec)-\d+)", dropped)
        if m and m.group(1) in served_prefs:
            served_prefs.remove(m.group(1))
        if m and m.group(1) in served_precs:
            served_precs.remove(m.group(1))
    return "\n".join(lines), served_prefs, served_precs


def log_briefing(session_id, task, served_prefs, served_precs, body):
    os.makedirs(BRIEF_DIR, exist_ok=True)
    append_row(BRIEF_LOG, {
        "ts": datetime.now(timezone.utc).isoformat(),
        "session_id": session_id or "unknown",
        "task_signal_hash": abs(hash(task)) % (10 ** 10),
        "served_pref_ids": served_prefs,
        "served_prec_ids": served_precs,
        "token_estimate": est_tokens(body),
    })


# ---- row construction -------------------------------------------------------

def validate_scope(scope):
    if scope == "global":
        return scope
    m = re.match(r"^(project|task):(.+)$", scope or "")
    if not m:
        raise SystemExit("invalid scope %r (want global | project:<slug> | task:<type>)" % scope)
    if m.group(1) == "task" and m.group(2) not in TASK_TYPES:
        raise SystemExit("unknown task type %r (allowed: %s)" % (m.group(2), ", ".join(TASK_TYPES)))
    return scope


def make_pref_row(args, status, origin):
    return {
        "id": next_id(PREFS if status == "active" else DRAFTS, "pref"),
        "statement": args.statement,
        "normalized_rule": args.rule or args.statement,
        "origin": origin,
        "status": status,
        "scope": validate_scope(args.scope),
        "tags": [t.strip().lower() for t in (args.tags or "").split(",") if t.strip()],
        "evidence": [{"source": args.evidence_source or "in-session",
                      "ref": args.evidence_ref or "",
                      "date": date.today().isoformat()}],
        "created": date.today().isoformat(),
        "last_confirmed": date.today().isoformat(),
        "supersedes": [],
        "contradicts": [],
    }


def contradiction_screen(new_row):
    """Cheap zero-LLM screen: same-scope active rows with >=50% tag Jaccard."""
    new_tags = set(new_row.get("tags", []))
    if not new_tags:
        return []
    candidates = []
    for r in load_rows(PREFS):
        if r.get("status") != "active" or r.get("scope") != new_row.get("scope"):
            continue
        tags = set(r.get("tags", []))
        union = tags | new_tags
        if union and len(tags & new_tags) / len(union) >= 0.5:
            candidates.append(r.get("id"))
    return candidates


# ---- subcommands --------------------------------------------------------------

def cmd_brief(args):
    try:
        body, prefs, precs = build_briefing(
            args.task, project=args.project, cwd=args.cwd, use_demote=not args.no_demote)
        if body:
            print(body)
            if not args.no_log:
                log_briefing(args.session_id, args.task, prefs, precs, body)
    except Exception as e:  # fail open: briefing must never break a prompt
        print("user-model brief failed open: %s" % e, file=sys.stderr)
        return 0
    return 0


def cmd_add(args):
    row = make_pref_row(args, "active", "stated")
    append_row(PREFS, row)
    print("added %s (active)" % row["id"])
    candidates = contradiction_screen(row)
    if candidates:
        print("review candidates (same scope, tag overlap >=50%%): %s"
              % ", ".join(candidates))
    return 0


def cmd_add_draft(args):
    row = make_pref_row(args, "draft", "proposed")
    row["proposed_by"] = args.proposed_by or "in-session"
    row["proposed_at"] = datetime.now(timezone.utc).isoformat()
    append_row(DRAFTS, row)
    print("drafted %s (awaits user confirmation)" % row["id"])
    return 0


def cmd_review_list(args):
    drafts = load_rows(DRAFTS)
    pending = [d for d in drafts if d.get("status") == "draft"]
    if not pending:
        print("no drafts awaiting confirmation")
        return 0
    for d in pending:
        print("%s [%s] (%s, proposed by %s)" % (
            d.get("id"), d.get("scope"), d.get("normalized_rule", "")[:100],
            d.get("proposed_by", "?")))
    return 0


def cmd_confirm(args):
    drafts = load_rows(DRAFTS)
    row = find_row(drafts, args.id)
    if not row or row.get("status") != "draft":
        raise SystemExit("no pending draft %s" % args.id)
    drafts.remove(row)
    rewrite_rows(DRAFTS, drafts)
    row["status"] = "active"
    row["last_confirmed"] = date.today().isoformat()
    row["id"] = next_id(PREFS, "pref")  # active rows get canonical pref ids
    append_row(PREFS, row)
    print("confirmed: now active as %s" % row["id"])
    return 0


def cmd_supersede(args):
    rows = load_rows(PREFS)
    old = find_row(rows, args.id)
    new = find_row(rows, args.by)
    if not old or not new:
        raise SystemExit("supersede needs two existing preference ids")
    old["status"] = "superseded"
    if args.id not in new.setdefault("supersedes", []):
        new["supersedes"].append(args.id)
    rewrite_rows(PREFS, rows)
    print("%s superseded by %s" % (args.id, args.by))
    return 0


def cmd_retract(args):
    rows = load_rows(PREFS)
    row = find_row(rows, args.id)
    if not row:
        raise SystemExit("no preference %s" % args.id)
    row["status"] = "retracted"
    rewrite_rows(PREFS, rows)
    print("%s retracted" % args.id)
    return 0


def cmd_eval(args):
    """Correction-episode recall@N: does brief() surface the preventing rule?"""
    episodes = load_rows(EVAL_FILE)
    if not episodes:
        print("no eval episodes at %s" % EVAL_FILE)
        return 1
    top_n = CONFIG["top_n_prefs"]
    passed = 0
    for ep in episodes:
        _, served, _ = build_briefing(
            ep.get("task_signal", ""), project=ep.get("project"),
            use_demote=False)  # raw retrieval: deterministic given the store
        expected = ep.get("expected_pref_ids", [])
        hit = all(pid in served[:top_n] for pid in expected)
        passed += 1 if hit else 0
        print("%s %s (expected %s, served %s)" % (
            "PASS" if hit else "MISS", ep.get("episode_id", "?"),
            ",".join(expected), ",".join(served[:top_n])))
    recall = passed / len(episodes)
    print("recall@%d: %.3f (%d/%d episodes)" % (top_n, recall, passed, len(episodes)))
    return 0


def main():
    p = argparse.ArgumentParser()
    sub = p.add_subparsers(dest="cmd", required=True)

    b = sub.add_parser("brief")
    b.add_argument("--task", default="")
    b.add_argument("--project", default=None)
    b.add_argument("--cwd", default="")
    b.add_argument("--session-id", default="")
    b.add_argument("--no-log", action="store_true")
    b.add_argument("--no-demote", action="store_true")
    b.set_defaults(fn=cmd_brief)

    for name, fn in [("add", cmd_add), ("add-draft", cmd_add_draft)]:
        a = sub.add_parser(name)
        a.add_argument("--statement", required=True)
        a.add_argument("--rule", default=None)
        a.add_argument("--scope", default="global")
        a.add_argument("--tags", default="")
        a.add_argument("--evidence-source", default=None)
        a.add_argument("--evidence-ref", default=None)
        if name == "add-draft":
            a.add_argument("--proposed-by", default=None)
        a.set_defaults(fn=fn)

    r = sub.add_parser("review-list")
    r.set_defaults(fn=cmd_review_list)
    c = sub.add_parser("confirm")
    c.add_argument("id")
    c.set_defaults(fn=cmd_confirm)
    s = sub.add_parser("supersede")
    s.add_argument("id")
    s.add_argument("--by", required=True)
    s.set_defaults(fn=cmd_supersede)
    t = sub.add_parser("retract")
    t.add_argument("id")
    t.set_defaults(fn=cmd_retract)
    e = sub.add_parser("eval")
    e.set_defaults(fn=cmd_eval)

    args = p.parse_args()
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
