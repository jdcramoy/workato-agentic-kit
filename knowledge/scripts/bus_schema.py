#!/usr/bin/env python3
"""bus_schema.py — one schema + dedup gate for every gossip-bus writer.

Born 2026-10-22 (triage bus-writer-duplicate-malformed-lines): writers emitted
duplicate and malformed lines — live count 2026-10-22, last-24h window across
~/.claude/knowledge/dreams/bus/*.jsonl: 116 lines, 54 missing at least one
required field, 24 with no ts at all, 10 exact duplicates (the dissenter's
findings posted 5-8x). Every writer now goes through write_row():

  * REQUIRED fields (minimum): ts, agent, thread, kind — missing fields are a
    loud refusal at append time, never silent coercion (predict.py's store
    rule, applied bus-wide).
  * NORMALIZATION: thread_id -> thread, type/event -> kind, epoch or bare-date
    or naive ts -> UTC Z ISO — the shape the fan-in merge and every reader
    already assume.
  * DEDUP: a row whose content (every field except ts) already exists in the
    outbox is skipped, not re-appended. Duplicates collapse at write time so
    no reader ever has to.

Readers: gossip-read.py's fan-in merge collapses any historical repeats that
predate this gate. History files are never rewritten.
"""

from __future__ import annotations

import datetime as _dt
import json
from pathlib import Path

from atomic_io import atomic_append

REQUIRED = ("ts", "agent", "thread", "kind")
# how far back one write scans for a content duplicate (these outboxes are
# hundreds of lines; a full scan is cheap and bounded here anyway)
_DEDUP_SCAN_LINES = 2000


class BusSchemaError(ValueError):
    """A row failed the minimum bus schema. Refused loudly."""


def normalize(rec: dict, default_agent: str | None = None) -> dict:
    """Normalize one row in place (returns a copy): thread_id/type aliases,
    agent default, ts coerced to UTC Z ISO."""
    out = dict(rec)
    if not out.get("thread") and out.get("thread_id"):
        out["thread"] = out["thread_id"]
    if not out.get("kind"):
        for alias in ("type", "event"):
            if out.get(alias):
                out["kind"] = out[alias]
                break
    if default_agent and not out.get("agent"):
        out["agent"] = default_agent
    out["ts"] = _coerce_ts(out.get("ts"))
    return out


def _coerce_ts(ts) -> str:
    if isinstance(ts, (int, float)):
        return _dt.datetime.fromtimestamp(
            ts, _dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    s = str(ts or "").strip()
    if not s:
        return _dt.datetime.now(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
    if len(s) == 10 and s[4] == "-":  # bare date, e.g. 2026-10-22
        s += "T00:00:00Z"
    if s.endswith("Z"):
        s = s[:-1] + "+00:00"
    try:
        d = _dt.datetime.fromisoformat(s)
    except ValueError:
        raise BusSchemaError(f"unparseable ts {ts!r}") from None
    if d.tzinfo is None:
        d = d.replace(tzinfo=_dt.timezone.utc)  # naive = UTC by convention
    return d.astimezone(_dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def missing(rec: dict) -> list[str]:
    return [k for k in REQUIRED if not rec.get(k)]


def dedup_key(rec: dict) -> str:
    """Content identity: every field except ts (ts always moves)."""
    body = {k: v for k, v in rec.items() if k != "ts"}
    return json.dumps(body, sort_keys=True, default=str)


def is_duplicate(path, rec: dict) -> bool:
    key = dedup_key(rec)
    try:
        with open(path, errors="replace") as fh:
            tail = fh.readlines()[-_DEDUP_SCAN_LINES:]
    except OSError:
        return False
    for line in tail:
        line = line.strip()
        if not line:
            continue
        try:
            existing = json.loads(line)
        except Exception:
            continue
        if dedup_key(normalize(existing)) == key:
            return True
    return False


def write_row(path, rec: dict, default_agent: str | None = None) -> dict:
    """Validate + normalize + dedup, then atomically append. Returns the row
    actually written (with 'dedup_skipped': True when suppressed instead)."""
    path = Path(path)
    rec = normalize(rec, default_agent=default_agent)
    bad = missing(rec)
    if bad:
        raise BusSchemaError(
            f"bus row refused, missing required fields {bad}: "
            f"{json.dumps(rec, default=str)[:300]}")
    if is_duplicate(path, rec):
        suppressed = dict(rec)
        suppressed["dedup_skipped"] = True
        return suppressed
    atomic_append(path, rec)
    return rec
