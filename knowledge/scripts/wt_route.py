#!/usr/bin/env python3
"""One-command route lookup for the Workato Developer API (wt api passthrough).

Usage:
  wt_route.py <regex>              # search method/path/description
  wt_route.py <regex> -v           # include doc_url in output

Examples:
  wt_route.py 'delete.*collection'
  wt_route.py 'recipe.*version'
  wt_route.py 'table' -v

Source of truth: ~/.claude/knowledge/workato-api/api-index.jsonl
(harvested by workato-api-discover.py from docs.workato.com; refresh with
`wt discover --refresh` if a route 404s — the docs may have moved).
"""
import json
import re
import sys
from pathlib import Path

INDEX = Path.home() / ".claude/knowledge/workato-api/api-index.jsonl"


def main():
    args = [a for a in sys.argv[1:] if a != "-v"]
    show_doc = "-v" in sys.argv
    if not args:
        print(__doc__)
        sys.exit(2)
    pat = re.compile(args[0], re.IGNORECASE)
    if not INDEX.exists():
        print(f"index missing: {INDEX} — run `wt discover --refresh`")
        sys.exit(1)
    hits = 0
    with open(INDEX) as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            d = json.loads(line)
            hay = f"{d.get('method','')} {d.get('path','')} {d.get('description','')} {d.get('group','')}"
            if pat.search(hay):
                hits += 1
                line_out = f"{d['method']:<7} {d['path']:<70} {d.get('description','')[:70]}"
                if show_doc:
                    line_out += f"\n         doc: {d.get('doc_url','')}"
                print(line_out)
    if not hits:
        print("no route matched — try a broader regex, or `wt discover --refresh` to re-harvest")
    else:
        print(f"\n({hits} route(s)) — call via: wt api METHOD <path>   [:id] = path parameter",
              file=sys.stderr)


if __name__ == "__main__":
    main()
