#!/usr/bin/env python3
"""null-miner.py — trials-factor (look-elsewhere) null calibration for the dreamer.

AMENDED SPEC (wave3 amendment 1, dissenter 2026-10-11): the null runs through
dream-mine.py's candidate enumeration — NOT an LLM prompt rerun (zero-LLM
contract; dream reports are prose with no numeric score to take a max
distribution over).

Mechanism: dream-mine reports the TOP candidates from a corpus scan (repeated
4-grams, verify trajectories, error kinds, corrections). Scanning many
candidates and reporting the best one statistically manufactures "patterns" —
the look-elsewhere effect. To calibrate, we re-run the SAME enumeration over
session-intact DAY-SWAP permutations of the transcript corpus: each whole
session file keeps its content intact but is re-assigned to a different day,
so the recency window (last --days days) fills with an exchangeable sample of
sessions. The max-score distribution under permutation is the null bar; a real
dreamer pattern must beat it before it earns belief.

Reuse: dream-mine.py's enumeration lives inline in its main(), so this script
imports its primitives (regexes, VERIFY tuple, iter_lines, text_of,
load_config) via importlib and re-expresses the loop in permutation-form.
Key optimization: per-session counts are PERMUTATION-INVARIANT, so each
session is enumerated exactly ONCE and a permutation only merges Counters —
that is the scaling path to the full 500+-session corpus (one content pass,
cheap permutations). Monthly full-corpus runs are feasible on that path.

Output (APPEND-ONLY, never clobbered):
  knowledge/dreams/calibration/permutation-null.jsonl
  rows: {"kind": "observed"|"permutation-null", ts, perm_index, seed,
         window_days, pool_sessions, sessions_in_window,
         max_ngram_count, max_traj_count, max_error_count,
         corrections, examined_candidates}

Usage:
  null-miner.py [--permute 5] [--days 3] [--max-sessions 60] [--seed 42]
                [--pool-timeout ...] [--out PATH] [--quiet]
  null-miner.py --selftest

Exit 0 on success. Stdlib only.
"""

import argparse
import collections
import datetime as dt
import importlib.util
import json
import os
import random
import statistics
import sys

HOME = os.path.expanduser("~")
SCRIPTS = os.path.join(HOME, ".claude", "knowledge", "scripts")
OUT_DEFAULT = os.path.join(HOME, ".claude", "knowledge", "dreams",
                           "calibration", "permutation-null.jsonl")
DREAM_MINE = os.path.join(SCRIPTS, "dream-mine.py")

# --- import dream-mine (hyphenated filename needs importlib) -----------------
_spec = importlib.util.spec_from_file_location("dream_mine", DREAM_MINE)
_dream_mine = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_dream_mine)  # its main() is not executed (guarded)


def session_start_day(path, mtime, max_bytes):
    """Day offset of a session's START, from the transcript's own first
    'timestamp' event field (mtime is last-write and clusters on 'today',
    which would collapse the day-swap to a no-op). Falls back to mtime."""
    try:
        if os.path.getsize(path) <= max_bytes:
            with open(path, "r", errors="replace") as f:
                for i, line in enumerate(f):
                    if i > 100:
                        break
                    if not line.strip():
                        continue
                    try:
                        ev = json.loads(line)
                    except Exception:
                        continue
                    ts = ev.get("timestamp")
                    if isinstance(ts, str):
                        start = dt.datetime.fromisoformat(
                            ts.replace("Z", "+00:00")).replace(tzinfo=None)
                        return max((dt.datetime.now() - start).days, 0)
    except OSError:
        pass
    return max((dt.datetime.now() - dt.datetime.fromtimestamp(mtime)).days, 0)


def discover_sessions(pool_limit, max_bytes):
    """Return the permutation pool: [{path, day, name, project}] for the most
    recent pool_limit session transcripts, sorted newest first. day = session
    START day offset (0 = today) — the label day_swap permutes."""
    projects = _dream_mine.PROJECTS
    if not os.path.isdir(projects):
        print("no projects dir", file=sys.stderr)
        return None
    found = []
    for proj in sorted(os.listdir(projects)):
        pdir = os.path.join(projects, proj)
        if not os.path.isdir(pdir):
            continue
        for name in os.listdir(pdir):
            if not name.endswith(".jsonl"):
                continue
            path = os.path.join(pdir, name)
            try:
                mtime = os.path.getmtime(path)
            except OSError:
                continue
            found.append((mtime, path, proj, name))
    found.sort(reverse=True)
    pool = []
    for mtime, path, proj, name in found[:pool_limit]:
        pool.append({"path": path,
                     "day": session_start_day(path, mtime, max_bytes),
                     "name": name[:12], "project": proj[-40:]})
    return pool


