#!/usr/bin/env python3
"""triage-decide.py — the ONE approval mechanism for triage findings.

The queue lives at knowledge/triage/queue.jsonl (one JSON object per
finding; agents APPEND findings, only this script changes status). Every
decision is also appended to garden-reports/triage-outcomes.jsonl
(append-only audit trail — the mirror of proposal-outcomes.jsonl; the
gardener's Phase 0 and the watchers' taste-matching read it).

Usage:
  triage-decide.py list                                  show open findings
  triage-decide.py <slug> accept ["note"] [--jira KEY]   accepted (filed under KEY if given)
  triage-decide.py <slug> filed  "note"   --jira KEY     story/bug created -> status: filed
  triage-decide.py <slug> build  ["note"]                built (dev-scoped work done) -> status: built
  triage-decide.py <slug> reject ["note"]                rejected -> status: rejected
  triage-decide.py <slug> defer  ["note"]                deferred -> status: deferred

<slug> is any unique fragment of the finding's slug field.

NEVER hand-edit the queue: status changes go through this script so the
outcomes ledger stays complete. Findings are APPENDED by their source
agent (watchdog, regression harness, gardener, estate-architect, cortex,
jira-autotriage) as one JSON line:
  {"ts":"...","slug":"kebab-slug","kind":"bugfix|playbook|test|hygiene|build",
   "source":"workato-watchdog","title":"one line","evidence":"path or job id",
   "work":"the proposed fix, one line","points":2,"status":"open"}
"""
import json, os, re, sys, datetime as dt
from atomic_io import atomic_append, atomic_append_validated

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
QUEUE = os.environ.get("TRIAGE_QUEUE", os.path.join(K, "triage", "queue.jsonl"))
OUTCOMES = os.environ.get("TRIAGE_OUTCOMES", os.path.join(K, "garden-reports", "triage-outcomes.jsonl"))

FM = {"accept": "accepted", "reject": "rejected", "defer": "deferred",
      "build": "built", "filed": "filed", "reopen": "open"}

# allowed transitions: final states (built, rejected) are terminal;
# deferred can be re-decided later; accepted can still be built or filed.
ALLOWED = {
    "accept": {"open", "deferred"},
    "reject": {"open", "deferred", "accepted"},
    "defer": {"open"},
    "build": {"open", "accepted", "filed"},
    "filed": {"open", "accepted"},
    # Josh-ordered reversal of a terminal verdict (2026-10-14, decisions-UAT
    # re-adjudication): back to open for a fresh decision, audit-logged like
    # any other action. Only ever fired by Josh's explicit call.
    "reopen": {"built", "rejected", "accepted"},
}


# statuses this recorder can issue; anything else in the queue is drift
# (e.g. an agent hand-writing "done") and fails the read loudly.
VALID_STATUSES = {"open", "accepted", "filed", "built", "rejected", "deferred"}


def load():
    if not os.path.exists(QUEUE):
        sys.exit(f"no queue at {QUEUE} (agents append findings there first)")
    rows = []
    with open(QUEUE) as fh:
        for n, line in enumerate(fh, 1):
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except json.JSONDecodeError:
                sys.exit(f"{QUEUE}:{n}: not valid JSON — fix by hand or restore from git")
            st = row.get("status", "open")
            if st not in VALID_STATUSES:
                # self-blocking corruption (a 'blocked' status once wedged the
                # whole queue: the validator refused to load, so the script could
                # never repair the row it told us to repair through it). Coerce
                # to open and warn; the next save persists the normalized status.
                print(f"NOTE: {QUEUE}:{n}: unknown status '{st}' on "
                      f"'{row.get('slug', '?')}' — normalized to 'open' "
                      f"(valid: {', '.join(sorted(VALID_STATUSES))})", file=sys.stderr)
                row["status"] = "open"
                st = "open"
            rows.append(row)
    return rows


def find(rows, slug):
    hits = [r for r in rows if r.get("slug", "") == slug] or \
           [r for r in rows if slug in r.get("slug", "")]
    if not hits:
        sys.exit(f"no finding matches '{slug}'")
    if len(hits) > 1:
        distinct = {h.get("slug", "") for h in hits}
        if len(distinct) > 1:
            sys.exit(f"ambiguous '{slug}': " + ", ".join(sorted(distinct)))
        # duplicate seed (same slug seeded twice): one logical finding —
        # the verdict fans out to every row on save; warn so dedupe gets fixed.
        print(f"NOTE: {len(hits)} rows share slug '{slug}' (duplicate seed); "
              f"verdict applies to all — dedupe belongs to the seeders", file=sys.stderr)
    return hits


