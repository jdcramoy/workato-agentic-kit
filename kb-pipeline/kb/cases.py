"""cases.py — case-based reasoning: the harness's clinical experience.

Medical model: reasoning starts from "have I seen this presentation before?"
Every incident/bug/fix becomes a CASE: {presentation, diagnosis, treatment,
outcome, tags}. At decision time, retrieve similar cases FIRST — before
re-deriving from facts.

Ingest sources: the regression canon (fixed+tested entries), watchdog autopsy
bus posts, dream lessons. Manual filing always allowed.

  kb cases file --presentation "..." --diagnosis "..." --treatment "..." --outcome worked --tags "snowflake,recipe"
  kb cases similar "recipe fails at step 4 on null fields" -k 3
  kb cases stats
"""

from __future__ import annotations

import argparse
import datetime as dt
import hashlib
import json
import sqlite3
import struct
from pathlib import Path

from .indexer import get_db, get_model

CASES_DB = Path.home() / ".claude/workato-kb/index/cases.db"

SCHEMA = """
CREATE TABLE IF NOT EXISTS cases (
    case_id TEXT PRIMARY KEY,
    created TEXT NOT NULL,
    presentation TEXT NOT NULL,
    diagnosis TEXT NOT NULL,
    treatment TEXT NOT NULL,
    outcome TEXT NOT NULL,
    tags TEXT DEFAULT '',
    source TEXT DEFAULT 'manual',
    embedding BLOB
);
CREATE VIRTUAL TABLE IF NOT EXISTS cases_fts USING fts5(
    presentation, diagnosis, treatment, tags, content='cases', content_rowid='rowid'
);
CREATE VIRTUAL TABLE IF NOT EXISTS cases_vec USING vec0(
    case_rowid INTEGER PRIMARY KEY, embedding float[768]
);
"""


def _connect() -> sqlite3.Connection:
    CASES_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(CASES_DB)
    db.enable_load_extension(True)
    import sqlite_vec

    sqlite_vec.load(db)
    db.enable_load_extension(False)
    db.executescript(SCHEMA)
    return db


def _cid(presentation: str) -> str:
    return "case-" + hashlib.sha1(presentation.encode()).hexdigest()[:12]


def file_case(presentation: str, diagnosis: str, treatment: str, outcome: str = "worked",
              tags: str = "", source: str = "manual") -> dict:
    db = _connect()
    try:
        cid = _cid(presentation)
        emb = get_model("embed").encode([presentation], normalize_embeddings=True)[0].tolist()
        db.execute(
            "INSERT OR REPLACE INTO cases(case_id,created,presentation,diagnosis,treatment,outcome,tags,source) "
            "VALUES(?,?,?,?,?,?,?,?,)",
            (cid, dt.datetime.now().isoformat(timespec="seconds"), presentation, diagnosis, treatment, outcome, tags, source),
        )
        rowid = db.execute("SELECT rowid FROM cases WHERE case_id=?", (cid,)).fetchone()[0]
        db.execute("DELETE FROM cases_vec WHERE case_rowid=?", (rowid,))
        db.execute(
            "INSERT INTO cases_vec(case_rowid, embedding) VALUES(?,?)",
            (rowid, struct.pack(f"{len(emb)}f", *emb)),
        )
        db.execute(
            "INSERT OR REPLACE INTO cases_fts(rowid, presentation, diagnosis, treatment, tags) "
            "SELECT rowid, presentation, diagnosis, treatment, tags FROM cases WHERE case_id=?",
            (cid,),
        )
        db.commit()
        return {"case_id": cid, "filed": True}
    finally:
        db.close()


