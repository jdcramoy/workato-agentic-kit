#!/usr/bin/env python3
"""Integrity mesh — reconcile internal claims against live Jira states for BSYS keys.

Usage:
  reconcile.py [--claims PATH] [--jira-status-cache FILE] [--orphan-hours N]

- Extracts BSYS-\\d+ refs from claim statements (and proof uris).
- Resolves each key's real Jira status:
    1. --jira-status-cache file.json  -> {"BSYS-123": "In Progress"}
       or {"BSYS-123": {"name": "In Progress", "statusCategory": "done"}} (one or both)
    2. else attempts `curl -s -m 10 "https://workato.atlassian.net/rest/api/3/issue/<KEY>?fields=status"`
       unauthenticated; on any failure marks the key "unfetchable".
- Flags ORPHANS: tier "asserted" claims older than --orphan-hours (default 24).
- Flags GHOSTS: statement claims fixed/done/resolved/... but the live Jira
  status contradicts it (status is not in a done-category).
- Writes knowledge/integrity/reconcile-report-<ts>.md and prints a summary.

Exit 0 when clean, 1 when any orphan/ghost/unfetchable finding exists.
"""
import argparse
import calendar
import json
import os
import re
import subprocess
import sys
import time
import urllib.parse

KB = os.path.expanduser("~/.claude/knowledge")
DEFAULT_CLAIMS = os.path.join(KB, "integrity", "claims.jsonl")
JIRA_HOST = "https://workato.atlassian.net"
BSYS_RE = re.compile(r"BSYS-(\d+)", re.IGNORECASE)
DONE_RE = re.compile(r"\b(fixed|done|resolved|closed|completed|shipped|deployed|verified)\b", re.IGNORECASE)
DONE_STATUSES = {"done", "closed", "resolved"}
REPORT_TS = time.strftime("%Y%m%d-%H%M%S")


def parse_ts(s):
    if not s:
        return None
    s = s.strip()
    try:
        if "T" in s:
            return calendar.timegm(time.strptime(s.replace("Z", "+0000"), "%Y-%m-%dT%H:%M:%S%z"))
        return calendar.timegm(time.strptime(s, "%Y-%m-%d"))
    except (ValueError, TypeError):
        return None


def load_claims(path):
    claims = []
    if not os.path.exists(path):
        sys.exit(f"claims file not found: {path}")
    with open(path) as f:
        for n, ln in enumerate(f, 1):
            ln = ln.strip()
            if not ln:
                continue
            try:
                claims.append(json.loads(ln))
            except json.JSONDecodeError as e:
                print(f"WARN {path}:{n} malformed line skipped: {e}", file=sys.stderr)
    return claims


def jira_status_live(key):
    """Unauthenticated probe; the Atlassian cloud is not openly readable, so this
    normally yields 'unfetchable' — the honest outcome, not a fabricated state."""
    url = f"{JIRA_HOST}/rest/api/3/issue/{urllib.parse.quote(key)}?fields=status"
    try:
        out = subprocess.run(["curl", "-s", "-m", "10", "-w", "\n%{http_code}", url],
                             capture_output=True, text=True, timeout=15).stdout
        body, _, code = out.rpartition("\n")
        if code.strip() == "200":
            d = json.loads(body)
            st = d.get("fields", {}).get("status", {})
            return {"name": st.get("name"), "statusCategory": (st.get("statusCategory") or {}).get("key")}
    except Exception:
        pass
    return None  # unfetchable


def normalize_status(raw):
    """Cache entry -> {name, statusCategory} or None."""
    if raw is None:
        return None
    if isinstance(raw, str):
        return {"name": raw, "statusCategory": None}
    if isinstance(raw, dict):
        return {"name": raw.get("name") or raw.get("status"),
                "statusCategory": raw.get("statusCategory")}
    return None


def is_done(status):
    if not status:
        return None
    if status.get("statusCategory") == "done":
        return True
    return (status.get("name") or "").strip().lower() in DONE_STATUSES