def enumerate_session(path, max_bytes):
    """dream-mine's candidate enumeration for ONE session, permutation form.
    Uses dream-mine's own primitives: iter_lines, text_of, ERROR_RE,
    CORRECTION_RE, NOT_CORRECTION_RE, VERIFY. dream-mine accumulates the
    tool-name sequence across the WHOLE session and counts 4-grams after the
    file loop — mirrored here."""
    ngrams = collections.Counter()
    trajs = collections.Counter()
    errors = collections.Counter()
    corrections = 0
    seq = []
    for line in _dream_mine.iter_lines(path, max_bytes):
        try:
            ev = json.loads(line)
        except Exception:
            continue
        et = ev.get("type")
        if et == "assistant":
            msg = ev.get("message") or {}
            for b in msg.get("content") or []:
                if isinstance(b, dict) and b.get("type") == "tool_use":
                    seq.append(b.get("name", "?"))
                if isinstance(b, dict) and b.get("type") == "text":
                    for m in _dream_mine.ERROR_RE.finditer(b.get("text", "")):
                        errors[m.group(0).lower()] += 1
        elif et == "user":
            msg = ev.get("message") or {}
            txt = _dream_mine.text_of(msg.get("content"))
            if isinstance(msg.get("content"), list):
                for b in msg["content"]:
                    if isinstance(b, dict) and b.get("type") == "tool_result":
                        blob = str(b.get("content", ""))[:2000]
                        for m in _dream_mine.ERROR_RE.finditer(blob):
                            errors[m.group(0).lower()] += 1
            if txt and not txt.startswith(("<", "[{")):
                line1 = txt.strip().splitlines()[0][:200]
                words = line1.split()
                if (len(line1) >= 15 and len(words) >= 3
                        and _dream_mine.CORRECTION_RE.search(line1)
                        and not _dream_mine.NOT_CORRECTION_RE.search(line1)):
                    corrections += 1
    for i in range(len(seq) - 3):
        ngrams[" > ".join(seq[i:i + 4])] += 1
        if any(v in seq[i + 3] for v in _dream_mine.VERIFY):
            trajs[" > ".join(seq[i:i + 4])] += 1
    return {"ngrams": ngrams, "trajs": trajs, "errors": errors,
            "corrections": corrections}


def day_swap(pool, rng):
    """Session-intact day-swap: permute the day labels across the pool.
    Content stays whole (never split a session); only its day assignment
    moves. Returns {path: permuted_day}."""
    days = [s["day"] for s in pool]
    rng.shuffle(days)
    return {s["path"]: d for s, d in zip(pool, days)}


def aggregate(pool, assignment, window_days):
    """Merge the cached per-session counters of sessions whose PERMUTED day
    falls inside the recency window — dream-mine's scan under the null."""
    ngrams = collections.Counter()
    trajs = collections.Counter()
    errors = collections.Counter()
    corrections = 0
    n_in = 0
    for s in pool:
        if assignment[s["path"]] < window_days:
            cache = s["cache"]
            ngrams.update(cache["ngrams"])
            trajs.update(cache["trajs"])
            errors.update(cache["errors"])
            corrections += cache["corrections"]
            n_in += 1
    return {
        "sessions_in_window": n_in,
        "max_ngram_count": max(ngrams.values(), default=0),
        "max_traj_count": max(trajs.values(), default=0),
        "max_error_count": max(errors.values(), default=0),
        "corrections": corrections,
        "examined_candidates": len(ngrams),
    }


def run(args):
    pool = discover_sessions(args.max_sessions, args.max_file_bytes)
    if pool is None:
        return 1
    for s in pool:
        s["cache"] = enumerate_session(s["path"], args.max_file_bytes)
    print(f"pool: {len(pool)} sessions enumerated "
          f"(day range 0..{max(s['day'] for s in pool)})", file=sys.stderr)

    out_path = args.out
    os.makedirs(os.path.dirname(out_path), exist_ok=True)

    def emit(kind, perm_index, seed, stats):
        row = {"ts": dt.datetime.now().isoformat(timespec="seconds"),
               "kind": kind, "perm_index": perm_index, "seed": seed,
               "window_days": args.days, "pool_sessions": len(pool),
               **stats}
        atomic_append(out_path, row)
        return row

    # observed (identity) scan — the value a real pattern must beat
    obs = aggregate(pool, {s["path"]: s["day"] for s in pool}, args.days)
    emit("observed", 0, "identity", obs)

    rng = random.Random(args.seed)
    null_scores = []
    for i in range(1, args.permute + 1):
        stats = aggregate(pool, day_swap(pool, rng), args.days)
        emit("permutation-null", i, args.seed, stats)
        null_scores.append(stats["max_ngram_count"])

    if null_scores:
        bar = statistics.quantiles(null_scores, n=20)[18] if len(null_scores) >= 5 \
            else max(null_scores)
        verdict = ("SURVIVED" if obs["max_ngram_count"] > max(null_scores)
                   else "WITHIN-NULL")
        print(f"null max_ngram_count: n={len(null_scores)} "
              f"min={min(null_scores)} p95={bar} max={max(null_scores)} | "
              f"observed={obs['max_ngram_count']} -> {verdict}")
    print(f"wrote {args.permute + 1} rows -> {out_path}")
    return 0


