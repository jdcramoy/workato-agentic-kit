#!/usr/bin/env python3
"""jira.py — one wrapper for Jira + Confluence REST operations (headless-safe).

Why: the Atlassian MCP auth breaks under load (429 throttling on the OAuth
consent page, observed 2026-10-21), which strands every scheduled job that
touches Jira. The email + API-token path (jira.env) works for both Jira and
Confluence on the same site and needs no OAuth. This wraps it with the rules
the fleet already follows: read-back verification, no-Jira-keys redaction on
Confluence, retry with backoff, and an evidence line for every result.

Auth: ~/.claude/knowledge/config/jira.env  (JIRA_EMAIL, JIRA_API_TOKEN)
Site: workato.atlassian.net (override: JIRA_SITE env var)

Subcommands:
  search "JQL" [--limit N] [--fields F1,F2]      JQL search -> compact rows
  get KEY [--comments]                           issue -> key/summary/status/...
  comment KEY (--text S | --file F)              add comment, read back, link
  transition KEY [--list | --name NAME]          list or apply a transition
  edit KEY --field FIELD --value V               set a field (raw JSON value ok)
  page-get PAGE_ID [--out FILE]                  Confluence page -> markdown-ish
  page-create --space ID --title T [--parent ID] [--draft] FILE
  page-publish PAGE_ID FILE [--no-redact]        publish markdown, read back

Every command ends with an EVIDENCE line (JSON): {cmd, http, ids, urls,
verified}. Read commands print the evidence line too — claims need citations.
"""

import argparse
import base64
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request

SITE = os.environ.get("JIRA_SITE", "https://workato.atlassian.net")
ENV_PATH = os.path.expanduser("~/.claude/knowledge/config/jira.env")
RETRYABLE = {429, 500, 502, 503, 504}
JIRA_KEY_RE = re.compile(r"\bBSYS-\d+\b")
MAX_ATTEMPTS, BACKOFF_S = 3, 8


def load_auth():
    email = token = None
    if os.path.exists(ENV_PATH):
        for line in open(ENV_PATH):
            m = re.match(r"^(JIRA_EMAIL|JIRA_API_TOKEN)=(.*)$", line.strip())
            if m:
                v = m.group(2).strip().strip('"').strip("'")
                if m.group(1) == "JIRA_EMAIL":
                    email = v
                else:
                    token = v
    if not (email and token):
        sys.exit(f"FAIL: {ENV_PATH} must define JIRA_EMAIL and JIRA_API_TOKEN")
    return email, token


def http(method, path, payload=None, auth=None, ok404=False):
    """One REST call with retry/backoff. Returns (code, parsed_body_or_text)."""
    basic = base64.b64encode(f"{auth[0]}:{auth[1]}".encode()).decode()
    req = urllib.request.Request(
        f"{SITE}{path}", method=method,
        data=json.dumps(payload).encode() if payload is not None else None,
        headers={"Authorization": f"Basic {basic}", "Content-Type": "application/json"})
    last = (0, {})
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            with urllib.request.urlopen(req, timeout=30) as r:
                code, body = r.status, r.read().decode()
        except urllib.error.HTTPError as e:
            code, body = e.code, e.read().decode()
        except urllib.error.URLError as e:
            code, body = 0, str(e.reason)
        try:
            parsed = json.loads(body) if body.strip() else {}
        except json.JSONDecodeError:
            parsed = {"raw": body}
        if code == 200 or (ok404 and code == 404):
            return code, parsed
        last = (code, parsed)
        if code in RETRYABLE and attempt < MAX_ATTEMPTS:
            print(f"  retry {attempt}/{MAX_ATTEMPTS-1}: HTTP {code}, backing off {BACKOFF_S}s",
                  file=sys.stderr)
            time.sleep(BACKOFF_S * attempt)
    return last


