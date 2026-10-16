#!/usr/bin/env python3
"""affinity-mature.py — affinity-maturation INSTRUMENTS (wave 3).

INSTRUMENTS ONLY. The maturation LOOP (variant generation, evidence-agent
re-probing, claim replacement) ships in wave 4 — it must wait until these
instruments read real data. This script never edits claims.jsonl or any claim.

Instruments:
  analyze   structured claim slots: scope, quantifier, threshold — parsed
            where parseable, flagged where not (the grammar the wave-4 loop
            will mutate: scope/quantifier/threshold ONLY, never the predicate)
  usage     grep-based usage counter for every claim across the knowledge
            tree (high-usage claims rot first; usage = maturation priority)
  fixtures  negative-fixture registry per failure class — real inputs that
            must NOT fire a class detector (autoreactivity guard). Without
            negatives, "the matured probe catches more of the class" is
            unmeasurable (titer-report.py admits fire counts are unknown).

Registry: knowledge/claims/maturations/negative-fixtures.jsonl (append-only,
schema-validated via atomic_io).

Usage:
  python3 affinity-mature.py analyze [--json]
  python3 affinity-mature.py usage [--tree PATH] [--min-files N]
  python3 affinity-mature.py fixtures --check | --seed | --add ...
  python3 affinity-mature.py --selftest
"""

import argparse
import json
import os
import re
import subprocess
import sys

HERE = os.path.dirname(os.path.abspath(__file__))
if HERE not in sys.path:
    sys.path.insert(0, HERE)

from atomic_io import atomic_append_validated, validate_row  # noqa: E402

K = os.path.expanduser("~/.claude/knowledge")
CLAIMS = os.path.join(K, "claims", "claims.jsonl")
TREE = K
FIXTURES = os.path.join(K, "claims", "maturations", "negative-fixtures.jsonl")

FIXTURE_SCHEMA = {
    "required": ["id", "ts", "failure_class", "negative_input",
                 "why_not_a_hit"],
    "timestamps": ["ts"],
}

QUANTIFIER_WORDS = ("every", "each", "all ", "any ", "never", "always",
                    "only ", "must ")
THRESHOLD_RE = re.compile(
    r"(?:[<>]=?|at least|at most|over|under|>=|<=)\s*\d+|\b\d+\s*"
    r"(?:day|days|hour|hours|minute|minutes|min|week|weeks|second|seconds|x)\b"
    r"|\b\d+\s*%|\b\d+\s*points?\b|\bcustomfield_\d+\b", re.IGNORECASE)
SCOPE_RE = re.compile(
    r"~/?[\w./-]+\.(?:md|py|json|rb|sh)\b|\b[\w-]+\.py\b|\b[a-z][a-z0-9-]+\.md\b"
    r"|\bUAT\b|\bprod(uction)?\b|\bdev\b|\brecipe[s]?\b|\bskill[s]?\b|\bVUA\b"
    r"|\bBSYS-\d+\b|\bclm-\d+\b", re.IGNORECASE)


def now_iso():
    import datetime as dt
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def load_jsonl(path):
    if not os.path.exists(path):
        return []
    rows = []
    with open(path) as f:
        for ln in f:
            ln = ln.strip()
            if ln:
                try:
                    rows.append(json.loads(ln))
                except json.JSONDecodeError:
                    print(f"WARN: malformed line skipped in {path}",
                          file=sys.stderr)
    return rows


# ---------------------------------------------------------------- analyze

def parse_slots(claim_text):
    """Extract (scope, quantifier, threshold) slots. Returns (slots, flags)."""
    text = claim_text
    low = text.lower()
    quantifier = next((q.strip() for q in QUANTIFIER_WORDS
                       if re.search(r"\b" + re.escape(q.strip()) + r"\b",
                                    low)), None)
    thresholds = sorted({m.group(0).strip() for m in THRESHOLD_RE.finditer(text)
                         }) if THRESHOLD_RE.search(text) else []
    scope = sorted({m.group(0) for m in SCOPE_RE.finditer(text)})[:8]
    flags = []
    if quantifier is None:
        flags.append("no-quantifier")
    if not thresholds:
        flags.append("no-threshold")
    if not scope:
        flags.append("no-scope-anchor")
    parseable = not flags
    slots = {"quantifier": quantifier, "thresholds": thresholds,
             "scope": scope}
    return slots, flags, parseable


def cmd_analyze(a):
    claims = load_jsonl(CLAIMS)
    if not claims:
        print(f"no claims found at {CLAIMS}")
        return 1
    out = []
    n_parse = 0
    for c in claims:
        slots, flags, parseable = parse_slots(c.get("claim", ""))
        n_parse += 1 if parseable else 0
        out.append({"id": c.get("id"), "subject": c.get("subject"),
                    "slots": slots, "parseable": parseable,
                    "flags": flags if flags else None})
    if a.json:
        print(json.dumps({"claims": len(claims), "parseable": n_parse,
                          "rows": out}, indent=1))
    else:
        print(f"claims: {len(claims)}, fully-slotted: {n_parse}, "
              f"flagged: {len(claims) - n_parse} (wave-4 loop may only mutate "
              f"parseable claims)")
        for r in out:
            mark = "OK " if r["parseable"] else "FLAG"
            s = r["slots"]
            print(f"  [{mark}] {r['id']} {r['subject']}: q={s['quantifier']} "
                  f"thr={s['thresholds'] or '-'} scope={s['scope'] or '-'}"
                  + (f" flags={r['flags']}" if r["flags"] else ""))
    return 0


