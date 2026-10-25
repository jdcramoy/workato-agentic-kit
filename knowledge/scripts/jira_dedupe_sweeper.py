#!/usr/bin/env python3
"""jira_dedupe_sweeper.py — estate-wide Atlassian comment-duplication sweeper.

Why: Atlassian regression (started 2026-10-23 between 08:02-16:24 UTC) reprocesses
every REST comment POST ~3x server-side -> three identical rows per comment
(consecutive ids, ~1s spacing, same actor). jira.py self-heals its own posts;
this sweeper catches clones from ANY API integration, workspace-wide.

Algorithm:
  1. JQL: issues updated in the last N minutes (comment activity bumps `updated`).
  2. For each issue, fetch comments; group by (author accountId, exact ADF body).
  3. A cluster of >= 2 rows whose `created` span is <= 60s = duplication.
  4. Delete every row except the lowest-id (first-created) one.
  5. Log every action to ~/.claude/knowledge/scripts/jira_dedupe_sweeper.jsonl.

Safety: exact-body match + same author + 60s window — a legit later repost (same
author, same text, hours later) never matches. DELETE may return 404 while landing
(known Jira quirk) — success is decided by the list read-back, never the status code.
"""

import json
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import jira  # same auth/SITE/http plumbing as jira.py

LOG = os.path.expanduser("~/.claude/knowledge/scripts/jira_dedupe_sweeper.jsonl")
WINDOW_MIN = 30          # look at issues updated in the last 30 minutes
CLUSTER_WINDOW_S = 60    # rows created within this span are one duplication cluster


def log(event):
    with open(LOG, "a") as f:
        f.write(json.dumps({"ts": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
                            **event}) + "\n")


def epoch(created):
    """Jira created (ms since epoch int, or ISO string) -> seconds, or None."""
    try:
        return int(created) / 1000.0
    except (ValueError, TypeError):
        pass
    try:
        import calendar
        from datetime import datetime
        s = str(created).strip()
        s = s.split(".")[0].split("+")[0]  # drop millis + tz suffix
        dt = datetime.strptime(s, "%Y-%m-%dT%H:%M:%S")
        return calendar.timegm(dt.timetuple())
    except Exception:
        return None


def sweep(auth, dry=False):
    jql = f"updated >= -{WINDOW_MIN}m"
    code, res = jira.http("POST", "/rest/api/3/search/jql", auth=auth, payload={
        "jql": jql, "maxResults": 50, "fields": ["summary"]})
    if code != 200:
        print(f"FAIL: search HTTP {code}: {json.dumps(res)[:200]}")
        return 1
    issues = [(i["key"], i["fields"].get("summary") or "") for i in res.get("issues", [])]
    total_deleted = 0
    for key, summary in issues:
        code, res = jira.http("GET", f"/rest/api/3/issue/{key}/comment?maxResults=50", auth=auth)
        if code != 200:
            continue
        comments = res.get("comments", [])
        clusters = {}
        for c in comments:
            author = ((c.get("author") or {}).get("accountId")) or "?"
            body = json.dumps(c.get("body", {}), sort_keys=True)
            clusters.setdefault((author, body), []).append(c)
        for (author, body), rows in clusters.items():
            if len(rows) < 2:
                continue
            times = [epoch(c.get("created")) for c in rows]
            if any(t is None for t in times):
                continue
            if max(times) - min(times) > CLUSTER_WINDOW_S:
                continue  # outside the duplication window — a legit repost
            rows_sorted = sorted(rows, key=lambda c: int(c["id"]))
            keep, clones = rows_sorted[0], rows_sorted[1:]
            print(f"{key}: duplicate cluster x{len(rows)} (author {author[:12]}…) — "
                  f"keep {keep['id']}, delete {[c['id'] for c in clones]}")
            log({"event": "cluster", "issue": key, "summary": summary[:80],
                 "kept": keep["id"], "clones": [c["id"] for c in clones],
                 "dry_run": dry})
            if dry:
                continue
            for c in clones:
                dcode, _ = jira.http("DELETE", f"/rest/api/3/issue/{key}/comment/{c['id']}",
                                     auth=auth, ok404=True)
                total_deleted += 1
                log({"event": "delete", "issue": key, "comment_id": c["id"],
                     "http": dcode})
        # read-back per issue: clones gone? (DELETE 404s while landing)
        if not dry and any(len(rows) >= 2 for rows in clusters.values()):
            code, res = jira.http("GET", f"/rest/api/3/issue/{key}/comment?maxResults=50", auth=auth)
            if code == 200:
                comments = res.get("comments", [])
                clusters2 = {}
                for c in comments:
                    author = ((c.get("author") or {}).get("accountId")) or "?"
                    body = json.dumps(c.get("body", {}), sort_keys=True)
                    clusters2.setdefault((author, body), []).append(c)
                left = {k: [c["id"] for c in v] for k, v in clusters2.items() if len(v) > 1
                        and max(epoch(c["created"]) for c in v) - min(epoch(c["created"]) for c in v) <= CLUSTER_WINDOW_S}
                if left:
                    log({"event": "leftover_after_sweep", "issue": key, "clusters": left})
    print(f"sweep done: {len(issues)} issues scanned, {total_deleted} clone rows deleted"
          + (" (dry run)" if dry else ""))
    log({"event": "sweep_done", "issues": len(issues), "deleted": total_deleted, "dry_run": dry})
    return 0


def main():
    dry = "--dry-run" in sys.argv
    auth = jira.load_auth()
    sys.exit(sweep(auth, dry=dry))


if __name__ == "__main__":
    main()
