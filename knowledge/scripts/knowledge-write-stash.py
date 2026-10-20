#!/usr/bin/env python3
"""knowledge-write-stash.py — write-discipline stash for bash-append-class ledger
files in the knowledge tree (dreamer proposal 2026-10-15, knowledge-tree write
durability; implemented 2026-10-19).

Why: an unknown parallel git state op (census-confirmed: `git filter-repo --force`
over a dirty tree, reflog destroyed) silently reverts uncommitted bash appends
(runs.jsonl, heartbeat.jsonl, last-sweep.txt, memory cat>>) between write and the
next reverter fire. This script snapshots the mutable ledgers into
~/.claude/knowledge/.stash/<ts>/ every run (launchd com.josh.kb-stash, 15 min),
keeping the last 8 snapshots, so any reverted append is recoverable within 15
minutes. The stash is plain file copies OUTSIDE git history — `git reset --hard`,
`git checkout .`, and `git filter-repo --force` cannot touch it.

Interaction note: session-shadow.py already auto-commits the repo (`git add -A`,
max every 10 min, revert-protection). That protects git-tracked files but died
with the reflog when filter-repo ran; this stash is the git-independent backstop
and also covers gitignored churn ledgers (*.log, build-ledger.jsonl,
usage-ledger.jsonl, slack-posts.jsonl) that git never protects.

Restore:  cp .stash/<ts>/<relpath> <relpath>
Inspect:  ls -t .stash | head -1   (newest snapshot)

Selective by design: only files modified since the previous snapshot are copied;
per-file cap 2 MB, per-run cap 64 MB, skips .git/.stash/__pycache__/people/.
"""

import os
import shutil
import sys
import time

REPO = os.path.expanduser("~/.claude/knowledge")
STASH = os.path.join(REPO, ".stash")
KEEP_SNAPSHOTS = 8
MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_RUN_BYTES = 64 * 1024 * 1024
SKIP_DIRS = {".git", ".stash", "__pycache__", "node_modules", "people"}
EXTS = (".jsonl", ".json", ".log", ".txt")


def is_target(relpath, name):
    if not name.lower().endswith(EXTS):
        return False
    if name.startswith("last-sweep") or "sweep" in name:
        return True  # last-sweep-style .txt ledgers
    return name.lower().endswith((".jsonl", ".json", ".log"))


def newest_snapshot():
    if not os.path.isdir(STASH):
        return None
    snaps = sorted(d for d in os.listdir(STASH) if os.path.isdir(os.path.join(STASH, d)))
    return snaps[-1] if snaps else None


def snapshot():
    ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime())
    dest_root = os.path.join(STASH, ts)
    # same-second collision: never write into a dir that already exists
    n = 1
    while os.path.exists(dest_root):
        ts = time.strftime("%Y%m%dT%H%M%SZ", time.gmtime()) + "-%d" % n
        dest_root = os.path.join(STASH, ts)
        n += 1
    prev = newest_snapshot()
    prev_root = os.path.join(STASH, prev) if prev else None

    os.makedirs(dest_root, exist_ok=True)
    copied, skipped, bytes_copied, errors, linked = 0, 0, 0, 0, 0
    for dirpath, dirnames, filenames in os.walk(REPO):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".stash")]
        for fname in filenames:
            src = os.path.join(dirpath, fname)
            rel = os.path.relpath(src, REPO)
            if not is_target(rel, fname):
                continue
            try:
                st = os.stat(src)
            except OSError:
                continue
            if st.st_size > MAX_FILE_BYTES:
                skipped += 1
                continue
            if bytes_copied + st.st_size > MAX_RUN_BYTES:
                skipped += 1
                continue
            # mtime gate: unchanged since the previous snapshot -> hardlink it
            # in (zero data copy) so every snapshot is a COMPLETE restore point
            if prev_root:
                prev_file = os.path.join(prev_root, rel)
                try:
                    pst = os.stat(prev_file)
                    if pst.st_mtime == st.st_mtime and pst.st_size == st.st_size:
                        dst = os.path.join(dest_root, rel)
                        os.makedirs(os.path.dirname(dst), exist_ok=True)
                        tmp = dst + ".tmp"
                        try:
                            os.link(prev_file, tmp)
                            os.replace(tmp, dst)
                            linked += 1
                            continue
                        except OSError:
                            pass  # fall through to fresh copy
                except OSError:
                    pass
            dst = os.path.join(dest_root, rel)
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            tmp = dst + ".tmp"
            try:
                shutil.copy2(src, tmp)  # atomic: tmp copy then rename
                os.replace(tmp, dst)
                copied += 1
                bytes_copied += st.st_size
            except OSError as e:
                errors += 1
                print("stash-error %s: %s" % (rel, e), file=sys.stderr)

    # prune: keep newest KEEP_SNAPSHOTS snapshot dirs
    pruned = 0
    if os.path.isdir(STASH):
        snaps = sorted(d for d in os.listdir(STASH) if os.path.isdir(os.path.join(STASH, d)))
    else:
        snaps = []
    for old in snaps[:-KEEP_SNAPSHOTS]:
        shutil.rmtree(os.path.join(STASH, old), ignore_errors=True)
        pruned += 1
    print("%s copied=%d linked=%d skipped=%d bytes=%d pruned=%d errors=%d prev=%s"
          % (ts, copied, linked, skipped, bytes_copied, pruned, errors, prev or "none"))
    return 0 if errors == 0 else 1


def restore(ts, relpath):
    """restore <ts> <relpath> — copy one stashed file back over the live file.
    Falls back to the newest snapshot containing the file if <ts> lacks it."""
    src = os.path.join(STASH, ts, relpath)
    if not os.path.isfile(src):
        for snap in sorted(os.listdir(STASH), reverse=True) if os.path.isdir(STASH) else []:
            cand = os.path.join(STASH, snap, relpath)
            if os.path.isfile(cand):
                print("note: %s not in %s, using %s" % (relpath, ts, snap), file=sys.stderr)
                src = cand
                break
        else:
            print("not found in any snapshot: %s" % relpath, file=sys.stderr)
            return 1
    dst = os.path.join(REPO, relpath)
    os.makedirs(os.path.dirname(dst) or REPO, exist_ok=True)
    shutil.copy2(src, dst)
    print("restored %s -> %s" % (src, dst))
    return 0


if __name__ == "__main__":
    if len(sys.argv) >= 2 and sys.argv[1] == "restore":
        sys.exit(restore(sys.argv[2], sys.argv[3]))
    sys.exit(snapshot())
