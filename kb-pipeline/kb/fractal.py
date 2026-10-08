"""fractal.py — self-similar memory: one schema, every scale, zoom queries.

The fractal unit (factlet): {id, level, title, text, parent, source, verdict, date}.
Levels:
  0 topic    — the INDEX line (what does this domain contain?)
  1 file     — a knowledge file or docs page (what does X say overall?)
  2 section  — a heading-level section or structured claim
  3 chunk    — the fine grain (the exact passage / evidence)
Same schema at every level; consolidation (gardener) and dreaming (lateral
engine) operate on the same units; retrieval zooms instead of loading.

Built ADDITIVELY from the existing stores — nothing is migrated or moved;
this is a lens over the same memory, not a replacement.

  kb fractal build            # construct factlets from all stores
  kb fractal zoom "vua"       # coarse answer + drill-down pointers
  kb fractal show <id>        # one factlet + its children/parent
"""

from __future__ import annotations

import argparse
import hashlib
import json
import re
import sqlite3
from pathlib import Path

from .common import DATA_ROOT
from .indexer import DB_PATH, get_db

FACTLET_DB = DATA_ROOT / "index" / "fractal.db"
KT = Path.home() / ".claude/knowledge"

LEVELS = {0: "topic", 1: "file", 2: "section", 3: "chunk"}

SCHEMA = """
CREATE TABLE IF NOT EXISTS factlets (
    id TEXT PRIMARY KEY,
    level INTEGER NOT NULL,
    title TEXT NOT NULL,
    text TEXT NOT NULL,
    parent TEXT,
    source TEXT,
    verdict TEXT,
    date TEXT,
    children TEXT DEFAULT '[]'
);
CREATE INDEX IF NOT EXISTS idx_factlets_level ON factlets(level);
CREATE INDEX IF NOT EXISTS idx_factlets_parent ON factlets(parent);
CREATE VIRTUAL TABLE IF NOT EXISTS factlets_fts USING fts5(
    title, text, content='factlets', content_rowid='rowid'
);
"""


def _fid(*parts) -> str:
    return hashlib.sha1("|".join(str(p) for p in parts).encode()).hexdigest()[:12]


def _connect() -> sqlite3.Connection:
    FACTLET_DB.parent.mkdir(parents=True, exist_ok=True)
    db = sqlite3.connect(FACTLET_DB)
    db.executescript(SCHEMA)
    return db


def _insert(db, level, title, text, parent, source, verdict=None, date=None):
    fid = _fid(level, title, source)
    db.execute(
        "INSERT OR REPLACE INTO factlets(id,level,title,text,parent,source,verdict,date,children) "
        "VALUES(?,?,?,?,?,?,?,?,COALESCE((SELECT children FROM factlets WHERE id=?),'[]'))",
        (fid, level, title[:200], text[:8000], parent, source, verdict, date, fid),
    )
    if parent:
        db.execute(
            "UPDATE factlets SET children = json_insert(children, '$[#]', ?) WHERE id=?",
            (fid, parent),
        )
    db.execute("INSERT OR REPLACE INTO factlets_fts(rowid, title, text) SELECT rowid, title, text FROM factlets WHERE id=?", (fid,))
    return fid