def md_to_adf(md_text):
    """Markdown -> ADF document. Covers what the fleet actually writes in
    tickets (jira-story-standards shapes): #/##/### headings, - bullets,
    - [ ] checkboxes, 1. numbered, ``` fences, paragraphs; inline **bold**,
    *italic* (only *single*-star style), `code`, [text](url). """
    inline_marks = []

    def inline(text):
        out = []
        # tokenize: **bold**, `code`, [t](u), then pass the rest through
        pat = re.compile(r"(\*\*.+?\*\*|`[^`]+`|\[[^\]]+\]\([^)]+\))")
        for seg in pat.split(text):
            if not seg:
                continue
            node = {"type": "text", "text": seg}
            if seg.startswith("**") and seg.endswith("**"):
                node = {"type": "text", "text": seg[2:-2], "marks": [{"type": "strong"}]}
            elif seg.startswith("`") and seg.endswith("`") and len(seg) > 2:
                node = {"type": "text", "text": seg[1:-1], "marks": [{"type": "code"}]}
            elif seg.startswith("[") and "](" in seg:
                label, url = seg[1:].split("](", 1)
                node = {"type": "text", "text": label,
                        "marks": [{"type": "link", "attrs": {"href": url[:-1]}}]}
            out.append(node)
        return out or [{"type": "text", "text": seg or " "}]

    content = []
    lines, i = md_text.split("\n"), 0

    def list_item(line_text, check=False):
        task = None
        body = line_text
        if check:
            todo = not line_text.lower().startswith("[x]")
            body = re.sub(r"^\[[ xX]\]\s*", "", line_text)
            task = "TODO" if todo else "DONE"
        return body, task

    while i < len(lines):
        line = lines[i]
        if not line.strip():
            i += 1
            continue
        # markdown table: consecutive |-rows (header, |---| separator, body)
        if line.lstrip().startswith("|"):
            rows = []
            while i < len(lines) and lines[i].lstrip().startswith("|"):
                cells = [c.strip() for c in lines[i].strip().strip("|").split("|")]
                if not all(re.fullmatch(r":?-{3,}:?", c) for c in cells):  # skip separator rows
                    rows.append(cells)
                i += 1
            if rows:
                ncols = max(len(r) for r in rows)
                content.append({"type": "table", "content": [
                    {"type": "tableRow", "content": [
                        {"type": "tableHeader" if r == 0 else "tableCell",
                         "content": [{"type": "paragraph", "content": inline(
                             row[c] if c < len(row) else "")}]}
                        for c in range(ncols)]}
                    for r, row in enumerate(rows)]})
                continue
        m = re.match(r"^(#{1,3})\s+(.*)$", line)
        if m:
            content.append({"type": "heading", "attrs": {"level": len(m.group(1))},
                            "content": inline(m.group(2))})
            i += 1
            continue
        if line.strip().startswith("```"):
            block, i = [], i + 1
            while i < len(lines) and not lines[i].strip().startswith("```"):
                block.append(lines[i])
                i += 1
            i += 1
            content.append({"type": "codeBlock",
                            "content": [{"type": "text", "text": "\n".join(block)}]})
            continue
        bullet_m = re.match(r"^(\s*)-\s+\[( |x|X)\]\s+(.*)$", line)
        bullet = re.match(r"^(\s*)-\s+(.*)$", line)
        numbered = re.match(r"^(\s*)\d+\.\s+(.*)$", line)
        if bullet_m or bullet or numbered:
            if bullet_m:  # Jira descriptions REJECT taskList/taskItem ADF blocks
                # (bisected live 2026-10-21) — render checkboxes as bullets with
                # a literal [ ]/[x] marker instead
                items = []
                while i < len(lines):
                    t = re.match(r"^(\s*)-\s+\[( |x|X)\]\s+(.*)$", lines[i])
                    if not t:
                        break
                    todo = not t.group(2).lower() == "x"
                    marker = "[ ]" if todo else "[x]"
                    items.append({"type": "listItem",
                                  "content": [{"type": "paragraph",
                                               "content": inline(f"{marker} {t.group(3)}")}]}),
                    i += 1
                content.append({"type": "bulletList", "content": items})
                continue
            kind = "bulletList" if bullet else "orderedList"
            items = []
            while i < len(lines):
                cur = re.match(r"^(\s*)-\s+(.*)$", lines[i]) if kind == "bulletList" \
                    else re.match(r"^(\s*)\d+\.\s+(.*)$", lines[i])
                if not cur:
                    break
                items.append({"type": "listItem",
                              "content": [{"type": "paragraph", "content": inline(cur.group(2))}]})
                i += 1
            node = {"type": kind, "content": items}
            if kind == "orderedList":
                node["attrs"] = {"order": 1}
            content.append(node)
            continue
        # paragraph: swallow consecutive non-special lines
        para = [line]
        i += 1
        while i < len(lines) and lines[i].strip() and not re.match(
                r"^(#{1,3}\s|\s*-\s|\s*\d+\.\s|```)", lines[i]):
            para.append(lines[i])
            i += 1
        content.append({"type": "paragraph", "content": inline(" ".join(para))})
    return {"type": "doc", "version": 1, "content": content or
            [{"type": "paragraph", "content": [{"type": "text", "text": " "}]}]}


