#!/usr/bin/env python3
"""jira_bulk_pull.py — refresh closed-bug corpus + case base (runs Sundays)."""
import base64, json, subprocess, urllib.request, urllib.parse, time
from pathlib import Path

tok = subprocess.run(["security", "find-generic-password", "-s", "atlassian-confluence", "-a", "josh.cramoy@workato.com", "-w"], capture_output=True, text=True).stdout.strip()
AUTH = base64.b64encode(f"josh.cramoy@workato.com:{tok}".encode()).decode()
BASE = "https://workato.atlassian.net"
OUT = Path.home() / ".claude/workato-kb/corpus/jira-bugs"
OUT.mkdir(parents=True, exist_ok=True)
sys_path = Path(__file__).parent.parent
import sys
sys.path.insert(0, str(sys_path))

def get(url):
    req = urllib.request.Request(url, headers={"Authorization": f"Basic {AUTH}", "User-Agent": "workato-kb/0.1"})
    for attempt in range(3):
        try:
            with urllib.request.urlopen(req, timeout=60) as r:
                return json.load(r)
        except Exception:
            if attempt == 2: raise
            time.sleep(2 * (attempt + 1))

jql = '(project = BSYS OR project = BTSUP) AND issuetype = Bug AND statusCategory = Done AND resolved >= "2025-10-01"'
token, pages, new = "", 0, 0
while True:
    params = {"jql": jql, "maxResults": 100, "fields": "key,summary,created,resolutiondate,comment,issuetype"}
    if token:
        params["nextPageToken"] = token
    d = get(f"{BASE}/rest/api/3/search/jql?" + urllib.parse.urlencode(params))
    issues = d.get("issues", [])
    for i in issues:
        f = OUT / f"{i['key']}.json"
        if not f.exists():
            new += 1
        f.write_text(json.dumps(i, indent=1))
    pages += 1
    token = d.get("nextPageToken", "")
    if not token or not issues:
        break
    time.sleep(0.2)

from kb.jira_seeder import extract
from kb.cases import file_case
import sqlite3 as _sq
_cdb = _sq.connect(str(Path.home() / ".claude/workato-kb/index/cases.db"))
already = {r[0] for r in _cdb.execute("SELECT dedupe_key FROM cases WHERE dedupe_key IS NOT NULL")}
_cdb.close()
filed = 0
for tf in OUT.glob("*.json"):
    try:
        c = extract(json.loads(tf.read_text()))
        if not c: continue
        if c["key"] in already:
            continue  # already filed — skip re-embedding (nightly cost = new bugs only)
        file_case(presentation=f"[{c['key']}] {c['presentation']}", diagnosis=c["diagnosis"],
                  treatment=c["treatment"], outcome="worked", tags=c["tags"], source=c["source"])
        filed += 1
    except Exception:
        continue
from kb.cases import stats
print(f"refreshed: {pages} pages, {new} new tickets, {filed} cases upserted; total {stats()['cases']}")