# ---------------------------------------------------------------- usage

def cmd_usage(a):
    claims = load_jsonl(CLAIMS)
    if not claims:
        print(f"no claims found at {CLAIMS}")
        return 1
    results = []
    excludes = ["--exclude-dir=__pycache__", "--exclude=*.pyc",
                "--exclude=*.lock"] + \
        [f"--exclude={e}" for e in a.exclude]
    for c in claims:
        needle = c.get("subject") or c.get("id")
        try:
            proc = subprocess.run(
                ["grep", "-r", "-F", "-l"] + excludes + [needle, a.tree],
                capture_output=True, text=True, timeout=60)
            files = [f for f in proc.stdout.splitlines() if f]
        except (subprocess.TimeoutExpired, OSError) as e:
            print(f"WARN: grep failed for {needle}: {e}", file=sys.stderr)
            files = []
        results.append({"id": c.get("id"), "subject": needle,
                        "files": len(files), "paths": files[:5]})
    results.sort(key=lambda r: -r["files"])
    hot = [r for r in results if r["files"] >= a.min_files]
    print(f"claims ranked by knowledge-tree usage (grep -r -F -l, tree="
          f"{a.tree}); {len(hot)} claim(s) at >= {a.min_files} files = "
          f"wave-4 maturation priority")
    for r in results:
        print(f"  {r['files']:4d} files  {r['id']} {r['subject']}"
              + (f"  e.g. {r['paths'][0]}" if r["paths"] else ""))
    return 0


# ---------------------------------------------------------------- fixtures

SEED_FIXTURES = [
    {
        "id": "negfix-001",
        "failure_class": "three-timestamp-format",
        "negative_input": ('heartbeat row {"ts": "2026-10-12T01:41:31Z", '
                           '"job": "session-shadow"} — proper Z-suffix '
                           'ISO-8601 with tz offset'),
        "why_not_a_hit": ("a detector for the 2026-10-11 naive-timestamp "
                          "incident must NOT flag tz-valid rows; only naive "
                          "or offset-less formats are the class"),
        "source": "garden-reports/heartbeat.jsonl (live 2026-10-11 sample)",
        "source_claim": "clm-013",
        "note": "atomic_io._validate_timestamp is the canonical check",
    },
    {
        "id": "negfix-002",
        "failure_class": "truncated-jsonl-ledger",
        "negative_input": ("a long but structurally complete build-ledger.jsonl "
                           "row (2026-10-09 incident was line 4837 truncated "
                           "mid-record by a crashed writer)"),
        "why_not_a_hit": ("a truncation detector must not flag long valid "
                          "rows — the class is unparseable-by-json.loads, not "
                          "length"),
        "source": "atomic_io.py docstring (real truncation 2026-10-09)",
        "source_claim": None,
        "note": None,
    },
    {
        "id": "negfix-003",
        "failure_class": "scheduler-tick-not-send",
        "negative_input": ('heartbeat tick {"ts": "...Z", "job": '
                           '"session-shadow"} — proof a schedule fired'),
        "why_not_a_hit": ("must never be counted as a Slack send, job "
                          "success, or end-to-end completion; the 2026-10-02 "
                          "NEVER-wait-for-scheduled-jobs rule exists because "
                          "ticks were read as outcomes"),
        "source": "~/Documents/CLAUDE.md Verification Rules (live rule)",
        "source_claim": None,
        "note": None,
    },
    {
        "id": "negfix-004",
        "failure_class": "prod-write-vs-read-confusion",
        "negative_input": ("allowlisted PROD READ via workato-airo-mcp-prod "
                           "(recipe_get, job_list, data_table_list) — runs "
                           "without prompting by standing policy"),
        "why_not_a_hit": ("the prod-write confirm gate (hook 13) must not "
                          "fire on allowlisted prod READS; the class boundary "
                          "is mutation vs read, not dev vs prod"),
        "source": "~/.claude/CLAUDE.md WORKATO AIRO block (standing policy)",
        "source_claim": None,
        "note": None,
    },
]