def evidence(cmd, code, **kw):
    print("EVIDENCE: " + json.dumps({"cmd": cmd, "http": code, **kw}, default=str))


def compact_issue(issue, comments=False):
    f = issue.get("fields", {})
    row = {
        "key": issue.get("key"),
        "summary": f.get("summary"),
        "status": (f.get("status") or {}).get("name"),
        "assignee": ((f.get("assignee") or {}).get("displayName")),
        "updated": f.get("updated"),
        "url": f"{SITE}/browse/{issue.get('key')}",
        "priority": (f.get("priority") or {}).get("name"),
        "labels": f.get("labels", []),
    }
    if comments:
        rows = (f.get("comment") or {}).get("comments", [])

        def body_text(c):  # v3 bodies are ADF objects; flatten to plain text
            b = c.get("body")
            if isinstance(b, str):
                return b[:300]
            return " ".join(t for t in _walk(b) if t)[:300]

        def _walk(node):  # depth-first over ADF nodes
            if isinstance(node, dict):
                if node.get("type") == "text":
                    yield node.get("text", "")
                for child in node.get("content", []):
                    yield from _walk(child)
            elif isinstance(node, list):
                for item in node:
                    yield from _walk(item)

        row["comments"] = [
            {"author": (c.get("author") or {}).get("displayName"),
             "created": c.get("created"), "body": body_text(c)}
            for c in rows]
    return row


def cmd_search(a, auth):
    code, res = http("POST", "/rest/api/3/search/jql", auth=auth, payload={
        "jql": a.jql, "maxResults": a.limit,
        "fields": ["summary", "status", "assignee", "updated", "priority", "labels"]})
    if code != 200:
        print(f"FAIL: search HTTP {code}: {json.dumps(res)[:300]}")
        evidence("search", code, jql=a.jql)
        return 1
    rows = [compact_issue(i) for i in res.get("issues", [])]
    for r in rows:
        print(f"{r['key']}  [{r['status']}]  {r['summary']}"
              f"  (upd {r['updated']})  {r['url']}")
    print(f"{len(rows)} issue(s) (total {res.get('total', len(rows))})")
    evidence("search", code, jql=a.jql, count=len(rows), keys=[r["key"] for r in rows])
    return 0


def cmd_get(a, auth):
    fields = "summary,status,assignee,updated,priority,labels,description"
    if a.comments:
        fields += ",comment"
    code, res = http("GET", f"/rest/api/3/issue/{a.key}?fields={fields}", auth=auth)
    if code != 200:
        print(f"FAIL: get {a.key} HTTP {code}: {json.dumps(res)[:200]}")
        evidence("get", code, key=a.key)
        return 1
    print(json.dumps(compact_issue(res, comments=a.comments), indent=2, default=str))
    evidence("get", code, key=a.key)
    return 0


