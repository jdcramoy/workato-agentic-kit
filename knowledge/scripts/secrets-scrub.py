#!/usr/bin/env python3
"""secrets-scrub.py — find live credentials sitting in session transcripts.

The 2026-10-07 lesson: a prod token pasted into chat lives in the session
JSONL forever. This scans ~/.claude/projects/**/*.jsonl for credential-shaped
strings and reports them. With --scrub, it rewrites the offending lines
in place (backup first to <file>.prescrub).

Default is report-only. Scrubbing rewrites history; do it deliberately.

Usage: secrets-scrub.py [--scrub] [--days 30]
"""

import argparse
import glob
import json
import os
import re
import shutil
import sys

PROJECTS = os.path.expanduser("~/.claude/projects")

PATTERNS = [
    ("workato-token", re.compile(r"wrkaus-[A-Za-z0-9._-]{40,}")),
    ("sk-key", re.compile(r"\bsk-[A-Za-z0-9_-]{20,}")),
    ("bearer", re.compile(r"Bearer\s+[A-Za-z0-9._~+/=-]{24,}")),
    ("xox", re.compile(r"xox[baprs]-[A-Za-z0-9-]{10,}")),
    ("github-pat", re.compile(r"(ghp_|github_pat_)[A-Za-z0-9_]{20,}")),
]


def scan_file(path, days):
    hits = []
    try:
        if days and (os.path.getmtime(path) < __import__("time").time() - days * 86400):
            return hits
    except OSError:
        return hits
    try:
        with open(path, errors="replace") as fh:
            for n, line in enumerate(fh, 1):
                for name, pat in PATTERNS:
                    for m in pat.finditer(line):
                        hits.append((n, name, m.group(0)[:18] + "…"))
    except OSError:
        pass
    return hits


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--scrub", action="store_true")
    ap.add_argument("--days", type=int, default=30)
    a = ap.parse_args()

    total_files = 0
    total_hits = 0
    for path in sorted(glob.glob(os.path.join(PROJECTS, "**", "*.jsonl"), recursive=True)):
        hits = scan_file(path, a.days)
        if not hits:
            continue
        total_files += 1
        total_hits += len(hits)
        print(f"\n{os.path.relpath(path, PROJECTS)}: {len(hits)} hit(s)")
        for n, name, preview in hits[:10]:
            print(f"  line {n}: {name}  {preview}")
        if a.scrub:
            shutil.copy2(path, path + ".prescrub")
            body = open(path, errors="replace").read()
            for _, pat in PATTERNS:
                body = pat.sub(lambda m: m.group(0)[:10] + "[SCRUBBED]", body)
            with open(path, "w") as fh:
                fh.write(body)
            print(f"  scrubbed (backup: {os.path.basename(path)}.prescrub)")

    print(f"\n{total_files} files with hits, {total_hits} credential-shaped strings"
          + (" — scrubbed" if a.scrub else " (report only; re-run with --scrub to redact)"))
    return 0 if total_hits == 0 else 2


if __name__ == "__main__":
    sys.exit(main())
