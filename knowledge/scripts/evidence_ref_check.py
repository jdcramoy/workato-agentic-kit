#!/usr/bin/env python3
"""evidence_ref_check.py — mechanical resolution check for triage evidence pointers.

Born from the 2026-10-17 triage evidence gate proposal (dreamer, accepted):
a triage verdict card citing evidence that nobody can resolve is the
fabricated-verdict class. This script RESOLVES a pointer the way the
renderer must — it cannot lie about file existence the way an agent
summarizing can.

Accepted pointer forms (explicit prefixes win; bare tokens are auto-detected):

  https://... / http://...    URL — must be http(s), scheme-checked
  file:<path>  or a path      FILE — must exist on disk (~/ and relative ok)
  bus:<thread-id>             BUS — thread must resolve in the gossip bus
                              (knowledge/dreams/bus/*.jsonl `thread` field —
                              the same store the brain_bus tool serves)
  job:<recipe>:<job-handle>   JOB — fetched live via `wt jobs get <recipe> <job>`
                              (a bare `j-...` handle without a recipe FAILS:
                              use the recipe:job form)

Multiple pointers may be passed; ALL must resolve for exit 0.

Exit codes: 0 = every pointer resolves, 1 = at least one does not.
Each pointer gets exactly one line:  PASS: ...  or  FAIL: <reason>

Usage:
  evidence_ref_check.py <pointer> [pointer ...]

In skill text: the /triage card renderer runs this on every card's
evidence_ref; any FAIL renders `| UNVERIFIED — do not dispatch` on the
card and blocks auto-dispatch. Exit code is the verdict; the reason line
is for the human.
"""
import glob
import json
import os
import re
import subprocess
import sys

HOME = os.path.expanduser("~")
BUS_DIR = os.path.join(HOME, ".claude", "knowledge", "dreams", "bus")
WT = "wt"
WT_TIMEOUT = 45  # seconds; wt jobs get is one API call

JOB_RE = re.compile(r"^\d+:[A-Za-z0-9_.\-]+$")   # recipe:job-handle
BARE_HANDLE_RE = re.compile(r"^j-[A-Za-z0-9_.\-]+$")


def resolve_url(ptr):
    if re.match(r"^https?://", ptr):
        return True, "URL with http(s) scheme"
    return False, f"not an http(s) URL: scheme must be http:// or https://"


def resolve_file(ptr):
    path = os.path.expanduser(ptr)
    if os.path.exists(path):
        return True, f"file exists: {path}"
    return False, f"file does not exist: {path}"


def bus_threads():
    """All thread ids ever posted, from the per-agent JSONL store the
    brain_bus tool reads."""
    threads = set()
    for f in glob.glob(os.path.join(BUS_DIR, "*.jsonl")):
        try:
            with open(f) as fh:
                for line in fh:
                    line = line.strip()
                    if not line:
                        continue
                    try:
                        rec = json.loads(line)
                    except json.JSONDecodeError:
                        continue  # a torn tail line must not break the check
                    t = rec.get("thread") or rec.get("subject")
                    if t:
                        threads.add(t)
        except OSError:
            continue
    return threads


def resolve_bus(ptr, threads=None):
    tid = ptr.split(":", 1)[1] if ptr.startswith("bus:") else ptr
    if not tid:
        return False, "empty bus thread id"
    threads = threads if threads is not None else bus_threads()
    if tid in threads:
        return True, f"bus thread resolves: {tid}"
    return False, f"bus thread not found in {BUS_DIR}: {tid}"


def resolve_job(ptr):
    body = ptr.split(":", 1)[1] if ptr.startswith("job:") else ptr
    if ":" not in body:
        if BARE_HANDLE_RE.match(body):
            return False, (f"bare job handle '{body}' cannot be fetched — "
                           f"use the recipe:job form, e.g. job:812345:{body}")
        return False, f"job pointer must be recipe:job form, got: {ptr}"
    recipe, handle = body.split(":", 1)
    if not recipe.isdigit() or not handle:
        return False, f"job pointer must be <numeric recipe>:<job handle>, got: {body}"
    try:
        proc = subprocess.run(
            [WT, "jobs", "get", recipe, handle],
            capture_output=True, text=True, timeout=WT_TIMEOUT,
        )
    except FileNotFoundError:
        return False, "wt CLI not found — cannot fetch job"
    except subprocess.TimeoutExpired:
        return False, f"wt jobs get {recipe} {handle} timed out after {WT_TIMEOUT}s"
    if proc.returncode == 0 and proc.stdout.strip():
        return True, f"job fetches: recipe {recipe}, handle {handle}"
    return False, (f"wt jobs get {recipe} {handle} failed "
                   f"(exit {proc.returncode}): {(proc.stdout or proc.stderr).strip()[:120]}")


def resolve(ptr, threads=None):
    ptr = ptr.strip()
    if not ptr:
        return False, "empty evidence pointer"
    if ptr.startswith(("http://", "https://")):
        return resolve_url(ptr)
    if re.match(r"^[a-z][a-z0-9+.\-]*://", ptr):
        return False, "not an http(s) URL: only http:// and https:// are accepted"
    if ptr.startswith("file:"):
        return resolve_file(ptr.split(":", 1)[1])
    if ptr.startswith("bus:"):
        return resolve_bus(ptr)
    if ptr.startswith("job:"):
        return resolve_job(ptr)
    # bare-token auto-detection
    if JOB_RE.match(ptr):
        return resolve_job(ptr)
    if BARE_HANDLE_RE.match(ptr):
        return resolve_job(ptr)
    if "/" in ptr or ptr.startswith("~"):
        return resolve_file(ptr)
    # last resort: bus thread id (the triage skill cites bare thread ids
    # like triage-taste), then a relative file path
    ok, reason = resolve_bus(ptr, threads)
    if ok:
        return ok, reason
    ok2, reason2 = resolve_file(ptr)
    if ok2:
        return ok2, reason2
    return False, (f"unrecognized pointer (tried bus thread, then file): {ptr} — {reason}")


def main():
    args = [a for a in sys.argv[1:] if a not in ("-h", "--help")]
    if not args:
        sys.exit(__doc__)
    threads = bus_threads()  # one read for all pointers
    failed = 0
    for ptr in args:
        ok, reason = resolve(ptr, threads)
        print(f"{'PASS' if ok else 'FAIL'}: {ptr} — {reason}")
        if not ok:
            failed += 1
    sys.exit(1 if failed else 0)


if __name__ == "__main__":
    main()
