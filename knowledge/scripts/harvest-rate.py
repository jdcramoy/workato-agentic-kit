#!/usr/bin/env python3
"""Harvest-rate metric for the brain gardener.

"Dreaming found nothing" is only good news if sessions were actually harvested.
This measures it: significant events in a session window (fixes landed, rules
stated, Josh corrections, job evidence) vs. knowledge/memory writes in the same
window. A healthy system harvests close to 100%; a low rate means knowledge is
being lost mid-session, and the in-session auto-save discipline needs shoring up.

Usage: python3 harvest-rate.py [--date 2026-10-06] [--project <slug>]

Zero-dependency; greps JSONL transcripts by signature, never loads them whole.
"""
import argparse
import json
import os
import re

DEFAULT_PROJECT = '-Users-YOUR-USER-Documents-workbench'
MEMROOT = os.path.expanduser('~/.claude/projects/%s/memory' % DEFAULT_PROJECT)
KROOT = os.path.expanduser('~/.claude/knowledge')

# Signatures of "a significant event happened" in transcript text.
EVENT_PATTERNS = {
    'rule_or_fix_stated': re.compile(r'fixed|resolved|workaround|trap|gotcha|root cause', re.I),
    'josh_correction': re.compile(r'"role":\s*"user"[^}]*?(no,|that\'s wrong|don\'t do that|stop doing|not what i)', re.I),
    'live_evidence': re.compile(r'job_get|job trace|job_id|job-handle|trace line', re.I),
    'jira_write': re.compile(r'mcp__atlassian__(createJiraIssue|addCommentToJiraIssue|editJiraIssue)'),
    'recipe_push': re.compile(r'recipe_builder_push'),
}
# Signatures of "it got recorded" in the same window.
WRITE_MARKERS = re.compile(r'memory|knowledge|INDEX\.md|SKILL\.md|playbook', re.I)


def transcript_stats(path):
    counts = {k: 0 for k in EVENT_PATTERNS}
    writes = 0
    with open(path, encoding='utf-8', errors='replace') as fh:
        for line in fh:
            for k, pat in EVENT_PATTERNS.items():
                if pat.search(line):
                    counts[k] += 1
            if '"name":"Write"' in line or '"name": "Write"' in line:
                if WRITE_MARKERS.search(line):
                    writes += 1
    return counts, writes


def day_files(root, day):
    proj = os.path.expanduser('~/.claude/projects/%s' % DEFAULT_PROJECT)
    out = []
    for dirpath, _dirs, files in os.walk(proj):
        for f in files:
            if f.endswith('.jsonl'):
                p = os.path.join(dirpath, f)
                # crude date filter by mtime day
                import datetime
                mt = datetime.datetime.fromtimestamp(os.path.getmtime(p))
                if mt.strftime('%Y-%m-%d') == day:
                    out.append(p)
    return out


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--date', default=None, help='YYYY-MM-DD (default: today)')
    args = ap.parse_args()
    import datetime
    day = args.date or datetime.datetime.now().strftime('%Y-%m-%d')

    files = day_files(None, day)
    if not files:
        print(f'No transcripts with mtime on {day} under project {DEFAULT_PROJECT}.')
        return

    total = {k: 0 for k in EVENT_PATTERNS}
    total_writes = 0
    for f in files:
        c, w = transcript_stats(f)
        for k in total:
            total[k] += c[k]
        total_writes += w

    print(f'Harvest-rate sample: {len(files)} transcript(s), {day}')
    for k, v in total.items():
        print(f'  {k}: {v}')
    print(f'  knowledge/memory writes recorded: {total_writes}')
    events = sum(total.values())
    if events:
        rate = min(100.0, 100.0 * total_writes / max(1, events))
        print(f'  crude harvest rate: {rate:.0f}% (writes / event-signature hits)')
    print('\nNote: signatures are directional, not exact — treat as a trend gauge,')
    print('and cross-check any surprising rate by hand before acting on it.')


if __name__ == '__main__':
    main()
