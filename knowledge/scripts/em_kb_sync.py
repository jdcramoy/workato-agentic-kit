#!/usr/bin/env python3
"""Estate Monitor Tier-1 KB sync.

Syncs the distilled knowledge tree (~/.claude/knowledge) + skill gotcha
catalogs (~/.claude/skills) into Workato Knowledge Bases via the
"EM | KB Sync" API recipe (82993520), which upserts documents by stable
Document ID (= tree-relative path) — idempotent re-runs update in place.

Mapping (one KB per knowledge area, mirroring INDEX.md routing):
  domains/  -> EM KB | Platform Domains      (kb-AbwEDBNg-WMkLdL-CD)
  projects/ -> EM KB | Project Knowledge     (kb-AbwEDC6t-Fk9oN4-CD)
  specs/    -> EM KB | Build Specs          (kb-AbwEDCfs-QTb3D6-CD)
  skills    -> EM KB | Skill Gotcha Catalogs (kb-AbwEDDPL-dxcwTJ-CD)
  INDEX.md  -> routed into Platform Domains (doc id "INDEX.md")

Usage:
  em_kb_sync.py [--all] [--dry-run] [--kb DOMAIN]
    default: only files whose sha256 changed since the last run
    --all:   re-send every file (repair path)
    --dry-run: print what would be sent, POST nothing

Config: WORKATO_KB_SYNC_URL env var overrides the stored webhook URL.
State:  ~/.claude/knowledge/.em-kb-sync-state.json  (path -> sha256)
"""

import argparse
import hashlib
import json
import os
import re
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path

TREE = Path.home() / ".claude" / "knowledge"
SKILLS = Path.home() / ".claude" / "skills"
STATE = TREE / ".em-kb-sync-state.json"
URL_STORE = TREE / ".em-kb-sync-url"

KBS = {
    "domains": "kb-AbwEDBNg-WMkLdL-CD",
    "projects": "kb-AbwEDC6t-Fk9oN4-CD",
    "specs": "kb-AbwEDCfs-QTb3D6-CD",
    "skills": "kb-AbwEDDPL-dxcwTJ-CD",
    "decisions": "kb-AbwJaTQK-pspgFK-CD",
}
GITHUB_PREFIX = "https://github.com/Workato-All/josh-knowledge/blob/main/"

# Decision-bearing knowledge-tree paths -> EM KB | Decisions & Policies
DECISION_DIRS = ["policies", "positions", "claims", "triage", "jira-triage",
                 "regression-canon", "redteam"]

# Harness-path triage transcripts (Builder B's watcher output). One file per
# completed headless triage; parsed best-effort — partial coverage acceptable.
TRANSCRIPTS_DIR = Path.home() / ".local" / "state" / "estate-monitor" / "transcripts"
MEMORY_KB = "kb-AbwJaW4J-RNXcHR-CD"

MAX_DOCS_PER_BATCH = 50
MAX_BYTES_PER_BATCH = 1_500_000  # request body ceiling, well under API limits


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def iter_files():
    """Yield (kb_area, relative_id, Path, source_url_or_None)."""
    idx = TREE / "INDEX.md"
    if idx.exists():
        yield "domains", "INDEX.md", idx, GITHUB_PREFIX + "INDEX.md"

    mapping = {
        "domains": (TREE / "domains", TREE, GITHUB_PREFIX),
        "projects": (TREE / "projects", TREE, GITHUB_PREFIX),
        "specs": (TREE / "specs", TREE, GITHUB_PREFIX),
        "skills": (SKILLS, Path.home() / ".claude", None),
        "decisions": (None, TREE, GITHUB_PREFIX),  # DECISION_DIRS, handled below
    }
    for area, (root, base, url_prefix) in mapping.items():
        if area == "decisions":
            for sub in DECISION_DIRS:
                d = TREE / sub
                if not d.exists():
                    continue
                for p in sorted(d.rglob("*.md")):
                    if p.is_file():
                        rel = p.relative_to(TREE).as_posix()
                        yield area, rel, p, GITHUB_PREFIX + rel
            continue
        if not root.exists():
            continue
        for p in sorted(root.rglob("*.md")):
            if not p.is_file():
                continue
            rel = p.relative_to(base).as_posix()
            if area == "domains" and p.parent != root:
                continue  # domains/ is flat
            url = url_prefix + rel if url_prefix else None
            yield area, rel, p, url


def load_state():
    if STATE.exists():
        return json.loads(STATE.read_text())
    return {}


def save_state(state):
    STATE.write_text(json.dumps(state, indent=1, sort_keys=True))


def load_url():
    url = os.environ.get("WORKATO_KB_SYNC_URL", "").strip()
    if url:
        return url
    if URL_STORE.exists():
        return URL_STORE.read_text().strip()
    return ""


def post_batch(url, sync_id, kb_handle, docs):
    payload = json.dumps({"sync_id": sync_id, "kb_handle": kb_handle, "docs": docs}).encode()
    req = urllib.request.Request(
        url, data=payload, headers={"Content-Type": "application/json"}, method="POST"
    )
    with urllib.request.urlopen(req, timeout=300) as resp:
        return resp.status, resp.read().decode()[:500]


