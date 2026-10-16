#!/usr/bin/env python3
"""kb-audit.py — standing integrity monitor for the workato-kb corpus/pipeline.

Born 2026-10-10 from the audit that found the 2026-10-08 bug class RECURRING:
auto-memory files existed on disk but were invisible to KB retrieval (the
harness source never ingested them). This monitor makes that failure class a
checked fact instead of a hope. Zero LLM: deterministic filesystem + sqlite +
one live `kb` CLI probe (daemon-warm, ~2s).

Checks (each -> PASS/WARN/FAIL + counts):
  1. memory-files      every ~/.claude/projects/*/memory/*.md is in the
                       harness manifest (the past bug, exactly)
  2. knowledge-files   knowledge/{domains,projects,claims}/**/*.md in manifest
  3. skills            every skills/*/SKILL.md in manifest
  4. unfiled-recent    harness-tree .md files modified <48h ago but not yet in
                       the manifest (catches new memories/docs before they go
                       stale-invisible)
  5. index-parity      FTS rows == chunks rows; no orphaned chunk embeddings;
                       manifest docs vs docs-table count drift < 2%
  6. entropy           >=95% of chunks have entropy > 0
  7. coarse-vecs       >=95% of docs have a coarse-layer embedding
  8. fractal           `kb fractal coverage` verdict has no new gaps vs the
                       2026-10-10 baseline (4 known knowledge-tree emitter gaps)
  9. live-probe        for the 2 most recently modified memory files: extract a
                       distinctive phrase, run `kb "<phrase>"`, and require the
                       file (its harness:// url) in the top 10 hits. The true
                       end-to-end check — indexing can be 100% and retrieval
                       still broken.

Output: human summary to stdout; JSON verdict to
  ~/.claude/workato-kb/audit/kb-audit-<date>.json (append-day, one per run)
Findings (any FAIL or >0 unfiled) post a typed finding to the gossip bus via
bus_post.py. Exit code is ALWAYS 0 (fleet validation keys on output, not rc);
the report is the alarm.

Usage: kb-audit.py            # full audit
       kb-audit.py --quiet    # print one verdict line only
"""

from __future__ import annotations

import datetime as dt
import json
import re
import sqlite3
import subprocess
import sys
from pathlib import Path

HOME = Path.home()
DATA_ROOT = HOME / ".claude/workato-kb"
DB_PATH = DATA_ROOT / "index" / "kb.db"
KNOWLEDGE = HOME / ".claude/knowledge"
PROJECTS = HOME / ".claude/projects"
SKILLS = HOME / ".claude/skills"
AUDIT_DIR = DATA_ROOT / "audit"
BUS_POST = KNOWLEDGE / "scripts/bus_post.py"
AGENT = "kb-audit"
KNOWN_GAPS = {  # pre-2026-10-10 knowledge-tree emitter gaps (gardener's turf)
    "josh-voice-corpus.md",
    "workato-dev-kb.md",
    "bsys-25528-vibe-app-registry.md",
    "bsys-25527-risk-tier-governance.md",
}


def load_manifest(name: str) -> dict[str, dict]:
    p = DATA_ROOT / "manifest" / f"{name}.jsonl"
    if not p.exists():
        return {}
    out = {}
    for line in p.read_text().splitlines():
        line = line.strip()
        if line:
            rec = json.loads(line)
            out[rec["url"]] = rec
    return out


def check_files(label: str, expected: list[Path], origins: set[str]) -> tuple[str, dict]:
    missing = [p for p in expected if str(p) not in origins]
    # age-aware: a file written an hour ago is not ingested until the nightly
    # harness sync (21:37) — that is "not yet", not "never". FAIL only when a
    # file stays unindexed past the 48h ingestion window (the original bug
    # class: stale-invisible forever); fresh-missing is a WARN.
    cutoff = dt.datetime.now().timestamp() - 48 * 3600
    stale_missing = [p for p in missing if p.stat().st_mtime <= cutoff]
    detail = {"expected": len(expected), "missing": len(missing), "stale_missing": len(stale_missing)}
    if missing:
        detail["missing_paths"] = [str(m) for m in missing[:10]]
    verdict = "PASS" if not missing else ("FAIL" if stale_missing else "WARN")
    return verdict, detail


def newest_memory_files(n: int) -> list[Path]:
    files = sorted(PROJECTS.glob("*/memory/*.md"), key=lambda p: p.stat().st_mtime, reverse=True)
    return files[:n]