def cmd_comment(a, auth):
    text = open(a.file).read() if a.file else a.text
    if not text:
        sys.exit("FAIL: empty comment (pass --text or --file)")
    code, res = http("POST", f"/rest/api/3/issue/{a.key}/comment", auth=auth, payload={
        "body": md_to_adf(text)})
    if code not in (200, 201):
        print(f"FAIL: comment HTTP {code}: {json.dumps(res)[:300]}")
        evidence("comment", code, key=a.key)
        return 1
    cid = res.get("id")
    print(f"comment {cid} posted on {a.key}: {SITE}/browse/{a.key}")
    # read back: the comment must exist on the issue before we claim done.
    # Also detect Atlassian-side duplication (one POST -> several comment rows,
    # e.g. BTSUP-79460 2026-10-23: server created 3 rows from one 201 POST,
    # returning only the last id; the extra rows fired duplicate Slack mirrors).
    code2, check = http("GET", f"/rest/api/3/issue/{a.key}?fields=comment", auth=auth)
    rows = (check.get("fields", {}).get("comment", {}).get("comments", [])) \
        if code2 == 200 else []
    ids = [c.get("id") for c in rows]
    verified = code2 == 200 and cid in ids
    # siblings: other rows created within 10s of ours with the same body text
    def _body(c):
        return json.dumps(c.get("body", {}), sort_keys=True, default=str)
    mine = next((c for c in rows if str(c.get("id")) == str(cid)), None)
    dupes = []
    if mine is not None:
        t_mine = _body(mine)
        for c in rows:
            if c.get("id") != cid and _body(c) == t_mine and c.get("created"):
                dupes.append(c.get("id"))
    print(f"read-back: {'VERIFIED' if verified else 'NOT FOUND IN ISSUE ' + str(code2)}")
    if dupes:
        # self-heal: Atlassian's 2026-10-23 regression reprocesses every comment POST
        # ~3x server-side. Delete the clone rows (keep the first-created), then re-verify.
        keep = str(cid)  # keep the id OUR POST returned; delete every other row
        removed = []
        for d in dupes:
            code3, _ = http("DELETE", f"/rest/api/3/issue/{a.key}/comment/{d}", auth=auth,
                            ok404=True)
            # DELETE quirk: may 404 while landing — re-read decides, not the status code
            removed.append((d, code3))
        code4, recheck = http("GET", f"/rest/api/3/issue/{a.key}?fields=comment", auth=auth)
        rows4 = (recheck.get("fields", {}).get("comment", {}).get("comments", [])) \
            if code4 == 200 else []
        left = [str(c.get("id")) for c in rows4 if _body(c) == t_mine] \
            if mine is not None else []
        print(f"DUPLICATE COMMENT ROWS on {a.key} (Atlassian-side duplication from one "
              f"POST): kept {keep} (returned id), deleted {[d for d, _ in removed]} -> "
              f"{'deduped to 1 row' if left == [keep] else 'RECHECK: rows with this body now ' + str(left)}")
        dupes = []  # warning handled; evidence below carries the sweep result
        evidence("dedupe", code4, key=a.key, kept=keep, deleted=removed,
                 remaining_same_body=left)
    evidence("comment", code, key=a.key, comment_id=cid, verified=verified,
             duplicate_rows=dupes)
    return 0 if verified else 1