def save(rows):
    tmp = QUEUE + ".tmp"
    with open(tmp, "w") as fh:
        for r in rows:
            fh.write(json.dumps(r, ensure_ascii=False) + "\n")
    os.replace(tmp, QUEUE)


TRIAGE_OUTCOME_SCHEMA = {
    "required": ["date", "finding", "slug", "action", "by"],
    "enums": {"action": {"built", "accepted", "rejected", "filed", "deferred", "open"}},
    # date is a YYYY-MM-DD date field, not a tz timestamp — regex-guarded below
}


def log_outcome(row, action, note, jira):
    os.makedirs(os.path.dirname(OUTCOMES), exist_ok=True)
    rec = {"date": dt.date.today().isoformat(), "finding": row.get("title", ""),
           "slug": row.get("slug", ""), "source": row.get("source", ""),
           "action": action, "notes": note or "", "jira": jira or "",
           "by": "josh (triage-decide)"}
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", rec["date"]):
        raise ValueError(f"refused: bad date format {rec['date']!r}")
    atomic_append_validated(OUTCOMES, rec, TRIAGE_OUTCOME_SCHEMA)


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "list"):
        rows = load() if os.path.exists(QUEUE) else []
        open_rows = [r for r in rows if r.get("status") == "open"]
        if not open_rows:
            print("triage queue: nothing open.")
        for r in open_rows:
            age = ((dt.date.today() - dt.date.fromisoformat(r["ts"][:10])).days
                   if r.get("ts") else 0)
            urg = r.get("urgency", "")
            jira = f", {r['jira']}" if r.get("jira") else ""
            print(f"[{r.get('kind','?')}{'/' + urg if urg else ''}] {r['slug']} "
                  f"(age {age}d, {r.get('points','?')}pts, source {r.get('source','?')}{jira}): "
                  f"{r.get('title','')} | {r.get('work','')}")
        print(f"queue: {len(open_rows)} open / {len(rows)} total at {QUEUE}")
        return
    # flags: --jira KEY may appear anywhere after the action
    jira = ""
    if "--jira" in args:
        i = args.index("--jira")
        if i + 1 >= len(args):
            sys.exit("--jira needs a value")
        jira = args[i + 1]
        args = args[:i] + args[i + 2:]
    if len(args) < 2 or args[1] not in FM:
        sys.exit(__doc__)
    slug, action = args[0], args[1]
    note = args[2] if len(args) > 2 else ""
    if action == "filed" and not (jira or note):
        sys.exit("'filed' requires --jira KEY (the story/bug key)")
    rows = load()
    hits = find(rows, slug)
    now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    # Per-row fan-out: apply the action to every row whose current state
    # allows it; skip rows already in a final state that disallows it with a
    # note instead of exiting. 2026-10-11 fix: the old all-or-nothing exit
    # left duplicate open rows unclosable whenever a final-state row shared
    # the slug (49 duplicates re-filed overnight by the terminal-slug gap).
    changed = 0
    skipped = 0
    for row in hits:
        cur = row.get("status", "open")
        if cur not in ALLOWED[action]:
            if cur == FM[action]:
                skipped += 1
                continue
            # Terminal-state row sharing the slug (duplicate seed): skip it,
            # don't abort the fan-out — the open rows still need the verdict.
            print(f"NOTE: skipping {slug} row already in terminal state '{cur}'",
                  file=sys.stderr)
            skipped += 1
            continue
        row["status"] = FM[action]
        row["decided_ts"] = now
        changed += 1
    if changed == 0 and skipped > 0:
        # Idempotent re-record: every matching row already sits in the exact
        # target state — nothing to do, not an error.
        print(f"no-op: {slug} already {FM[action]} on all {skipped} matching rows")
        return 0
    row = hits[0]
    if jira:
        row["jira"] = jira
    if note:
        row["note"] = note
    save(rows)
    log_outcome(row, FM[action], note, jira)
    line = f"logged: {row['slug']} -> {FM[action]}"
    if jira:
        line += f" ({jira})"
    if note:
        line += f' — {note}'
    print(line)
    print("next: re-run 'list' or record the build when it lands (build)")


if __name__ == "__main__":
    main()
