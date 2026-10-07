#!/usr/bin/env python3
"""Cost heatmap for the Workato estate: runtime tasks vs dev tokens, coupled.

Runtime cost = task consumption per folder (from the corpus index, which the
weekly corpus-indexer refreshes with job counters).
Dev cost = token usage per day (from the usage ledger; brain-guard logs
turn-usage events). Session→project attribution is NOT yet possible (usage
events carry no session id), so dev tokens report estate-wide — the script
says so rather than faking precision. The ROI layer (business value per
capability) is a manual input file when Josh provides one.

Usage: python3 cost-heatmap.py [--days 7]
Output: markdown tables (print + append to garden-reports/cost-heatmap-latest.md)
"""
import argparse
import json
import os
from collections import defaultdict
from datetime import datetime, timedelta, timezone

GARDEN = os.path.expanduser('~/.claude/knowledge/garden-reports')
INDEX = os.path.join(GARDEN, 'recipes-index.jsonl')
USAGE = os.path.join(GARDEN, 'usage-ledger.jsonl')
OUT = os.path.join(GARDEN, 'cost-heatmap-latest.md')


def load_jsonl(path):
    rows = []
    if os.path.exists(path):
        for line in open(path, encoding='utf-8', errors='replace'):
            line = line.strip()
            if not line:
                continue
            try:
                rows.append(json.loads(line))
            except json.JSONDecodeError:
                pass
    return rows


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--days', type=int, default=7)
    args = ap.parse_args()

    since = datetime.now(timezone.utc) - timedelta(days=args.days)
    index = load_jsonl(INDEX)

    # --- runtime tasks per folder ---
    folder_tasks = defaultdict(int)
    folder_names = {}
    no_stats = 0
    for r in index:
        fid = str(r.get('folder_id') or '?')
        folder_names.setdefault(fid, r.get('folder_name') or '')
        lt = r.get('lifetime_task_count')
        if lt is None:
            no_stats += 1
            continue
        folder_tasks[fid] += int(lt)

    # --- dev tokens from usage ledger ---
    total_in = total_out = cache_read = 0
    turns = 0
    for ev in load_jsonl(USAGE):
        if ev.get('kind') != 'turn-usage':
            continue
        try:
            ts = datetime.fromisoformat(ev['ts'])
        except (KeyError, ValueError):
            continue
        if ts < since:
            continue
        turns += 1
        for part in str(ev.get('target', '')).split():
            if '=' not in part:
                continue
            k, _, v = part.partition('=')
            try:
                v = int(v)
            except ValueError:
                continue
            if k == 'in':
                total_in += v
            elif k == 'out':
                total_out += v
            elif k == 'cache_read':
                cache_read += v

    lines = []
    lines.append(f'# Estate cost heatmap — generated {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M")} UTC')
    lines.append('')
    lines.append(f'## Runtime cost: tasks per folder (estate: {len(index)} recipes)')
    lines.append('')
    lines.append('| Folder | Lifetime tasks |')
    lines.append('|---|---|')
    for fid, tasks in sorted(folder_tasks.items(), key=lambda kv: -kv[1]):
        name = folder_names.get(fid, '')
        lines.append(f'| [{fid}](https://app.workato.com/recipes?fid={fid}) {name} | {tasks:,} |')
    if no_stats:
        lines.append(f'')
        lines.append(f'_{no_stats} recipes in the index carry no task counters (indexer captures what recipe_list returns)._')
    lines.append('')
    lines.append(f'## Dev cost: tokens, last {args.days} days ({turns} turns)')
    lines.append('')
    lines.append('| Metric | Tokens |')
    lines.append('|---|---|')
    lines.append(f'| Input | {total_in:,} |')
    lines.append(f'| Output | {total_out:,} |')
    lines.append(f'| Cache reads | {cache_read:,} |')
    lines.append(f'| Effective input (in + cache_read) | {total_in + cache_read:,} |')
    lines.append('')
    lines.append('_Dev tokens are estate-wide: usage events carry no session/project attribution yet._')
    lines.append('_ROI layer: manual, when a business-value number per capability exists._')

    out = '\n'.join(lines) + '\n'
    print(out)
    with open(OUT, 'w') as fh:
        fh.write(out)


if __name__ == '__main__':
    main()