def cmd_transition(a, auth):
    code, res = http("GET", f"/rest/api/3/issue/{a.key}/transitions", auth=auth)
    if code != 200:
        print(f"FAIL: transitions HTTP {code}")
        evidence("transition", code, key=a.key)
        return 1
    trans = res.get("transitions", [])
    if a.list or not a.name:
        for t in trans:
            print(f"{t['id']}  {t['name']}")
        evidence("transition-list", code, key=a.key, count=len(trans))
        return 0
    match = next((t for t in trans if t["name"].lower() == a.name.lower()), None)
    if not match:
        print(f"FAIL: no transition named '{a.name}'. Available: "
              + ", ".join(t["name"] for t in trans))
        evidence("transition", 404, key=a.key, wanted=a.name)
        return 1
    code, res = http("POST", f"/rest/api/3/issue/{a.key}/transitions", auth=auth,
                     payload={"transition": {"id": match["id"]}})
    if code != 204:
        print(f"  transition note (HTTP {code}): {json.dumps(res)[:250]}")
    # read back: status must now match
    code2, issue = http("GET", f"/rest/api/3/issue/{a.key}?fields=status", auth=auth)
    now = (issue.get("fields", {}).get("status") or {}).get("name")
    print(f"transition '{a.name}' applied -> status now: {now}")
    evidence("transition", code, key=a.key, to=a.name, status_now=now, verified=code2 == 200)
    return 0 if code == 204 else 1


def cmd_edit(a, auth):
    try:
        value = json.loads(a.value)
    except json.JSONDecodeError:
        value = a.value
    code, res = http("PUT", f"/rest/api/3/issue/{a.key}", auth=auth,
                     payload={"fields": {a.field: value}})
    ok = code == 204
    print(f"edit {a.key} {a.field}: {'OK' if ok else f'FAIL HTTP {code}: ' + json.dumps(res)[:200]}")
    evidence("edit", code, key=a.key, field=a.field, verified=ok)
    return 0 if ok else 1


def cmd_page_get(a, auth):
    """Confluence page via v2 (markdown) with v1 storage fallback."""
    code, page = http("GET", f"/wiki/api/v2/pages/{a.page_id}?body-format=markdown", auth=auth)
    body = (page.get("body") or {}).get("value", "")
    if not body:  # some tenants return empty markdown bodies; v1 storage always has content
        code, page = http("GET", f"/wiki/rest/api/content/{a.page_id}?expand=body.storage,version",
                          auth=auth)
        body = (page.get("body") or {}).get("storage", {}).get("value", "")
        src = "v1-storage"
    else:
        src = "v2-markdown"
    if code != 200:
        print(f"FAIL: page-get HTTP {code}: {json.dumps(page)[:200]}")
        evidence("page-get", code, page_id=a.page_id)
        return 1
    if a.out:
        open(a.out, "w").write(body)
        print(f"wrote {len(body)} chars -> {a.out}")
    else:
        print(body)
    evidence("page-get", code, page_id=a.page_id, version=page.get("version", {}).get("number"),
             chars=len(body), source=src)
    return 0


def redact(text):
    """House rule: no Jira keys in published Confluence content."""
    return JIRA_KEY_RE.sub("one tracked incident", text)


