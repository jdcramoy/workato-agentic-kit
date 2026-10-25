#!/usr/bin/env python3
"""triage-decide.py — the ONE approval mechanism for triage findings.

The queue lives at knowledge/triage/queue.jsonl (one JSON object per
finding; agents APPEND findings, only this script changes status). Every
decision is also appended to garden-reports/triage-outcomes.jsonl
(append-only audit trail — the mirror of proposal-outcomes.jsonl; the
gardener's Phase 0 and the watchers' taste-matching read it).

Usage:
  triage-decide.py list                                  show open findings
  triage-decide.py sync                                  ingest mission-control needs-josh rows as kind=decision cards
  triage-decide.py <slug> accept ["note"] [--jira KEY]   accepted (filed under KEY if given)
  triage-decide.py <slug> filed  "note"   --jira KEY     story/bug created -> status: filed
  triage-decide.py <slug> build  ["note"]                built (dev-scoped work done) -> status: built
  triage-decide.py <slug> reject ["note"]                rejected -> status: rejected
  triage-decide.py <slug> defer  ["note"]                deferred -> status: deferred

<slug> is any unique fragment of the finding's slug field.

mc- decision rows (synced from mission-control needs-josh, kind=decision)
write their verdict back: any final disposition appends a superseding
mission-control event closing the registry row; defer leaves it open.

NEVER hand-edit the queue: status changes go through this script so the
outcomes ledger stays complete. Findings are APPENDED by their source
agent (watchdog, regression harness, gardener, estate-architect, cortex,
jira-autotriage) as one JSON line:
  {"ts":"...","slug":"kebab-slug","kind":"bugfix|playbook|test|hygiene|build",
   "source":"workato-watchdog","title":"one line","evidence":"path or job id",
   "work":"the proposed fix, one line","points":2,"status":"open"}
"""
import json, os, re, subprocess, sys, datetime as dt
from atomic_io import atomic_append, atomic_append_validated

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
QUEUE = os.environ.get("TRIAGE_QUEUE", os.path.join(K, "triage", "queue.jsonl"))
OUTCOMES = os.environ.get("TRIAGE_OUTCOMES", os.path.join(K, "garden-reports", "triage-outcomes.jsonl"))
VERDICT_REASONS = os.path.join(K, "triage", "verdict-reasons.jsonl")
MC_LOG = os.path.join(K, "mission-control", "events.jsonl")
MC_SCRIPT = os.path.join(K, "scripts", "mission-control.py")

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


def sync_mc():
    """Ingest mission-control needs-josh rows as kind=decision queue rows
    (2026-10-23, Josh-approved /triage integration): every open registry
    decision renders as a card in ONE queue, and a verdict on an mc- row
    writes back a superseding mission-control event so the registry row
    closes too. Idempotent: a workstream already in the queue is never
    re-ingested."""
    if not os.path.exists(MC_LOG):
        sys.exit(f"no mission-control log at {MC_LOG}")
    latest = {}
    with open(MC_LOG, errors="replace") as fh:
        for line in fh:
            line = line.strip()
            if not line:
                continue
            try:
                e = json.loads(line)
            except json.JSONDecodeError:
                continue
            w = e.get("workstream", "")
            if w:
                latest[w] = e
    open_rows = [r for r in latest.values() if r.get("state") == "needs-josh"]
    rows = load()
    existing = {r.get("slug", "") for r in rows}
    appended = 0
    refreshed = 0
    for r in open_rows:
        ws = r["workstream"]
        slug = f"mc-{ws}"
        # evidence points at the events file itself — a real path, so the
        # mandatory evidence gate resolves it (no #fragment: the checker
        # treats it as part of the path and fails the existence test)
        evidence = MC_LOG
        if slug in existing:
            # refresh our own rows' evidence format in place (the recorder
            # is the only writer of mc- rows; never touches verdict fields)
            for q in rows:
                if q.get("slug") == slug and q.get("evidence") != evidence:
                    q["evidence"] = evidence
                    refreshed += 1
            continue
        decision_txt = r.get("needs") or r.get("what") or "(no decision text)"
        row = {"ts": r.get("ts", ""), "slug": slug, "kind": "decision",
               "source": "mission-control",
               "title": decision_txt[:200],
               "evidence": evidence,
               "work": decision_txt[:400], "jira": r.get("jira", ""),
               "status": "open"}
        atomic_append(QUEUE, row)
        existing.add(slug)
        appended += 1
    if refreshed:
        save(rows)
    print(f"sync: {appended} mission-control needs-josh row(s) ingested "
          f"as decision cards ({len(open_rows) - appended} already in queue,"
          f" {refreshed} evidence refreshed)")


