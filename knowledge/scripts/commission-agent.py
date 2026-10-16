#!/usr/bin/env python3
"""commission-agent.py — mechanical PSY4 commissioning check for agent files.

Verifies that an agent definition (~/.claude/agents/<name>.md) carries the
three required sections from knowledge/config/commissioning-template.md:

  1. Charter      — one-sentence job statement
  2. Refusal rights — explicit never-do list
  3. Mentor + review date — named mentor and a dated (14-day) review

Prints pass/fail per section and appends a commissioning row
  {"ts","agent","sections_ok","review_date"}
to knowledge/garden-reports/commissioning.jsonl (atomic_io.atomic_append).

Section matching is heading-based, not keyword-anywhere: a keyword mention
in passing (e.g. 'refuse or wait' inside a procedure step) does NOT pass —
the section must exist as a heading with a non-empty body. Accepted
heading synonyms are deliberately narrow and each match is printed so it
is auditable:
  charter         /charter|constitution|mission/
  refusal rights  /refusal|refuse|boundaries/
  mentor+review   heading/body containing /mentor/ AND /review/, plus a
                  YYYY-MM-DD date inside the section (the dated review)

Usage:
  commission-agent.py <name>        # one agent
  commission-agent.py --all         # every agent file (retrofit backlog)

Exit code: 0 if every checked agent passes all sections, 1 otherwise.
"""

import argparse
import glob
import json
import os
import re
import sys
import time

AGENTS_DIR = os.path.expanduser("~/.claude/agents")
TEMPLATE = os.path.expanduser(
    "~/.claude/knowledge/config/commissioning-template.md")
LEDGER = os.path.expanduser(
    "~/.claude/knowledge/garden-reports/commissioning.jsonl")

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from atomic_io import atomic_append  # noqa: E402

SECTIONS = [
    ("charter", re.compile(r"charter|constitution|mission", re.I)),
    ("refusal_rights", re.compile(r"refusal|refuse|boundaries", re.I)),
    ("mentor_review", re.compile(r"mentor", re.I)),
]

DATE_RE = re.compile(r"\d{4}-\d{2}-\d{2}")


def parse_sections(text):
    """Split an agent file into [(heading, body_lines)]."""
    sections = []
    cur_head, cur_body = None, []
    for line in text.splitlines():
        if re.match(r"^#{1,3}\s+", line.strip()):
            if cur_head is not None:
                sections.append((cur_head, cur_body))
            cur_head, cur_body = line.strip().lstrip("#").strip(), []
        elif cur_head is not None:
            cur_body.append(line)
    if cur_head is not None:
        sections.append((cur_head, cur_body))
    return sections


def check_agent(path):
    """Return ({section: (ok, matched_heading_or_reason)}, review_date)."""
    text = open(path, errors="replace").read()
    sections = parse_sections(text)
    results = {}
    review_date = None

    for key, rx in SECTIONS:
        ok, why = False, "no matching heading"
        for head, body in sections:
            if not rx.search(head):
                continue
            body_txt = "\n".join(body).strip()
            if key == "mentor_review":
                body_rx = re.search(r"review", body_txt, re.I) or \
                    re.search(r"review", head, re.I)
                dates = DATE_RE.findall(body_txt) or DATE_RE.findall(head)
                if not body_txt:
                    ok, why = False, f'heading "{head}" has empty body'
                elif not body_rx:
                    ok, why = False, f'heading "{head}" but no review wording'
                elif not dates:
                    ok, why = False, f'heading "{head}" but no YYYY-MM-DD date'
                else:
                    ok, why = True, head
                    review_date = dates[0]
            elif not body_txt or not any(l.strip() for l in body):
                ok, why = False, f'heading "{head}" has empty body'
            else:
                ok, why = True, head
            break
        results[key] = (ok, why)
    return results, review_date


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("name", nargs="?", default=None,
                    help="agent name (file ~/.claude/agents/<name>.md)")
    ap.add_argument("--all", action="store_true",
                    help="check every agent file")
    ap.add_argument("--no-record", action="store_true",
                    help="do not append to the commissioning ledger")
    a = ap.parse_args()

    if not a.all and not a.name:
        ap.error("give an agent name or --all")

    if a.all:
        paths = sorted(glob.glob(os.path.join(AGENTS_DIR, "*.md")))
    else:
        p = os.path.join(AGENTS_DIR, f"{a.name}.md")
        if not os.path.exists(p):
            print(f"no such agent file: {p}", file=sys.stderr)
            return 2
        paths = [p]

    now = time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime())
    today = time.strftime("%Y-%m-%d")
    all_ok = True
    for p in paths:
        name = os.path.splitext(os.path.basename(p))[0]
        results, review_date = check_agent(p)
        ok_flags = []
        print(f"{name}:")
        for key, (ok, why) in results.items():
            mark = "PASS" if ok else "FAIL"
            print(f"  {mark}  {key:14} {why if not ok else f'({why})'}")
            ok_flags.append(ok)
            all_ok = all_ok and ok
        if review_date and review_date < today:
            print(f"  NOTE  review date {review_date} is in the past "
                  f"(overdue review)")
        if not a.no_record:
            atomic_append(LEDGER, {
                "ts": now,
                "agent": name,
                "sections_ok": [k for k, (ok, _) in results.items() if ok],
                "review_date": review_date,
            })
        print()

    if not a.no_record:
        print(f"recorded to {LEDGER}")
    return 0 if all_ok else 1


if __name__ == "__main__":
    sys.exit(main())