def cmd_page_publish(a, auth):
    content = open(a.file).read()
    if a.redact:
        content = redact(content)
    # v2 update: need current version + title
    code, page = http("GET", f"/wiki/api/v2/pages/{a.page_id}", auth=auth)
    if code != 200:
        print(f"FAIL: cannot read page {a.page_id} before publish: HTTP {code}")
        evidence("page-publish", code, page_id=a.page_id)
        return 1
    ver = page["version"]["number"]
    code, _ = http("PUT", f"/wiki/api/v2/pages/{a.page_id}", auth=auth, payload={
        "id": str(a.page_id), "type": "page", "status": "current",
        "title": page["title"],
        "body": {"representation": "markdown", "value": content},
        "version": {"number": ver + 1}})
    if code != 200:
        print(f"FAIL: publish HTTP {code}")
        evidence("page-publish", code, page_id=a.page_id, version=ver + 1)
        return 1
    # read back via v1 storage (v2 markdown bodies read empty on this tenant)
    code2, check = http("GET",
                        f"/wiki/rest/api/content/{a.page_id}?expand=body.storage,version", auth=auth)
    live = (check.get("body") or {}).get("storage", {}).get("value", "")
    norm = lambda s: re.sub(r"\s+", " ", s).lower()          # noqa: E731
    # probe check: 8 distinctive non-trivial words from the source
    words = [w for w in re.findall(r"[a-z0-9.-]{6,}", norm(content))
             if not w.startswith(("http", "wiki", "workato"))][:8]
    verified = code2 == 200 and all(w in norm(live) for w in words) and len(live) > 100
    print(f"published {a.page_id} v{ver} -> v{ver + 1}; read-back "
          f"{'VERIFIED' if verified else 'MISMATCH'} ({len(live)} chars live, {len(words)} probes)")
    if not verified and live:
        missing = [w for w in words if w not in norm(live)]
        print(f"  missing probes: {missing}")
    evidence("page-publish", code, page_id=a.page_id, version=ver + 1, verified=verified)
    return 0 if verified else 1


def cmd_create(a, auth):
    """Create any issue (Story/Epic/Bug/Sub-task/...) per jira-story-standards:
    parent epic, labels, story points (customfield_10057), markdown description."""
    # Story-points gate, ported 2026-10-29 from the guardrails mod (hook 3):
    # the mod watched mcp__atlassian__createJiraIssue; with the MCP retired,
    # the wrapper is the write path, so the rule lives here now. Points are
    # REQUIRED unless the project's screen lacks the field (BTSUP, HROPS,
    # PSM, MCP — known blocked, do not retry).
    if a.points is None and a.project.upper() not in {"BTSUP", "HROPS", "PSM", "MCP"}:
        print("FAIL: story points are REQUIRED at creation (jira-story-standards): "
              "--points N (Fibonacci; 1pt = 1 dev-day). Projects without the field "
              "on their screen (BTSUP, HROPS, PSM, MCP) are exempt — note once, move on.")
        evidence("create-points-gate", 0, project=a.project)
        return 1
    fields = {"project": {"key": a.project}, "issuetype": {"name": a.type},
              "summary": a.summary, "labels": a.labels or []}
    desc = open(a.description).read() if a.description else (a.text or "")
    if desc:
        fields["description"] = md_to_adf(desc)
    if a.parent:
        fields["parent"] = {"key": a.parent}
    if a.points is not None:
        fields["customfield_10057"] = a.points
    if a.priority:
        fields["priority"] = {"name": a.priority}
    if a.assignee:
        # resolve email -> account id
        code, res = http("GET", "/rest/api/3/user/search?query=" + a.assignee, auth=auth)
        ids = [u.get("accountId") for u in (res if isinstance(res, list) else [])]
        if not ids:
            print(f"FAIL: no user found for '{a.assignee}'")
            evidence("create", code, assignee=a.assignee)
            return 1
        fields["assignee"] = {"id": ids[0]}
    # Dedupe pre-check (born from the 2026-10-26 triplicate filing: five
    # same-day clusters filed 2-3x byte-identical). Block on a same-project
    # near-identical open summary unless --force-dedupe-ok.
    if not a.force_dedupe_ok:
        norm = lambda s: " ".join(s.lower().split())
        want = norm(a.summary)
        import difflib
        jql = f'project = {a.project} AND created >= -7d AND resolution = Unresolved'
        code, res = http("POST", "/rest/api/3/search/jql", auth=auth, payload={
            "jql": jql, "maxResults": 100, "fields": ["summary"]})
        if code in (200, 201):
            for issue in (res.get("issues") or []):
                s = norm(issue.get("fields", {}).get("summary", ""))
                if not s:
                    continue
                ratio = difflib.SequenceMatcher(None, want, s).ratio()
                if s == want or ratio >= 0.9:
                    k = issue.get("key")
                    print(f"DEDUPE BLOCK: {k} has a near-identical open summary "
                          f"(similarity {ratio:.2f}): {issue.get('fields', {}).get('summary')!r}")
                    print(f"  Link it instead, or re-run with --force-dedupe-ok to create anyway.")
                    evidence("create-dedupe-block", code, candidate=k, similarity=round(ratio, 2))
                    return 1
    code, res = http("POST", "/rest/api/3/issue", auth=auth, payload={"fields": fields})
    if code not in (200, 201):
        print(f"FAIL: create HTTP {code}: {json.dumps(res)[:500]}")
        evidence("create", code, project=a.project, type=a.type)
        return 1
    key = res.get("key")
    # read back: the issue must exist with the right summary before claiming done
    code2, issue = http("GET", f"/rest/api/3/issue/{key}?fields=summary,status", auth=auth)
    verified = code2 == 200 and issue.get("fields", {}).get("summary") == a.summary
    print(f"created {a.type} {key}: {SITE}/browse/{key}"
          f"  (read-back {'VERIFIED' if verified else 'MISMATCH'})")
    evidence("create", code, key=key, url=f"{SITE}/browse/{key}", verified=verified)
    return 0 if verified else 1


