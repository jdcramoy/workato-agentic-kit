#!/usr/bin/env python3
"""error-canon-promoter.py — count repeats and promote them to canon.

Reads error-events.jsonl (written by ~/.claude/hooks/error-sensor.py), clusters
by signature, and maintains error-canon/error-canon.jsonl:

  - a signature seen >= THRESHOLD times (default 3) across >= MIN_SESSIONS
    sessions (default 2) becomes a canon row  -> the sensor injects guidance on
    every subsequent occurrence (retry storms within one session don't count)
  - `--record <sig_hash> --lesson "..."` permanently records the correction;
    the lesson is what gets injected from then on

Usage:
  error-canon-promoter.py              # aggregate + promote (idempotent)
  error-canon-promoter.py --quiet      # print only NEW promotions
  error-canon-promoter.py --list       # show canon rows
  error-canon-promoter.py --record a1b2c3d4e5f6 --lesson "one-line lesson"
"""
import argparse
import json
import os
import sys
import tempfile
import time
from collections import defaultdict

KNOW = os.path.expanduser('~/.claude/knowledge')
EVENTS = os.path.join(KNOW, 'error-events.jsonl')
CANON_DIR = os.path.join(KNOW, 'error-canon')
CANON = os.path.join(CANON_DIR, 'error-canon.jsonl')

THRESHOLD = int(os.environ.get('ERRCANON_THRESHOLD', '3'))
MIN_SESSIONS = int(os.environ.get('ERRCANON_MIN_SESSIONS', '2'))


def load_jsonl(path):
    rows = []
    if os.path.exists(path):
        with open(path) as fh:
            for line in fh:
                line = line.strip()
                if line:
                    try:
                        rows.append(json.loads(line))
                    except ValueError:
                        pass
    return rows


def write_canon(rows):
    os.makedirs(CANON_DIR, exist_ok=True)
    fd, tmp = tempfile.mkstemp(dir=CANON_DIR, suffix='.tmp')
    with os.fdopen(fd, 'w') as fh:
        for r in rows:
            fh.write(json.dumps(r) + '\n')
    os.replace(tmp, CANON)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--quiet', action='store_true')
    ap.add_argument('--list', action='store_true')
    ap.add_argument('--record', metavar='SIG_HASH')
    ap.add_argument('--lesson', metavar='TEXT')
    args = ap.parse_args()

    if args.record:
        if not args.lesson:
            sys.exit('ERROR: --record needs --lesson "<one-line lesson>"')
        rows = load_jsonl(CANON)
        for r in rows:
            if r.get('sig_hash') == args.record:
                r['lesson'] = args.lesson.strip()
                r['status'] = 'lesson-recorded'
                r['lesson_recorded_at'] = round(time.time(), 3)
                write_canon(rows)
                if not args.quiet:
                    print(f'recorded lesson for {args.record}: {r["signature"]}')
                return
        sys.exit(f'ERROR: no canon row with sig_hash {args.record} (check --list)')

    rows = load_jsonl(CANON)
    if args.list:
        for r in rows:
            print(f'{r["sig_hash"]}  {r["count"]:>3}x  {r.get("sessions","?"):>2}s  '
                  f'{"LESSON" if r.get("lesson") else "open "}  {r["signature"]}')
        return

    # aggregate events
    groups = defaultdict(lambda: {'events': []})
    for e in load_jsonl(EVENTS):
        g = groups[e['sig_hash']]
        g['events'].append(e)
        g.setdefault('signature', e['signature'])

    existing = {r['sig_hash']: r for r in rows}
    new_promotions = []
    for sig_hash, g in groups.items():
        events = g['events']
        count = len(events)
        sessions = len({e.get('session', '?') for e in events})
        first = min(e['ts'] for e in events)
        last = max(e['ts'] for e in events)
        row = existing.get(sig_hash)
        if row:
            row['count'], row['sessions'], row['last_seen'] = count, sessions, last
        elif count >= THRESHOLD and sessions >= MIN_SESSIONS:
            row = {
                'sig_hash': sig_hash, 'signature': g['signature'],
                'tool': events[0].get('tool', ''),
                'count': count, 'sessions': sessions,
                'first_seen': first, 'last_seen': last,
                'lesson': '', 'status': 'canon', 'created': round(time.time(), 3),
            }
            existing[sig_hash] = row
            new_promotions.append(
                f'NEW CANON {sig_hash} ({count}x/{sessions}s): {g["signature"]}')
        else:
            continue
    # drop open duplicates that never qualified (events exist but < threshold)
    keep = [r for r in existing.values()
            if r.get('status') == 'lesson-recorded'
            or (r.get('count', 0) >= THRESHOLD and r.get('sessions', 0) >= MIN_SESSIONS)]
    write_canon(keep)

    if new_promotions and not args.quiet:
        print('\n'.join(new_promotions))
    elif new_promotions and args.quiet:
        print(f'{len(new_promotions)} new canon promotion(s): ' + '; '.join(p.split("): ", 1)[1] for p in new_promotions))


if __name__ == '__main__':
    main()