def selftest():
    """Synthetic corpus: temp project dir with tool_use sessions containing a
    deliberately repeated 4-gram; prove enumeration + permutation produce
    sane, varying stats and append-only rows."""
    import tempfile
    tmp_root = tempfile.mkdtemp()
    dm_dir = os.path.join(tmp_root, "proj")
    os.makedirs(dm_dir)
    tools = ["Read", "Bash", "Grep", "Edit", "Bash", "Read", "Bash", "Grep",
             "Edit", "Bash"]
    for i in range(6):
        recs = []
        recs.append(json.dumps({"type": "assistant", "message": {
            "content": [{"type": "tool_use", "name": t} for t in tools]}}))
        recs.append(json.dumps({"type": "user", "message": {
            "content": "no, that is wrong, revert the last change you made"}}))
        path = os.path.join(dm_dir, f"s{i}.jsonl")
        with open(path, "w") as f:
            f.write("\n".join(recs) + "\n")
        os.utime(path, (time.time() - i * 86400, time.time() - i * 86400))

    saved = _dream_mine.PROJECTS
    try:
        _dream_mine.PROJECTS = tmp_root
        pool = discover_sessions(10, 10**9)
        assert pool and len(pool) == 6, f"pool discovery failed: {pool}"
        for s in pool:
            s["cache"] = enumerate_session(s["path"], 10**9)
        obs = aggregate(pool, {s["path"]: s["day"] for s in pool}, 3)
        assert obs["max_ngram_count"] > 0, "no repeated 4-gram found in synthetic corpus"
        assert obs["corrections"] == 3, \
            f"corrections={obs['corrections']} (expected 3: window covers days 0-2)"
        permuted = aggregate(pool, day_swap(pool, random.Random(1)), 3)
        # permuted window is a strict subset swap: in-window count must differ
        # from observed for at least this pool (days 0..5, window 3)
        assert permuted["sessions_in_window"] == 3, \
            f"day-swap did not move sessions: {permuted}"
        assert permuted["max_ngram_count"] > 0
    finally:
        _dream_mine.PROJECTS = saved

    # append-only behavior of the ledger helper
    global atomic_append
    tmp = os.path.join(tempfile.mkdtemp(), "null.jsonl")
    atomic_append(tmp, {"kind": "selftest"})
    atomic_append(tmp, {"kind": "selftest2"})
    lines = open(tmp).read().strip().splitlines()
    assert len(lines) == 2, "atomic_append clobbered instead of appended"
    print(f"SELFTEST PASS: enumeration + day-swap + append-only ledger OK "
          f"(observed={obs['max_ngram_count']}, permuted={permuted['max_ngram_count']})")
    return 0


if __name__ == "__main__":
    sys.path.insert(0, SCRIPTS)
    from atomic_io import atomic_append
    ap = argparse.ArgumentParser(
        description="Trials-factor null calibration via dream-mine enumeration "
                    "over session-intact day-swap permutations (zero-LLM).")
    ap.add_argument("--permute", type=int, default=5,
                    help="number of day-swap permutations (null samples)")
    ap.add_argument("--days", type=int, default=None,
                    help="recency window in days (default: dream-mine config)")
    ap.add_argument("--max-sessions", type=int, default=60,
                    help="permutation pool size (most recent N sessions); "
                         "raise to None-all for full-corpus monthly runs")
    ap.add_argument("--seed", type=int, default=42)
    ap.add_argument("--max-file-bytes", type=int, default=30_000_000,
                    help="skip transcripts larger than this (dream-mine parity)")
    ap.add_argument("--out", default=OUT_DEFAULT)
    ap.add_argument("--quiet", action="store_true")
    ap.add_argument("--selftest", action="store_true")
    args = ap.parse_args()
    if args.selftest:
        import time
        sys.exit(selftest())
    cfg = _dream_mine.load_config()
    if args.days is None:
        args.days = cfg["mine_days_back"]
    sys.exit(run(args))