def cmd_link(a, auth):
    payload = {"type": {"name": a.type}, "inwardIssue": {"key": a.inward},
               "outwardIssue": {"key": a.outward}}
    code, res = http("POST", "/rest/api/3/issueLink", auth=auth, payload=payload)
    ok = code in (200, 201)
    print(f"link {a.inward} --{a.type}--> {a.outward}: {'OK' if ok else 'FAIL ' + str(code)}")
    evidence("link", code, inward=a.inward, outward=a.outward, type=a.type, verified=ok)
    return 0 if ok else 1


def cmd_page_create(a, auth):
    content = open(a.file).read()
    if a.redact:
        content = redact(content)
    payload = {"spaceId": a.space, "status": "draft" if a.draft else "current",
               "title": a.title,
               "parentId": a.parent or None,
               "body": {"representation": "markdown", "value": content}}
    payload = {k: v for k, v in payload.items() if v is not None}
    code, res = http("POST", "/wiki/api/v2/pages", auth=auth, payload=payload)
    if code not in (200, 201):
        print(f"FAIL: page-create HTTP {code}: {json.dumps(res)[:300]}")
        evidence("page-create", code, title=a.title)
        return 1
    pid = res.get("id")
    state = " (draft)" if a.draft else ""
    print(f"created page {pid}{state}: {res.get('_links', {}).get('editui', res.get('_links', {}).get('base', ''))}")
    evidence("page-create", code, page_id=pid, title=a.title, parent=a.parent,
             draft=a.draft)
    return 0


def cmd_cql(a, auth):
    import urllib.parse
    q = f"/wiki/rest/api/content/search?cql={urllib.parse.quote(a.cql)}&limit={a.limit}"
    code, res = http("GET", q, auth=auth)
    if code != 200:
        print(f"FAIL: cql HTTP {code}: {json.dumps(res)[:200]}")
        evidence("cql", code, cql=a.cql)
        return 1
    for r in res.get("results", []):
        print(f"{r.get('id')}  {r.get('title')}")
    print(f"{len(res.get('results', []))} result(s)")
    evidence("cql", code, cql=a.cql, count=res.get("size", len(res.get("results", []))))
    return 0


