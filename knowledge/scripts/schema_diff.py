#!/usr/bin/env python3
"""Schema-diff a transformed data file against the original it will replace.

Usage: schema_diff.py <old> <new>

Exit 0 = no fields dropped (or no comparable schema). Exit 1 = dropped
fields exist; prints them. Used by the extend-not-replace pre-write gate.
"""
import csv
import json
import sys


def fields_of(path):
    """Return the set of top-level field names, or None if not structured."""
    try:
        if path.endswith((".csv", ".tsv")):
            with open(path, newline="", errors="replace") as fh:
                delim = "\t" if path.endswith(".tsv") else ","
                row = next(csv.reader(fh, delimiter=delim), None)
            return set(row) if row else None
        with open(path, errors="replace") as fh:
            first = fh.read(1)
            fh.seek(0)
            if first == "[":
                data = json.load(fh)
                return set(data[0]) if isinstance(data, list) and data else None
            if first == "{":
                first_obj = None
                decoder = json.JSONDecoder()
                buf = fh.read().lstrip()
                if buf.startswith("{"):
                    obj, _ = decoder.raw_decode(buf)
                    first_obj = obj
                elif buf.startswith("}\n{") or "\n{" in buf[:2]:  # pragma: no cover
                    pass
                if isinstance(first_obj, dict):
                    return set(first_obj)
            # JSONL
            fh.seek(0)
            for line in fh:
                line = line.strip()
                if line:
                    obj = json.loads(line)
                    return set(obj) if isinstance(obj, dict) else None
    except Exception:
        return None
    return None


def main():
    if len(sys.argv) != 3:
        print(__doc__)
        return 2
    old, new = fields_of(sys.argv[1]), fields_of(sys.argv[2])
    if old is None or new is None:
        print("schema_diff: no comparable structured schema (skip)")
        return 0
    dropped = sorted(old - new)
    if dropped:
        print("DROPPED FIELDS: " + ", ".join(dropped))
        return 1
    added = sorted(new - old)
    print("no fields dropped" + (f"; added: {', '.join(added)}" if added else ""))
    return 0


if __name__ == "__main__":
    sys.exit(main())
