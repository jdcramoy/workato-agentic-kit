#!/usr/bin/env python3
"""ea-escalate.py -- drop an escalation card into the Josh EA's inbox.

Any agent (dreamer, watchdog, gardener, project-dreamer, evidence, cortex,
triage/proposal flows) calls this INSTEAD of only posting to the bus when the
finding needs Josh to see it. The EA pulse consumes, ranks, dedupes, and
presents these as action-item signals; presented cards are marked presented,
not deleted (audit trail).

Usage:
  ea-escalate.py --from <agent> --kind <finding|proposal|blocker|ask> \
    --summary "<one line Josh-readable>" [--detail "<2-3 lines max>"] \
    [--source "<path or ticket or bus thread>"] [--urgency low|normal|high]

Cards live at ~/.claude/knowledge/josh-ea/escalations/cards.jsonl (atomic
append under a lockfile).
"""
import argparse, fcntl, json, os, time

ROOT = os.path.expanduser('~/.claude/knowledge/josh-ea/escalations')
CARDS = os.path.join(ROOT, 'cards.jsonl')
LOCK = CARDS + '.lock'

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--from', dest='frm', required=True)
    ap.add_argument('--kind', required=True, choices=['finding','proposal','blocker','ask'])
    ap.add_argument('--summary', required=True)
    ap.add_argument('--detail', default='')
    ap.add_argument('--source', default='')
    ap.add_argument('--urgency', default='normal', choices=['low','normal','high'])
    a = ap.parse_args()
    os.makedirs(ROOT, exist_ok=True)
    card = {
        'id': '%d-%s' % (int(time.time()*1000), a.frm),
        'ts': time.strftime('%Y-%m-%dT%H:%M:%SZ', time.gmtime()),
        'from': a.frm, 'kind': a.kind, 'urgency': a.urgency,
        'summary': a.summary, 'detail': a.detail, 'source': a.source,
        'status': 'new',  # -> presented -> actioned | dismissed
    }
    with open(LOCK, 'w') as lk:
        fcntl.flock(lk, fcntl.LOCK_EX)
        with open(CARDS, 'a') as f:
            f.write(json.dumps(card) + '\n')
    print('escalation card dropped:', card['id'])

if __name__ == '__main__':
    main()
