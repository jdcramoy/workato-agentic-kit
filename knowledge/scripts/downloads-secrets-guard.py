#!/usr/bin/env python3
"""downloads-secrets-guard.py — flag secrets-shaped files in ~/Downloads.

Triage finding: downloads-plaintext-secrets-hygiene (Josh approved purge +
guard, 2026-10-22). Name+mode scan only — never reads file contents.

Appends a report row to knowledge/reports/secrets-guard.jsonl and posts to
the gossip bus (thread secrets-guard) when something secrets-shaped is found.
"""
import glob
import json
import os
import datetime as dt

HOME = os.path.expanduser("~")
DL = os.path.join(HOME, "Downloads")
OUT = os.path.join(HOME, ".claude/knowledge/reports/secrets-guard.jsonl")
BUS = os.path.join(HOME, ".claude/knowledge/dreams/bus")
AGENT = "downloads-secrets-guard"

# name+mode heuristics only — no content reads
NAME_PATTERNS = [
    "keychain", "credentials", "credential", "secret", "secrets", "token",
    "client_secret", "api-key", "apikey", "api_key", "private-key",
    "private_key", "id_rsa", "password",
]
SUSPECT_EXT = {".json", ".txt", ".env", ".csv", ".yaml", ".yml", ".xml", ".pem", ".p12", ".pfx"}


def write_bus(thread, text, kind="finding"):
    path = os.path.join(BUS, f"{AGENT}.jsonl")
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "agent": AGENT,
        "thread": thread,
        "kind": kind,
        "text": text,
    }
    try:
        os.makedirs(BUS, exist_ok=True)
        with open(path, "a") as fh:
            fh.write(json.dumps(row) + "\n")
        return True
    except OSError:
        return False


def scan():
    findings = []
    for p in glob.glob(os.path.join(DL, "*")):
        if not os.path.isfile(p):
            continue
        base = os.path.basename(p).lower()
        if not base.endswith(tuple(SUSPECT_EXT)):
            continue
        name_hit = next((pat for pat in NAME_PATTERNS if pat in base), None)
        if not name_hit:
            continue
        mode = oct(os.stat(p).st_mode & 0o777)
        loose = mode in ("0o644", "0o666", "0o665")
        findings.append({"file": base, "mode": mode, "hit": name_hit, "loose_mode": loose})
    return findings


def main():
    findings = scan()
    row = {
        "ts": dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ"),
        "scanned": DL,
        "findings": findings,
    }
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    with open(OUT, "a") as fh:
        fh.write(json.dumps(row) + "\n")
    if findings:
        msg = "secrets-shaped files in ~/Downloads: " + ", ".join(
            f"{f['file']} (mode {f['mode']}{', LOOSE MODE' if f['loose_mode'] else ''})" for f in findings
        )
        write_bus("secrets-guard", msg)


if __name__ == "__main__":
    main()