def build() -> dict:
    db = _connect()
    stats = {"level0": 0, "level1": 0, "level2": 0, "level3": 0}
    kb = get_db()

    # level 0/1 from the knowledge tree INDEX (topic -> file)
    index_lines = [
        ln
        for ln in (KT / "INDEX.md").read_text().splitlines()
        if ln.strip().startswith("- [")
    ]
    root = _fid(0, "INDEX-root", "knowledge-tree")
    db.execute(
        "INSERT OR REPLACE INTO factlets(id,level,title,text,parent,source,verdict,date,children) VALUES(?,?,?,?,?,?,?,?,?)",
        (root, 0, "The knowledge tree", "The harness's curated memory: every line routes to one file.", None, "INDEX.md", None, None, "[]"),
    )
    stats["level0"] += 1
    for ln in index_lines:
        m = re.match(r"- \[(.+?)\]\((.+?)\)", ln)
        if not m:
            continue
        title, rel = m.group(1), m.group(2)
        path = None
        for cand in [KT / rel, KT / "domains" / rel, KT / "projects" / rel, KT / rel.lstrip("./")]:
            if cand.exists():
                path = cand
                break
        if not path:
            continue
        fid = _insert(db, 1, title, path.read_text()[:4000], root, rel)
        stats["level1"] += 1

        # level 2: sections within the file
        text = path.read_text()
        for sec in re.split(r"\n(?=## )", text):
            if not sec.strip() or not sec.startswith("## "):
                continue
            sec_title = sec.splitlines()[0][3:].strip()[:80]
            _insert(db, 2, f"{title} :: {sec_title}", sec[:3000], fid, rel)
            stats["level2"] += 1

    # level 2 from the claims ledger (structured facts attach to their domain file)
    claims_p = KT / "claims" / "claims.jsonl"
    if claims_p.exists():
        for line in claims_p.read_text().splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            _insert(
                db,
                2,
                f"claim: {c.get('claim', '')[:60]}",
                json.dumps(c, indent=1),
                _fid(1, c.get("domain", "unfiled"), c.get("domain", "")),
                c.get("source", "claims.jsonl"),
                verdict=c.get("verdict") or c.get("status"),
                date=c.get("last_verified") or c.get("created"),
            )
            stats["level2"] += 1

    # level 3 from KB chunks (fine grain; parent = the docs page file factlet)
    for (url, title, context, text) in kb.execute(
        "SELECT d.url, d.title, c.context, c.text FROM chunks c JOIN docs d ON d.doc_id = c.doc_id LIMIT 200000"
    ):
        _insert(db, 3, title[:150], f"{context}\n\n{text[:2000]}", _fid(1, title, url.split("docs.workato.com/")[-1].removesuffix(".md")), url)
        stats["level3"] += 1
    kb.close()

    db.commit()
    db.close()
    stats["total"] = sum(stats.values())
    return stats


def zoom(topic: str, level: int | None = None, k: int = 6) -> dict:
    """Coarse-first retrieval: best factlets at the coarsest level that answers,
    with drill-down pointers. Read less; zoom only when needed."""
    db = _connect()
    try:
        import re as _re

        tokens = _re.findall(r"\w{2,}", topic.lower())
        match = " OR ".join(f'"{t}"' for t in tokens) or '""'
        out = {"topic": topic, "levels": {}}
        for lvl in sorted(LEVELS):  # coarse first
            if level is not None and lvl != level:
                continue
            rows = db.execute(
                "SELECT f.id, f.level, f.title, substr(f.text, 1, 300), f.parent, f.source "
                "FROM factlets_fts ft JOIN factlets f ON f.rowid = ft.rowid "
                "WHERE factlets_fts MATCH ? AND f.level = ? LIMIT ?",
                (match, lvl, k),
            ).fetchall()
            if rows:
                out["levels"][LEVELS[lvl]] = [
                    {
                        "id": r[0],
                        "title": r[2],
                        "snippet": r[3],
                        "parent": r[4],
                        "source": r[5],
                        "drill": f"kb fractal show {r[0]}",
                    }
                    for r in rows
                ]
        out["verdict"] = (
            f"{sum(len(v) for v in out['levels'].values())} factlets; read the coarsest level that answers, drill only on decision"
        )
        return out
    finally:
        db.close()


def show(fid: str) -> dict:
    db = _connect()
    try:
        row = db.execute(
            "SELECT id, level, title, text, parent, source, verdict, date, children FROM factlets WHERE id=? OR rowid=?",
            (fid, int(fid) if fid.isdigit() else -1),
        ).fetchone()
        if not row:
            return {"error": f"no factlet {fid}"}
        children = json.loads(row[8] or "[]")
        kids = db.execute(
            f"SELECT id, level, title FROM factlets WHERE id IN ({','.join('?' * len(children)) or '?'})",
            children or ["__none__"],
        ).fetchall()
        return {
            "id": row[0],
            "level": LEVELS.get(row[1], row[1]),
            "title": row[2],
            "text": row[3][:1500],
            "parent": row[4],
            "source": row[5],
            "verdict": row[6],
            "date": row[7],
            "children": [{"id": k[0], "level": LEVELS.get(k[1], k[1]), "title": k[2]} for k in kids],
        }
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    z = sub.add_parser("zoom")
    z.add_argument("topic")
    z.add_argument("--level", type=int, default=None)
    z.add_argument("-k", type=int, default=6)
    s = sub.add_parser("show")
    s.add_argument("id")
    a = ap.parse_args()
    if a.cmd == "build":
        print(json.dumps(build(), indent=2))
    elif a.cmd == "zoom":
        print(json.dumps(zoom(a.topic, a.level, a.k), indent=2))
    elif a.cmd == "show":
        print(json.dumps(show(a.id), indent=2))