def collect_memory_docs():
    """Best-effort parse of harness triage transcripts -> memory docs.

    Transcript format is whatever the watcher writes (markdown or json);
    we extract the incident key when findable and embed the full transcript.
    Partial coverage is acceptable and expected — say so in the run output.
    """
    docs = []
    if not TRANSCRIPTS_DIR.exists():
        return docs, "transcripts dir absent (watcher not built/running yet)"
    files = sorted(TRANSCRIPTS_DIR.rglob("*"))
    files = [p for p in files if p.is_file() and p.suffix in (".md", ".json", ".txt")]
    for p in files:
        try:
            body = p.read_text(errors="replace")
        except Exception:  # noqa: BLE001
            continue
        if not body.strip():
            continue
        rel = p.relative_to(TRANSCRIPTS_DIR).as_posix()
        m = re.search(r"recipe_(?:failed|stop_user|stop_workato)\|[^\s'\"]+|connection\|[^\s'\"]+|degraded\|[^\s'\"]+", body)
        incident = m.group(0) if m else ""
        title = f"triage-mem: {incident or rel}"
        doc = {
            "id": "transcripts/" + rel,
            "title": title,
            "body": (
                "# Harness-path triage transcript\n\n"
                f"*Incident:* {incident or 'unparsed'}\n"
                f"*Source:* harness watcher transcript `{rel}`\n\n"
                + body
            ),
            "source_url": "",
        }
        docs.append(doc)
    return docs, f"{len(files)} transcript files found"


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--all", action="store_true", help="re-send every file, not just changed")
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--kb", choices=list(KBS), help="limit to one KB area")
    ap.add_argument("--memory", action="store_true",
                    help="sync harness triage transcripts into EM KB | Triage Memory instead of the tree")
    args = ap.parse_args()

    url = load_url()
    if not url and not args.dry_run:
        print("ERROR: no sync URL. Set WORKATO_KB_SYNC_URL or run once with the "
              "webhook stored in " + str(URL_STORE), file=sys.stderr)
        sys.exit(2)

    if args.memory:
        docs, note = collect_memory_docs()
        state = load_state()
        changed, new_state = [], dict(state)
        for doc in docs:
            digest = hashlib.sha256(doc["body"].encode()).hexdigest()
            key = doc["id"]
            new_state["mem:" + key] = digest
            if not args.all and state.get("mem:" + key) == digest:
                continue
            changed.append(doc)
        if args.dry_run:
            print(f"DRY RUN (memory): {note}; would send {len(changed)} docs")
            return
        sent, failures = 0, []
        for i in range(0, len(changed), MAX_DOCS_PER_BATCH):
            batch = changed[i:i + MAX_DOCS_PER_BATCH]
            if sum(len(d["body"].encode()) for d in batch) > MAX_BYTES_PER_BATCH:
                for d in batch:  # oversized batch: send singly
                    try:
                        post_batch(url, f"memory-{int(time.time())}", MEMORY_KB, [d])
                        sent += 1
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"{d['id']}: {e}")
                continue
            try:
                post_batch(url, f"memory-{int(time.time())}", MEMORY_KB, batch)
                sent += len(batch)
            except Exception as e:  # noqa: BLE001
                failures.append(f"memory batch: {e}")
        if not failures:
            save_state(new_state)
        print(f"MEMORY SYNC COMPLETE: {note}; {sent} docs sent"
              + (f"; {len(failures)} FAILED (state not advanced)" if failures else ""))
        for f in failures:
            print("  FAIL: " + f)
        sys.exit(1 if failures else 0)

    state = load_state()
    new_state = dict(state)
    pending = {}  # area -> list of doc dicts
    seen = set()

    for area, rel, path, src in iter_files():
        if args.kb and area != args.kb:
            continue
        seen.add(rel)
        digest = sha256_of(path)
        new_state[rel] = digest
        if not args.all and state.get(rel) == digest:
            continue
        try:
            body = path.read_text(errors="replace")
        except Exception as e:  # noqa: BLE001
            print(f"WARN: unreadable {rel}: {e}")
            continue
        pending.setdefault(area, []).append(
            {
                "id": rel,
                "title": rel,
                "body": body,
                "source_url": src or "",
            }
        )

    # Files that vanished: keep their last synced state (deletes are manual,
    # deliberate — never auto-delete knowledge from the genie).

    total_sent = 0
    failures = []
    for area, docs in sorted(pending.items()):
        kb = KBS[area]
        batch, batch_bytes = [], 0
        for doc in docs:
            size = len(doc["body"].encode())
            if batch and (len(batch) >= MAX_DOCS_PER_BATCH or batch_bytes + size > MAX_BYTES_PER_BATCH):
                if not args.dry_run:
                    try:
                        post_batch(url, f"{area}-{int(time.time())}", kb, batch)
                    except Exception as e:  # noqa: BLE001
                        failures.append(f"{area} batch: {e}")
                        continue
                print(f"  {area}: posted batch of {len(batch)} docs ({batch_bytes} bytes) -> {kb}")
                total_sent += len(batch)
                batch, batch_bytes = [], 0
            batch.append(doc)
            batch_bytes += size
        if batch:
            if not args.dry_run:
                try:
                    post_batch(url, f"{area}-{int(time.time())}", kb, batch)
                except Exception as e:  # noqa: BLE001
                    failures.append(f"{area} batch: {e}")
                    continue
            print(f"  {area}: posted batch of {len(batch)} docs ({batch_bytes} bytes) -> {kb}")
            total_sent += len(batch)

    if args.dry_run:
        n = sum(len(v) for v in pending.values())
        print(f"DRY RUN: would send {n} changed docs; total synced state {len(seen)} files")
        return

    if not failures:
        save_state(new_state)

    print(f"SYNC COMPLETE: {total_sent} docs sent"
          + (f"; {len(failures)} FAILED batches (state not advanced):" if failures else ""))
    for f in failures:
        print("  FAIL: " + f)
    sys.exit(1 if failures else 0)


if __name__ == "__main__":
    main()
