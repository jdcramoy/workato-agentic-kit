#!/usr/bin/env python3
"""proposal-decide.py — the ONE approval mechanism for dreamer proposals.

Canonical flow: appends to garden-reports/proposal-outcomes.jsonl (append-only
ledger) and updates the proposal file's frontmatter status. Everything else
(pipeline digest, morning brief, dashboard, gardener) reads from these.

Usage:
  proposal-decide.py <slug> accept  ["note"]   approve -> status: accepted
  proposal-decide.py <slug> reject  ["note"]   decline -> status: rejected
  proposal-decide.py <slug> build   ["note"]   done building -> status: built
  proposal-decide.py list                      show pending decisions

<slug> is any unique fragment of the proposal filename, e.g.:
  proposal-decide.py replay-gym accept "build it as the nightly gym job"
"""
import json, os, re, glob, sys, datetime as dt
from atomic_io import atomic_append, atomic_append_validated

HOME = os.path.expanduser("~")
K = os.path.join(HOME, ".claude", "knowledge")
PROPOSALS = os.environ.get("PROPOSALS_DIR", os.path.join(K, "dreams", "proposals"))
OUTCOMES = os.environ.get("OUTCOMES_FILE", os.path.join(K, "garden-reports", "proposal-outcomes.jsonl"))


def find(slug):
    hits = [f for f in glob.glob(os.path.join(PROPOSALS, "*.md")) if slug in os.path.basename(f)]
    if not hits:
        sys.exit(f"no proposal matches '{slug}' in {PROPOSALS}")
    if len(hits) > 1:
        sys.exit(f"ambiguous '{slug}': {', '.join(os.path.basename(h) for h in hits)}")
    return hits[0]


def set_status(path, status):
    body = open(path, errors="replace").read()
    new = re.sub(r"^status:\s*\S+", f"status: {status}", body, count=1, flags=re.MULTILINE)
    if new == body and not body.startswith("---"):
        sys.exit(f"{os.path.basename(path)} has no frontmatter status line")
    if new == body:
        # no existing status line; insert one under the frontmatter opener
        new = body.replace("---\n", f"---\nstatus: {status}\n", 1)
    open(path, "w").write(new)


PROPOSAL_OUTCOME_SCHEMA = {
    "required": ["date", "proposal", "action", "by"],
    "enums": {"action": {"accepted", "rejected-false-alarm", "accepted-modified", "built"}},
    # date is a YYYY-MM-DD date field, not a tz timestamp — regex-guarded below
}


def log_outcome(title, action, note):
    row = {"date": dt.date.today().isoformat(), "proposal": title,
           "action": action, "notes": note or "", "by": "josh (proposal-decide)"}
    if not re.match(r"^\d{4}-\d{2}-\d{2}$", row["date"]):
        raise ValueError(f"refused: bad date format {row['date']!r}")
    atomic_append_validated(OUTCOMES, row, PROPOSAL_OUTCOME_SCHEMA)
    return row


def main():
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "list"):
        os.system(f"python3 {os.path.join(HOME, '.claude', 'knowledge', 'scripts', 'proposal-pipeline.py')}")
        return
    if len(args) < 2 or args[1] not in ("accept", "reject", "build"):
        sys.exit(__doc__)
    slug, action = args[0], args[1]
    note = args[2] if len(args) > 2 else ""
    p = find(slug)
    title = re.sub(r"^\d{4}-\d{2}-\d{2}-", "", os.path.basename(p)[:-3]).replace("-", " ")
    fm_status = "built" if action == "build" else action + ("d" if action != "reject" else "ed")
    fm_status = {"accept": "accepted", "reject": "rejected", "build": "built"}[action]
    set_status(p, fm_status)
    log_outcome(title, fm_status, note)
    print(f"logged: {title} -> {fm_status}" + (f' ({note})' if note else ''))
    print("next: python3 ~/.claude/knowledge/scripts/proposal-pipeline.py")


if __name__ == "__main__":
    main()
