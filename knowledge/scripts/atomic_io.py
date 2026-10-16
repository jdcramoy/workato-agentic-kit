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
import datetime as dt
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


class SchemaViolation(ValueError):
    """A row failed its ledger schema. Loud refusal — never silent coercion."""


# The three-formats-in-one-ledger class (2026-10-11: heartbeat.jsonl carried
# Z-suffix, +00:00, +0000, -04:00 AND naive timestamps in one file). A valid
# timestamp is ISO-8601 WITH a timezone offset; naive local time is rejected.
def _validate_timestamp(name, value):
    if not isinstance(value, str):
        return f"{name}: timestamp must be a string, got {type(value).__name__}"
    try:
        # Z suffix is valid ISO-8601 but only parses natively on Python 3.11+;
        # this repo runs on 3.9 (mission-control.py fold() already normalizes
        # the same way). Normalize before parsing.
        parsed = dt.datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return f"{name}: not ISO-8601 ({value!r})"
    if parsed.tzinfo is None or parsed.tzinfo.utcoffset(parsed) is None:
        return (f"{name}: naive timestamp {value!r} rejected — ISO-8601 WITH "
                f"timezone offset required (e.g. ...Z or ...+00:00); the "
                f"2026-10-11 heartbeat.jsonl three-format incident is the class")
    return None


def validate_row(row, schema):
    """Return a list of schema violations for row (empty list = valid).

    Schema keys (all optional, unknown keys are rejected so a typo'd schema
    can never silently validate nothing):
      required:   [field, ...]        key must be present
      enums:      {field: set(...)}   value must be in the set (None skips —
                                      optional enum fields use None as "unset")
      timestamps: [field, ...]        value must be ISO-8601 WITH tz offset
                                      (None skips — unset timestamp is fine)
    """
    if not isinstance(schema, dict):
        return [f"schema must be a dict, got {type(schema).__name__}"]
    unknown = set(schema) - {"required", "enums", "timestamps"}
    if unknown:
        return [f"schema has unknown key(s) {sorted(unknown)} — "
                f"allowed: required, enums, timestamps"]
    if not isinstance(row, dict):
        return [f"row must be a dict, got {type(row).__name__}"]
    errs = []
    for field in schema.get("required", []):
        if field not in row:
            errs.append(f"missing required field '{field}'")
    for field, allowed in schema.get("enums", {}).items():
        if field in row and row[field] is not None and row[field] not in allowed:
            errs.append(f"{field}: {row[field]!r} not in enum "
                        f"{sorted(allowed) if isinstance(allowed, (set, frozenset)) else list(allowed)}")
    for field in schema.get("timestamps", []):
        if field in row and row[field] is not None:
            err = _validate_timestamp(field, row[field])
            if err:
                errs.append(err)
    return errs


def atomic_append_validated(path, row, schema):
    """Validate row against schema, then atomic_append it. All-or-nothing:
    an invalid row raises SchemaViolation and writes NOTHING (loud refusal,
    never silent coercion). Valid rows go through the same flock + tmp +
    os.replace path as atomic_append."""
    errs = validate_row(row, schema)
    if errs:
        raise SchemaViolation(
            f"refused append to {os.path.abspath(str(path))}: "
            + "; ".join(errs))
    atomic_append(path, row if isinstance(row, dict) else json.dumps(row))


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