def similar(presentation: str, k: int = 3) -> list[dict]:
    db = _connect()
    try:
        emb = get_model("embed").encode([presentation], normalize_embeddings=True)[0].tolist()
        qbind = struct.pack(f"{len(emb)}f", *emb)
        vec = db.execute(
            "SELECT case_rowid, distance FROM cases_vec WHERE embedding MATCH ? AND k = ?",
            (qbind, k * 3),
        ).fetchall()
        # map rowids back to case_ids
        vec = [
            (db.execute("SELECT case_id FROM cases WHERE rowid=?", (rid,)).fetchone()[0], d)
            for rid, d in vec
        ]
        import re as _re

        tokens = _re.findall(r"\w{3,}", presentation.lower())
        fts_match = " OR ".join(f'"{t}"' for t in tokens)
        fts = db.execute(
            "SELECT rowid FROM cases_fts WHERE cases_fts MATCH ? LIMIT ?",
            (fts_match, k * 3),
        ).fetchall()
        fts = [
            (db.execute("SELECT case_id FROM cases WHERE rowid=?", (rid,)).fetchone()[0], 0)
            for rid, in fts
        ]
        # RRF fusion
        scores: dict[str, float] = {}
        for rank, (cid, _) in enumerate(vec):
            scores[cid] = scores.get(cid, 0) + 1 / (60 + rank + 1)
        for rank, (cid, _) in enumerate(fts):
            scores[cid] = scores.get(cid, 0) + 1 / (60 + rank + 1)
        top = sorted(scores.items(), key=lambda kv: -kv[1])[:k]
        out = []
        for cid, s in top:
            row = db.execute(
                "SELECT case_id, created, presentation, diagnosis, treatment, outcome, tags, source FROM cases WHERE case_id=?",
                (cid,),
            ).fetchone()
            out.append({
                "case_id": row[0], "created": row[1], "presentation": row[2],
                "diagnosis": row[3], "treatment": row[4], "outcome": row[5],
                "tags": row[6], "source": row[7], "sim": round(s, 4),
            })
        return out
    finally:
        db.close()


def stats() -> dict:
    db = _connect()
    try:
        n = db.execute("SELECT COUNT(*) FROM cases").fetchone()[0]
        by_source = db.execute("SELECT source, COUNT(*) FROM cases GROUP BY source").fetchall()
        by_outcome = db.execute("SELECT outcome, COUNT(*) FROM cases GROUP BY outcome").fetchall()
        return {"cases": n, "by_source": dict(by_source), "by_outcome": dict(by_outcome)}
    finally:
        db.close()


def ingest_from_canon() -> dict:
    """Bootstrap: every fixed canon entry becomes a case."""
    canon = Path.home() / ".claude/knowledge/regression-canon/canon.jsonl"
    if not canon.exists():
        return {"note": "no canon yet"}
    n = 0
    for line in canon.read_text().splitlines():
        try:
            c = json.loads(line)
        except json.JSONDecodeError:
            continue
        if c.get("status") in ("fixed", "tested"):
            file_case(
                presentation=c.get("signature") or c.get("symptom") or c.get("title", "unknown failure"),
                diagnosis=c.get("root_cause") or c.get("signature") or "",
                treatment=c.get("guard") or c.get("fix") or "see canon",
                outcome=c.get("status", "fixed"),
                tags=f"canon,{c.get('recipe_id', '')}",
                source="regression-canon",
            )
            n += 1
    return {"cases_from_canon": n}


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    fi = sub.add_parser("file")
    fi.add_argument("--presentation", required=True)
    fi.add_argument("--diagnosis", required=True)
    fi.add_argument("--treatment", required=True)
    fi.add_argument("--outcome", default="worked")
    fi.add_argument("--tags", default="")
    fi.add_argument("--source", default="manual")
    si = sub.add_parser("similar")
    si.add_argument("presentation")
    si.add_argument("-k", type=int, default=3)
    sub.add_parser("stats")
    sub.add_parser("ingest-canon")
    a = ap.parse_args()
    if a.cmd == "file":
        print(json.dumps(file_case(a.presentation, a.diagnosis, a.treatment, a.outcome, a.tags, a.source), indent=2))
    elif a.cmd == "similar":
        print(json.dumps(similar(a.presentation, a.k), indent=2))
    elif a.cmd == "stats":
        print(json.dumps(stats(), indent=2))
    elif a.cmd == "ingest-canon":
        print(json.dumps(ingest_from_canon(), indent=2))