def mc_write_back(workstream, action, note):
    """Verdict write-back for mc- decision rows: a final disposition closes
    the mission-control row with a superseding event; reopen re-raises it.
    Defer deliberately does NOT write back — the decision stays open in the
    registry and re-renders at the next triage pass."""
    if action == "reopen":
        what = f"re-raised by triage reopen: {note or 'no note'} (decision back in needs-josh)"
        subprocess.run([sys.executable, MC_SCRIPT, "add", "--event", "state",
                        "--workstream", workstream, "--state", "needs-josh",
                        "--what", what, "--why", "triage verdict write-back (reopen re-raises the registry row)",
                        "--end", "decision re-opened; renders again at next triage",
                        "--by", "triage-decide"], capture_output=True, text=True)
        return
    acts = {"reject": "REJECTED", "build": "BUILT (dev work executed)",
            "filed": "FILED (story/bug created)", "accept": "ACCEPTED (queued for later work)"}
    if action not in acts:
        return  # defer / unknown: registry row stays open
    what = f"triage verdict {acts[action]}: {note or 'no note'}"
    if len(what) < 20:
        what += " (recorded by the triage-decide write-back)"
    subprocess.run([sys.executable, MC_SCRIPT, "add", "--event", "closeout",
                    "--workstream", workstream, "--state", "done",
                    "--what", what, "--why",
                    "triage verdict write-back: needs-josh decisions render as /triage decision cards (2026-10-23 integration)",
                    "--end", "decision made; row closed; re-raise by appending a fresh event",
                    "--by", "triage-decide"], capture_output=True, text=True)


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
    if args and args[0] == "sync":
        sync_mc()
        return
    if not args or args[0] in ("-h", "--help", "list"):
        rows = load() if os.path.exists(QUEUE) else []
        open_rows = [r for r in rows if r.get("status") == "open"]
        if not open_rows:
            print("triage queue: nothing open.")
        # 2026-10-23 (jev-replica): every open card carries its assembled
        # STATE block (lane semantics, prior decisions, sibling verdicts,
        # ticket coverage, age) — triage-state.py, as_of=now. Failure here
        # must never wedge the queue: degrade to a one-line note.
        TS = None
        if os.environ.get("TRIAGE_STATE", "on") != "off":
            try:
                import importlib.util
                _spec = importlib.util.spec_from_file_location(
                    "triage_state",
                    os.path.join(os.path.dirname(os.path.abspath(__file__)),
                                 "triage-state.py"))
                TS = importlib.util.module_from_spec(_spec)
                _spec.loader.exec_module(TS)
                ts_idx = TS.build_index(rows)
                ts_now = dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
            except Exception as e:
                TS = None
                print(f"NOTE: state assembly unavailable ({e})", file=sys.stderr)
        for r in open_rows:
            age = ((dt.date.today() - dt.date.fromisoformat(r["ts"][:10])).days
                   if r.get("ts") else 0)
            urg = r.get("urgency", "")
            jira = f", {r['jira']}" if r.get("jira") else ""
            print(f"[{r.get('kind','?')}{'/' + urg if urg else ''}] {r['slug']} "
                  f"(age {age}d, {r.get('points','?')}pts, source {r.get('source','?')}{jira}): "
                  f"{r.get('title','')} | {r.get('work','')}")
            if TS:
                try:
                    st = TS.state_block(r["slug"], r, ts_idx, as_of=ts_now)
                    for ln in TS.render_compact(st).splitlines():
                        print(f"    {ln}")
                except Exception as e:
                    print(f"    STATE: unavailable ({str(e)[:100]})")
        print(f"queue: {len(open_rows)} open / {len(rows)} total at {QUEUE}")
        return
    # flags: --jira KEY / --reason CODE may appear anywhere after the action
    jira = ""
    if "--jira" in args:
        i = args.index("--jira")
        if i + 1 >= len(args):
            sys.exit("--jira needs a value")
        jira = args[i + 1]
        args = args[:i] + args[i + 2:]
    # 2026-10-24 (jev-replica lever 3): reason codes turn verdicts into
    # explanations. The recording agent infers the code from Josh's note when
    # he doesn't state one — zero extra taps for him, structured corpus for
    # the judge. Canonical codes below; unknown codes pass through tagged.
    reason = ""
    if "--reason" in args:
        i = args.index("--reason")
        if i + 1 >= len(args):
            sys.exit("--reason needs a value (stale|covered|not-mine|done|"
                     "not-valuable|valuable|cheap-win|blocks-other|other)")
        reason = args[i + 1]
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
    if reason:
        REASONS = {"stale", "covered", "not-mine", "done", "not-valuable",
                   "valuable", "cheap-win", "blocks-other", "other"}
        atomic_append(VERDICT_REASONS,
                      {"ts": now, "slug": row["slug"], "action": FM[action],
                       "reason": reason, "note": note or "",
                       "reason_source": "explicit" if reason in REASONS
                       else "freeform",
                       "by": "josh (triage-decide)"})
    if row["slug"].startswith("mc-"):
        mc_write_back(row["slug"][3:], action, note)
    line = f"logged: {row['slug']} -> {FM[action]}"
    if jira:
        line += f" ({jira})"
    if note:
        line += f' — {note}'
    print(line)
    print("next: re-run 'list' or record the build when it lands (build)")


if __name__ == "__main__":
    main()