def main() -> None:
    quiet = "--quiet" in sys.argv
    checks: dict[str, dict] = {}
    harness = load_manifest("harness")
    # manifest records carry no origin field — the corpus frontmatter does
    origins = set()
    corpus_harness = DATA_ROOT / "corpus" / "harness"
    for f in corpus_harness.rglob("*.md"):
        head = f.read_text(errors="ignore")[:400]
        m = re.search(r'origin: "(.+)"', head)
        if m:
            origins.add(m.group(1))

    # 1-3. file coverage vs harness manifest
    mem_files = sorted(PROJECTS.glob("*/memory/*.md"))
    v, d = check_files("memory", mem_files, origins)
    checks["memory-files"] = {"verdict": v, **d}
    kt_files = [p for sub in ("domains", "projects", "claims") for p in (KNOWLEDGE / sub).rglob("*.md") if "/people/" not in str(p)]
    v, d = check_files("knowledge", kt_files, origins)
    checks["knowledge-files"] = {"verdict": v, **d}
    skill_files = sorted(SKILLS.glob("*/SKILL.md"))
    v, d = check_files("skills", skill_files, origins)
    checks["skills"] = {"verdict": v, **d}

    # 4. unfiled-recent (48h window) — any harness-tree .md, not just known dirs
    cutoff = dt.datetime.now().timestamp() - 48 * 3600
    unfiled = [
        str(p)
        for p in list(mem_files) + kt_files + skill_files
        if p.stat().st_mtime > cutoff and str(p) not in origins
    ]
    checks["unfiled-recent"] = {"verdict": "PASS" if not unfiled else "WARN", "count": len(unfiled), "paths": unfiled[:10]}

    # 5-7. index internals
    if DB_PATH.exists():
        db = sqlite3.connect(f"file:{DB_PATH}?mode=ro", uri=True)
        n_docs = db.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        n_chunks = db.execute("SELECT COUNT(*) FROM chunks").fetchone()[0]
        n_fts = db.execute("SELECT COUNT(*) FROM chunks_fts").fetchone()[0]
        n_vec = db.execute("SELECT COUNT(*) FROM chunks_vec_rowids").fetchone()[0]
        # vec0 rowids-table: rowid IS the chunk_id (chunk_id col is a vec0-
        # internal partition id — never join on it)
        orphans = max(0, n_vec - db.execute("SELECT COUNT(*) FROM chunks_vec_rowids WHERE rowid IN (SELECT chunk_id FROM chunks)").fetchone()[0])
        # chunks with NO vector at all — the killed-mid-embed bug class
        # (2026-10-14: 4,535 slack chunks stranded; the old orphan-only check
        # scored PASS while dense retrieval silently missed 29% of a source)
        missing_vec = db.execute("SELECT COUNT(*) FROM chunks WHERE chunk_id NOT IN (SELECT rowid FROM chunks_vec_rowids)").fetchone()[0]
        n_entropy = db.execute("SELECT COUNT(*) FROM chunks WHERE entropy > 0").fetchone()[0]
        n_coarse = db.execute("SELECT COUNT(*) FROM docs_vec_coarse_rowids").fetchone()[0]
        # coarse layer covers contextualized docs only (funnel.build selects
        # llm_context != ''); measure against that denominator, not all docs
        n_coarse_expected = db.execute("SELECT COUNT(*) FROM docs WHERE llm_context != ''").fetchone()[0]
        # manifest total discovered dynamically (glob) — the hardcoded source
        # list predated the scout expansion and read drift 133% forever (same
        # hardcoded-list bug class the indexer _doc_iter fix killed). Rows
        # marked thin are recorded-but-skipped by design (rss feed entries
        # under the length floor) — not expected to be indexed.
        manifest_total = sum(
            1 for p in (DATA_ROOT / "manifest").glob("*.jsonl")
            for rec in load_manifest(p.stem).values()
            if str(rec.get("thin", "")).lower() != "true"
        )
        drift = abs(manifest_total - n_docs) / max(1, manifest_total)
        checks["index-parity"] = {
            "verdict": "PASS" if (n_fts == n_chunks and orphans == 0 and missing_vec == 0 and drift < 0.02) else "FAIL",
            "docs": n_docs, "chunks": n_chunks, "fts": n_fts,
            "vec_rows": n_vec, "orphan_vecs": orphans, "missing_vec": missing_vec,
            "manifest_total": manifest_total, "drift_pct": round(drift * 100, 2),
        }
        checks["entropy"] = {"verdict": "PASS" if n_entropy / max(1, n_chunks) >= 0.95 else "WARN",
                             "scored": n_entropy, "total": n_chunks}
        checks["coarse-vecs"] = {"verdict": "PASS" if n_coarse / max(1, n_coarse_expected) >= 0.95 else "WARN",
                                 "covered": n_coarse, "contextualized_docs": n_coarse_expected}
        db.close()
    else:
        checks["index-parity"] = {"verdict": "FAIL", "error": "kb.db missing"}

    # 8. fractal verdict (subprocess; tolerate CLI absence)
    try:
        r = subprocess.run(["kb", "fractal", "coverage"], capture_output=True, text=True, timeout=600)
        s = r.stdout
        verdict = re.search(r'"verdict": "([^"]+)"', s)
        gaps = re.findall(r'knowledge/(?:domains|projects)/([^\"]+\.md)', s)
        new_gaps = [g for g in gaps if g not in KNOWN_GAPS]
        checks["fractal"] = {"verdict": "PASS" if not new_gaps else "WARN",
                             "verdict_line": verdict.group(1) if verdict else "?",
                             "new_gaps": new_gaps[:10]}
    except Exception as e:  # noqa: BLE001
        checks["fractal"] = {"verdict": "WARN", "error": str(e)}

    # 9. live-probe memory retrieval end-to-end. Age-aware: a file younger
    # than the 48h ingestion window cannot be indexed yet — probing it FAILs
    # on "not yet" every time a session writes a memory mid-day. Probe the
    # 2 freshest files PAST the window; fresh-only state = PASS (pending).
    probes = []
    probeable = [p for p in newest_memory_files(8) if p.stat().st_mtime <= dt.datetime.now().timestamp() - 48 * 3600][:2]
    for p in probeable:
        words = [w for w in re.findall(r"[a-z]{5,}", p.read_text(errors="ignore").lower()) if w not in
                 {"workato", "recipe", "recipe", "josh", "built", "verified", "memory", "metadata", "description", "because", "should", "there", "which", "their", "about", "after"}]
        phrase = " ".join(words[:10])
        try:
            r = subprocess.run(["kb", phrase], capture_output=True, text=True, timeout=180)
            hit_urls = re.findall(r"url: (harness://memory/\S+)", r.stdout)
            # match on filename stem — url slug may reword
            stem = p.stem
            found = any(stem in u for u in hit_urls)
            probes.append({"file": str(p), "phrase": phrase, "found": found, "top_hit": hit_urls[0] if hit_urls else None})
        except Exception as e:  # noqa: BLE001
            probes.append({"file": str(p), "phrase": phrase, "found": None, "error": str(e)})
    checks["live-probe"] = {
        "verdict": "PASS" if all(pr.get("found") for pr in probes) else "FAIL",
        "note": "no memory files past the 48h ingestion window yet" if not probes else "",
        "probes": probes,
    }

    verdict_counts = {}
    for c in checks.values():
        verdict_counts[c["verdict"]] = verdict_counts.get(c["verdict"], 0) + 1
    overall = "FAIL" if verdict_counts.get("FAIL") else ("WARN" if verdict_counts.get("WARN") else "PASS")

    report = {
        "ts": dt.datetime.now().isoformat(timespec="seconds"),
        "overall": overall,
        "checks": checks,
    }
    AUDIT_DIR.mkdir(parents=True, exist_ok=True)
    (AUDIT_DIR / f"kb-audit-{dt.date.today()}.jsonl").open("a").write(json.dumps(report) + "\n")

    if quiet:
        print(f"kb-audit: {overall} ({verdict_counts})")
        return
    print(f"=== kb-audit {report['ts']}: {overall} ===")
    for name, c in checks.items():
        line = f"  [{c['verdict']:4}] {name}"
        extra = {k: v for k, v in c.items() if k not in ("verdict", "probes", "missing_paths", "paths")}
        print(f"{line}  {extra}")
        for pr in c.get("probes", []):
            print(f"           probe {Path(pr['file']).name}: found={pr.get('found')}")
    if overall != "PASS":
        try:
            subprocess.run(
                ["python3", str(BUS_POST), "post", "--agent", AGENT, "--type", "finding",
                 "--subject", "kb-audit-findings", "--claim", f"kb-audit {overall}: {verdict_counts}",
                 "--evidence", json.dumps({k: c for k, c in checks.items() if c["verdict"] != "PASS"}),
                 "--confidence", "0.9"],
                capture_output=True, text=True, timeout=60,
            )
        except Exception:  # noqa: BLE001 — bus is best-effort
            pass


if __name__ == "__main__":
    main()