def main():
    ap = argparse.ArgumentParser(description="Reconcile integrity claims against live Jira states.")
    ap.add_argument("--claims", default=DEFAULT_CLAIMS)
    ap.add_argument("--jira-status-cache", help="JSON file mapping BSYS keys to status name or object")
    ap.add_argument("--orphan-hours", type=int, default=24)
    args = ap.parse_args()

    claims = load_claims(args.claims)
    cache = {}
    if args.jira_status_cache:
        with open(args.jira_status_cache) as f:
            cache = json.load(f)

    keys = set()
    for c in claims:
        blob = f"{c.get('statement', '')} {json.dumps(c.get('proof') or {})}"
        for m in BSYS_RE.finditer(blob):
            keys.add(f"BSYS-{m.group(1)}")

    live, unfetchable = {}, []
    for k in sorted(keys):
        if k in cache:
            live[k] = normalize_status(cache[k])
            if live[k] is None:
                unfetchable.append(k)
        else:
            st = jira_status_live(k)
            live[k] = st
            if st is None:
                unfetchable.append(k)

    now = time.time()
    orphans, ghosts, clean = [], [], []
    for c in claims:
        cid = c.get("claim_id", "?")
        ts = parse_ts(c.get("ts"))
        age_h = (now - ts) / 3600 if ts else None
        blob = f"{c.get('statement', '')} {json.dumps(c.get('proof') or {})}"
        ckeys = sorted({f"BSYS-{m.group(1)}" for m in BSYS_RE.finditer(blob)})
        row = {"cid": cid, "ts": c.get("ts"), "age_h": age_h, "tier": c.get("tier"),
               "statement": c.get("statement", ""), "keys": ckeys}
        if c.get("tier") == "asserted" and age_h is not None and age_h > args.orphan_hours:
            orphans.append(row)
        claimed_done = bool(DONE_RE.search(c.get("statement", "")))
        contradicted = False
        for k in ckeys:
            st = live.get(k)
            if st and claimed_done and is_done(st) is False:
                contradicted = True
        if contradicted:
            ghosts.append({**row, "jira": {k: live[k] for k in ckeys}})
        if not (c.get("tier") == "asserted" and age_h is not None and age_h > args.orphan_hours) and not contradicted:
            clean.append(row)

    path = os.path.join(KB, "integrity", f"reconcile-report-{REPORT_TS}.md")
    lines = [
        f"# Integrity reconcile — {time.strftime('%Y-%m-%d %H:%M:%S %Z', time.gmtime())}",
        "",
        f"Claims scanned: {len(claims)} | BSYS keys referenced: {len(keys)} | "
        f"orphans: {len(orphans)} | ghosts: {len(ghosts)} | unfetchable keys: {len(unfetchable)}",
        "",
    ]
    if orphans:
        lines += [f"## Orphans — asserted with no proof, older than {args.orphan_hours}h ({len(orphans)})", ""]
        for r in orphans:
            age = f"{r['age_h']:.0f}h" if r["age_h"] is not None else "unknown age"
            lines.append(f"- `{r['cid']}` ({age}, tier={r['tier']}): {r['statement'][:140]}")
        lines.append("")
    if ghosts:
        lines += [f"## Ghosts — claimed done/fixed, Jira contradicts ({len(ghosts)})", ""]
        for r in ghosts:
            js = ", ".join(f"{k}={v['name']}" for k, v in r["jira"].items())
            lines.append(f"- `{r['cid']}` ({r['ts']}): claims done but Jira says {js} — {r['statement'][:140]}")
        lines.append("")
    if unfetchable:
        lines += [f"## Unfetchable Jira keys ({len(unfetchable)})", "",
                  "No cache entry and the unauthenticated probe failed (expected: Jira Cloud requires auth).",
                  "Re-run with --jira-status-cache to resolve these.", ""]
        lines += [f"- {k}" for k in unfetchable] + [""]
    lines += [f"## Clean ({len(clean)})"]
    if not clean:
        lines.append("No clean claims — every claim was flagged or the ledger is empty.")
    for r in clean:
        age = f"{r['age_h']:.0f}h" if r["age_h"] is not None else "?"
        lines.append(f"- `{r['cid']}` ({age}, tier={r['tier']}): {r['statement'][:120]}")

    with open(path, "w") as f:
        f.write("\n".join(lines) + "\n")

    print(f"reconcile: {len(claims)} claims, {len(keys)} BSYS keys")
    print(f"  orphans: {len(orphans)}  ghosts: {len(ghosts)}  unfetchable: {len(unfetchable)}  clean: {len(clean)}")
    print(f"  report -> {path}")
    if orphans or ghosts or unfetchable:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