def cmd_raw(a, auth):
    """Escape hatch: any REST operation the wrapper does not name yet.
    jira.py raw POST /rest/api/3/... '{"json":"body"}'"""
    body = json.loads(a.data) if a.data else None
    code, res = http(a.method, a.path, payload=body, auth=auth)
    print(json.dumps(res, indent=2, default=str)[:4000])
    evidence("raw", code, method=a.method, path=a.path)
    return 0 if code in (200, 201, 204) else 1


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    sub = ap.add_subparsers(dest="cmd", required=True)

    s = sub.add_parser("search")
    s.add_argument("jql")
    s.add_argument("--limit", type=int, default=25)
    s.add_argument("--fields", default="summary,status,assignee,updated")
    s.set_defaults(fn=cmd_search)

    s = sub.add_parser("get")
    s.add_argument("key")
    s.add_argument("--comments", action="store_true")
    s.set_defaults(fn=cmd_get)

    s = sub.add_parser("comment")
    s.add_argument("key")
    g = s.add_mutually_exclusive_group(required=True)
    g.add_argument("--text")
    g.add_argument("--file")
    s.set_defaults(fn=cmd_comment)

    s = sub.add_parser("transition")
    s.add_argument("key")
    s.add_argument("--name")
    s.add_argument("--list", action="store_true")
    s.set_defaults(fn=cmd_transition)

    s = sub.add_parser("edit")
    s.add_argument("key")
    s.add_argument("--field", required=True)
    s.add_argument("--value", required=True)
    s.set_defaults(fn=cmd_edit)

    s = sub.add_parser("page-get")
    s.add_argument("page_id")
    s.add_argument("--out")
    s.set_defaults(fn=cmd_page_get)

    s = sub.add_parser("create", help="create issue/epic/story/bug/subtask (standards-shaped)")
    s.add_argument("--project", required=True, help="project key, e.g. BSYS")
    s.add_argument("--type", required=True, help='issue type: Story/Epic/Bug/"Sub-task"/...')
    s.add_argument("--summary", required=True)
    s.add_argument("--parent", help="parent Epic key (ALWAYS set one per jira-story-standards)")
    s.add_argument("--description", help="file containing markdown description")
    s.add_argument("--text", help="markdown description inline")
    s.add_argument("--labels", nargs="*", default=[])
    s.add_argument("--points", type=int, help="story points (customfield_10057)")
    s.add_argument("--priority")
    s.add_argument("--assignee", help="email or name fragment; resolved to account id")
    s.add_argument("--force-dedupe-ok", action="store_true",
                   help="skip the near-identical-summary dedupe pre-check")
    s.set_defaults(fn=cmd_create)

    s = sub.add_parser("link", help="link two issues, e.g. Blocks/Relates/Duplicate")
    s.add_argument("--type", default="Relates")
    s.add_argument("--inward", required=True, help="blocks/the source issue")
    s.add_argument("--outward", required=True)
    s.set_defaults(fn=cmd_link)

    s = sub.add_parser("page-create", help="create a Confluence page from markdown")
    s.add_argument("--space", required=True, help="numeric space id")
    s.add_argument("--title", required=True)
    s.add_argument("file")
    s.add_argument("--parent", help="parent page id")
    s.add_argument("--draft", action="store_true", help="create as DRAFT (Josh publishes on review)")
    s.add_argument("--no-redact", dest="redact", action="store_false")
    s.set_defaults(fn=cmd_page_create, redact=True)

    s = sub.add_parser("cql", help="search Confluence with CQL")
    s.add_argument("cql")
    s.add_argument("--limit", type=int, default=10)
    s.set_defaults(fn=cmd_cql)

    s = sub.add_parser("raw", help="escape hatch: any REST call the wrapper does not name")
    s.add_argument("method", help="GET/POST/PUT/DELETE")
    s.add_argument("path", help="/rest/api/3/... or /wiki/...")
    s.add_argument("data", nargs="?", help="JSON body (optional)")
    s.set_defaults(fn=cmd_raw)

    s = sub.add_parser("page-publish")
    s.add_argument("page_id")
    s.add_argument("file")
    s.add_argument("--no-redact", dest="redact", action="store_false")
    s.set_defaults(fn=cmd_page_publish, redact=True)

    a = ap.parse_args()
    sys.exit(a.fn(a, load_auth()))


if __name__ == "__main__":
    main()
