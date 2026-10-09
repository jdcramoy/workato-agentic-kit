#!/usr/bin/env python3
"""Atomic append for shared multi-agent JSONL ledgers.

Why: plain open(path, 'a') writes can be truncated when a writer crashes or
interleaves with another writer (seen 2026-10-09: build-ledger.jsonl line
4837 truncated mid-record). This helper makes every append all-or-nothing:

  1. flock(EX) on a <path>.lock file — no lost updates between concurrent
     writers (macOS has no flock(1) binary; fcntl.flock is used directly).
  2. Read current content, append the new line(s), write to a temp file in
     the same directory.
  3. os.replace(tmp, path) — atomic on POSIX; readers see either the old or
     the new file, never a half-written one.

Usage (library):
    from atomic_io import atomic_append
    atomic_append(path, json.dumps(rec) + "\\n")        # or pass a dict
    atomic_append(path, {"ts": ...})                    # dict is JSON-encoded

Usage (CLI, for non-Python writers e.g. the guardrails Node hook):
    printf '%s' "$LINE" | python3 atomic_io.py /path/to/ledger.jsonl
"""
import fcntl
import json
import os
import sys
import tempfile


def atomic_append(path, payload):
    """Append payload (str, dict, or list of dicts/str) to path atomically."""
    if isinstance(payload, dict):
        lines = [json.dumps(payload, ensure_ascii=False) + "\n"]
    elif isinstance(payload, (list, tuple)):
        lines = [
            (p if isinstance(p, str) else json.dumps(p, ensure_ascii=False))
            for p in payload
        ]
    elif isinstance(payload, str):
        lines = [payload]
    else:
        raise TypeError(f"unsupported payload type: {type(payload)}")
    data = "".join(l if l.endswith("\n") else l + "\n" for l in lines)

    path = os.path.abspath(str(path))
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)

    lock_path = path + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".jsonl")
        try:
            try:
                with open(path, "rb") as cur:
                    existing = cur.read()
            except FileNotFoundError:
                existing = b""
            with os.fdopen(fd, "wb") as t:
                t.write(existing)
                t.write(data.encode("utf-8"))
                t.flush()
                os.fsync(t.fileno())
            os.replace(tmp, path)  # atomic: readers see old or new, never partial
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


def atomic_write(path, text):
    """Whole-file replacement of path with text, atomically (flock + tmp + replace).

    For read-modify-write callers (e.g. triage queue state transitions) so a
    crash mid-rewrite can never leave a truncated ledger behind.
    """
    path = os.path.abspath(str(path))
    d = os.path.dirname(path)
    os.makedirs(d, exist_ok=True)
    lock_path = path + ".lock"
    with open(lock_path, "w") as lock:
        fcntl.flock(lock.fileno(), fcntl.LOCK_EX)
        fd, tmp = tempfile.mkstemp(dir=d, prefix=".tmp-", suffix=".jsonl")
        try:
            with os.fdopen(fd, "wb") as t:
                t.write(text.encode("utf-8"))
                t.flush()
                os.fsync(t.fileno())
            os.replace(tmp, path)
        except BaseException:
            try:
                os.unlink(tmp)
            except OSError:
                pass
            raise
        finally:
            fcntl.flock(lock.fileno(), fcntl.LOCK_UN)


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: python3 atomic_io.py <ledger.jsonl>  (line on stdin)",
              file=sys.stderr)
        sys.exit(2)
    text = sys.stdin.read()
    if text.strip():
        atomic_append(sys.argv[1], text)