def cmd_fixtures(a):
    if a.seed:
        existing = {r.get("id") for r in load_jsonl(FIXTURES)}
        added = 0
        for r in SEED_FIXTURES:
            if r["id"] in existing:
                continue
            atomic_append_validated(FIXTURES, {**r, "ts": now_iso()},
                                    FIXTURE_SCHEMA)
            added += 1
        print(f"fixtures --seed: added={added} (idempotent)")
        return 0
    if a.add:
        rec = {"id": a.add[0], "ts": now_iso(), "failure_class": a.add[1],
               "negative_input": a.add[2], "why_not_a_hit": a.add[3],
               "source": a.add[4] if len(a.add) > 4 else None,
               "source_claim": None, "note": None}
        atomic_append_validated(FIXTURES, rec, FIXTURE_SCHEMA)
        print(f"fixtures --add: {rec['id']} recorded")
        return 0
    # default: --check
    rows = load_jsonl(FIXTURES)
    bad = []
    for r in rows:
        errs = validate_row(r, FIXTURE_SCHEMA)
        if errs:
            bad.append((r.get("id"), errs))
    print(f"fixtures --check: {len(rows)} row(s), {len(bad)} invalid")
    for rid, errs in bad:
        print(f"  INVALID {rid}: {'; '.join(errs)}")
    if not rows:
        print(f"  registry empty — run --seed to write the real class "
              f"negatives to {FIXTURES}")
        return 1
    return 1 if bad else 0


# ---------------------------------------------------------------- selftest

def cmd_selftest(_a):
    import tempfile
    real = (globals()["CLAIMS"], globals()["FIXTURES"])
    with tempfile.TemporaryDirectory() as td:
        # analyze: two claims, one fully slotted, one flagged
        cl = os.path.join(td, "claims.jsonl")
        with open(cl, "w") as f:
            f.write(json.dumps({
                "id": "t-1", "subject": "thresholds-claim",
                "claim": "Every push reverts VUA within 30 days; verify "
                         "~/Documents/CLAUDE.md after every push"}) + "\n")
            f.write(json.dumps({
                "id": "t-2", "subject": "vague-claim",
                "claim": "It is generally better to be careful."}) + "\n")
        globals()["CLAIMS"] = cl
        import contextlib, io
        ns = argparse.Namespace(json=False)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            assert cmd_analyze(ns) == 0
        t = buf.getvalue()
        assert "fully-slotted: 1" in t and "flagged: 1" in t, t
        assert "no-threshold" in t or "FLAG" in t, t
        # fixtures: seed idempotently, check passes, add works, check catches
        # tampered row
        globals()["FIXTURES"] = os.path.join(td, "negfix.jsonl")
        assert cmd_fixtures(argparse.Namespace(seed=True, add=None)) == 0
        assert cmd_fixtures(argparse.Namespace(seed=True, add=None)) == 0
        n1 = len(load_jsonl(globals()["FIXTURES"]))
        assert cmd_fixtures(argparse.Namespace(seed=True, add=None)) == 0 \
            and len(load_jsonl(globals()["FIXTURES"])) == n1, "seed not idem"
        assert cmd_fixtures(argparse.Namespace(seed=False, add=None)) == 0
        assert cmd_fixtures(argparse.Namespace(
            seed=False,
            add=["negfix-900", "test-class", "negative input text",
                 "why not text", "selftest"])) == 0
        # tamper: missing required field must fail check
        with open(globals()["FIXTURES"], "a") as f:
            f.write(json.dumps({"id": "negfix-bad"}) + "\n")
        assert cmd_fixtures(argparse.Namespace(seed=False, add=None)) == 1, \
            "check failed to catch tampered row"
    globals()["CLAIMS"], globals()["FIXTURES"] = real
    print("selftest: PASS (slot-parse/flagging/seed-idempotence/check/"
          "add/tamper-catch)")
    return 0


def main():
    ap = argparse.ArgumentParser(
        description="Affinity-maturation INSTRUMENTS ONLY — the mutation loop "
                    "ships in wave 4, after these instruments read real data. "
                    "Never edits claims.")
    ap.add_argument("--selftest", action="store_true")
    sub = ap.add_subparsers(dest="cmd")

    p = sub.add_parser("analyze", help="structured slots per claim")
    p.add_argument("--json", action="store_true")
    p.set_defaults(fn=cmd_analyze)

    p = sub.add_parser("usage", help="grep-based claim usage counter")
    p.add_argument("--tree", default=TREE)
    p.add_argument("--min-files", dest="min_files", type=int, default=3,
                   help="files threshold for maturation priority (default 3)")
    p.add_argument("--exclude", action="append", default=[
        "dashboard.html", "board.html", "morning-brief", "loadout-"],
        help="generated surfaces to exclude from counts (default: dashboards "
             "and briefs, which embed every subject and inflate counts)")
    p.set_defaults(fn=cmd_usage)

    p = sub.add_parser("fixtures",
                       help="negative-fixture registry (default --check)")
    p.add_argument("--check", action="store_true",
                   help="validate every registry row against the schema "
                        "(the default when no other flag is given)")
    p.add_argument("--seed", action="store_true",
                   help="seed the registry with real class negatives "
                        "(idempotent)")
    p.add_argument("--add", nargs="+", metavar=("ID", "FAILURE_CLASS"),
                   help="add ID FAILURE_CLASS NEGATIVE_INPUT WHY_NOT_A_HIT "
                        "[SOURCE]")
    p.set_defaults(fn=cmd_fixtures)

    args = ap.parse_args()
    if args.selftest:
        return cmd_selftest(None)
    if not getattr(args, "fn", None):
        ap.print_help()
        return 2
    return args.fn(args)


if __name__ == "__main__":
    sys.exit(main())
