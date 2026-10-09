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
from collections import defaultdict
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
CREATE TABLE IF NOT EXISTS build_meta (
    source_key TEXT PRIMARY KEY,
    sha TEXT NOT NULL,
    built_at TEXT DEFAULT (datetime('now'))
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


def _insert(db, level, title, text, parent, source, verdict=None, date=None, fid=None):
    fid = fid or _fid(level, parent, title, source)
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


def _sha(path: Path) -> str:
    import hashlib

    return hashlib.sha1(path.read_bytes()).hexdigest()


def _source_changed(db, key: str, sha: str) -> bool:
    row = db.execute("SELECT sha FROM build_meta WHERE source_key=?", (key,)).fetchone()
    return row is None or row[0] != sha


def _mark(db, key: str, sha: str) -> None:
    db.execute(
        "INSERT OR REPLACE INTO build_meta(source_key, sha, built_at) VALUES(?,?,datetime('now'))",
        (key, sha),
    )


def build(full: bool = False) -> dict:
    """Incremental by default: each source rebuilds only when its content changed.
    Sources: knowledge tree, claims, agent SOPs, skills, CLAUDE.md tiers, the
    auto-memory dir, dream reports, calibration cards, KB chunk layer."""
    db = _connect()
    stats = {"level0": 0, "level1": 0, "level2": 0, "level3": 0, "skipped": 0}
    kb = get_db()

    def insert(level, title, text, parent, source, verdict=None, date=None, fid=None):
        return _insert(db, level, title, text, parent, source, verdict, date, fid=fid)

    # --- knowledge tree (INDEX -> files -> sections) ---
    index_lines = [
        ln
        for ln in (KT / "INDEX.md").read_text().splitlines()
        if ln.strip().startswith("- [")
    ]
    if full or _source_changed(db, "kt-index", _sha(KT / "INDEX.md")):
        root = _fid(0, "INDEX-root", "knowledge-tree")
        db.execute(
            "INSERT OR REPLACE INTO factlets(id,level,title,text,parent,source,verdict,date,children) VALUES(?,?,?,?,?,?,?,?,?)",
            (root, 0, "The knowledge tree", "The harness's curated memory: every line routes to one file.", None, "INDEX.md", None, None, "[]"),
        )
        _mark(db, "kt-index", _sha(KT / "INDEX.md"))
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
        key = f"kt:{rel}"
        if not full and not _source_changed(db, key, _sha(path)):
            stats["skipped"] += 1
            continue
        fid = insert(1, title, path.read_text()[:9000], root, rel)
        stats["level1"] += 1
        text = path.read_text()
        for sec in re.split(r"\n(?=## )", text):
            if not sec.strip() or not sec.startswith("## "):
                continue
            sec_title = sec.splitlines()[0][3:].strip()[:80]
            _insert(db, 2, f"{title} :: {sec_title}", sec[:3000], fid, rel)
            stats["level2"] += 1
        _mark(db, key, _sha(path))

    # --- claims ledger ---
    claims_p = KT / "claims" / "claims.jsonl"
    if claims_p.exists() and (full or _source_changed(db, "claims", _sha(claims_p))):
        for line in claims_p.read_text().splitlines():
            if not line.strip():
                continue
            c = json.loads(line)
            insert(
                2,
                f"claim: {c.get('claim', '')[:60]}",
                json.dumps(c, indent=1),
                _fid(1, c.get("domain", "unfiled"), c.get("domain", "")),
                c.get("source", "claims.jsonl"),
                verdict=c.get("verdict") or c.get("status"),
                date=c.get("last_verified") or c.get("created"),
            )
            stats["level2"] += 1
        _mark(db, "claims", _sha(claims_p))

    # --- agent SOPs (level 1 + level 2 sections) ---
    agents_changed = 0
    for p_ag in (Path.home() / ".claude/agents").glob("*.md"):
        key = f"agent:{p_ag.name}"
        if not full and not _source_changed(db, key, _sha(p_ag)):
            stats["skipped"] += 1
            continue
        text = p_ag.read_text()
        head = re.sub(r"^---\n.*?---\n", "", text, flags=re.S).strip()
        title = head.splitlines()[0].lstrip("# ").strip() if head.startswith("#") else p_ag.stem
        fid = insert(1, f"agent: {title}", head[:9000], root, f"agents/{p_ag.name}")
        stats["level1"] += 1
        for sec in re.split(r"\n(?=## )", head):
            if not sec.strip() or not sec.startswith("## "):
                continue
            insert(2, f"agent {p_ag.stem} :: {sec.splitlines()[0][3:].strip()[:60]}", sec[:3000], fid, f"agents/{p_ag.name}")
            stats["level2"] += 1
        _mark(db, key, _sha(p_ag))
        agents_changed += 1

    # --- skills (level 1: one factlet per skill, description carries the routing) ---
    for p_sk in (Path.home() / ".claude/skills").glob("*/SKILL.md"):
        key = f"skill:{p_sk.parent.name}"
        if not full and not _source_changed(db, key, _sha(p_sk)):
            stats["skipped"] += 1
            continue
        text = p_sk.read_text()
        desc = ""
        m = re.search(r"description:\s*>?-?\s*\n?((?:\s+.+\n)+)", text)
        if not m:
            m = re.search(r"description:\s*(.+)", text)
        if m:
            desc = " ".join(m.group(1).split())[:500]
        insert(1, f"skill: {p_sk.parent.name}", f"{desc}\n\n{text[:2500]}", root, f"skills/{p_sk.parent.name}")
        stats["level1"] += 1
        _mark(db, key, _sha(p_sk))

    # --- CLAUDE.md tiers + auto-memory (level 1) ---
    for label, cpath in [
        ("global-CLAUDE.md", Path.home() / ".claude/CLAUDE.md"),
        ("project-CLAUDE.md", Path.home() / "Documents/CLAUDE.md"),
        ("workbench-CLAUDE.md", Path.home() / "Documents/workbench/CLAUDE.md"),
        ("MEMORY.md", Path.home() / ".claude/projects/-Users-joshcramoy-Documents-workbench/memory/MEMORY.md"),
    ]:
        if not cpath.exists():
            continue
        key = f"claude:{label}"
        if not full and not _source_changed(db, key, _sha(cpath)):
            stats["skipped"] += 1
            continue
        insert(1, label, cpath.read_text()[:5000], root, str(cpath))
        stats["level1"] += 1
        _mark(db, key, _sha(cpath))
    mem_dir = Path.home() / ".claude/projects/-Users-joshcramoy-Documents-workbench/memory"
    for p_m in mem_dir.glob("*.md"):
        if p_m.name == "MEMORY.md":
            continue
        key = f"memory:{p_m.name}"
        if not full and not _source_changed(db, key, _sha(p_m)):
            stats["skipped"] += 1
            continue
        insert(1, f"memory: {p_m.stem}", p_m.read_text()[:4000], root, str(p_m))
        stats["level1"] += 1
        _mark(db, key, _sha(p_m))

    # --- dream reports + calibration cards (level 1, dated) ---
    for p_d in sorted((KT / "dreams").glob("2*.md"))[-30:]:
        key = f"dream:{p_d.name}"
        if not full and not _source_changed(db, key, _sha(p_d)):
            stats["skipped"] += 1
            continue
        insert(1, f"dream: {p_d.stem}", p_d.read_text()[:6000], root, str(p_d), date=p_d.stem[:10])
        stats["level1"] += 1
        _mark(db, key, _sha(p_d))
    cal = KT / "dreams/calibration"
    if cal.exists():
        for p_c in sorted(cal.glob("*.md"))[-8:]:
            key = f"calibration:{p_c.name}"
            if not full and not _source_changed(db, key, _sha(p_c)):
                stats["skipped"] += 1
                continue
            insert(1, f"calibration: {p_c.stem}", p_c.read_text()[:3000], root, str(p_c))
            stats["level1"] += 1
            _mark(db, key, _sha(p_c))

    # --- ALL other project memory dirs (every ~/.claude/projects/*/memory) ---
    for mem_d in Path.home().joinpath(".claude/projects").glob("*/memory"):
        if mem_d == mem_dir:
            continue  # workbench memory already covered above
        for p_m in mem_d.glob("*.md"):
            key = f"memproj:{mem_d.parent.name}:{p_m.name}"
            if not full and not _source_changed(db, key, _sha(p_m)):
                stats["skipped"] += 1
                continue
            proj = mem_d.parent.name.replace("-Users-joshcramoy-", "~/").replace("-", "/")[:60]
            insert(1, f"memory[{proj}]: {p_m.stem}", p_m.read_text()[:4000], root, str(p_m))
            stats["level1"] += 1
            _mark(db, key, _sha(p_m))

    # --- repo instruction files (CLAUDE.md / AGENTS.md in every repo) ---
    for pat in ("*/CLAUDE.md", "*/AGENTS.md", "*/docs/AGENTS.md"):
        for cpath in Path.home().joinpath("Documents").glob(pat):
            key = f"repo-instr:{cpath}"
            if not full and not _source_changed(db, key, _sha(cpath)):
                stats["skipped"] += 1
                continue
            insert(1, f"instructions: {cpath.parent.name}", cpath.read_text()[:6000], root, str(cpath))
            stats["level1"] += 1
            _mark(db, key, _sha(cpath))

    # --- fleet job prompts (procedural memory: what each scheduled job does) ---
    fleet_jobs = Path.home() / ".local/bin/fleet/jobs"
    if fleet_jobs.exists():
        for p_j in list(fleet_jobs.glob("*.prompt")) + list(fleet_jobs.glob("*.script")):
            key = f"fleet:{p_j.name}"
            if not full and not _source_changed(db, key, _sha(p_j)):
                stats["skipped"] += 1
                continue
            insert(2, f"fleet job: {p_j.stem}", p_j.read_text()[:3000], root, str(p_j))
            stats["level2"] += 1
            _mark(db, key, _sha(p_j))

    # --- loose docs in ~/Documents/Claude (linked, not moved; INDEX points here) ---
    claude_docs = Path.home() / "Documents/Claude"
    if claude_docs.exists():
        for p_d in claude_docs.glob("*.md"):
            if p_d.name == "CLAUDE.md":
                continue
            key = f"loose:{p_d.name}"
            if not full and not _source_changed(db, key, _sha(p_d)):
                stats["skipped"] += 1
                continue
            insert(1, f"doc: {p_d.stem}", p_d.read_text()[:6000], root, str(p_d))
            stats["level1"] += 1
            _mark(db, key, _sha(p_d))

    # --- KB chunk layer (level 3) — rebuild only when the KB index moved ---
    kb_db = DB_PATH
    kb_newer = not _source_changed(db, "kb-chunks", f"{kb_db.stat().st_mtime_ns}") if kb_db.exists() else False
    if full or kb_newer:
        # level-1 factlets for every docs page FIRST (chunks parent to these);
        # the llm_context (or title) is the page's coarse summary
        docs_rows = kb.execute(
            "SELECT DISTINCT d.url, d.title, IFNULL(d.llm_context, ''), d.source FROM docs d LIMIT 200000"
        ).fetchall()
        page_fid = {}
        for (url, title, llm_ctx, source) in docs_rows:
            pf = _fid(1, title, url.split("docs.workato.com/")[-1].removesuffix(".md"))
            page_fid[url] = pf
            coarse = llm_ctx or f"{title} ({source} page)"
            insert(1, f"{source}: {title[:120]}", f"{coarse}\n\n{url}", root, url, fid=pf)
            stats["level1"] += 1
        # fid includes chunk_id — chunks of one page must not overwrite each other
        for (chunk_id, url, title, context, text) in kb.execute(
            "SELECT c.chunk_id, d.url, d.title, c.context, c.text FROM chunks c JOIN docs d ON d.doc_id = c.doc_id LIMIT 200000"
        ):
            insert(
                3,
                title[:150],
                f"{context}\n\n{text[:2000]}",
                page_fid.get(url) or _fid(1, title, url.split("docs.workato.com/")[-1].removesuffix(".md")),
                url,
                fid=_fid(3, chunk_id),
            )
            stats["level3"] += 1
        _mark(db, "kb-chunks", f"{kb_db.stat().st_mtime_ns}")

    db.commit()
    db.close()
    stats["total"] = sum(v for k2, v in stats.items() if k2 != "skipped")
    return stats


def _freshen() -> None:
    """Rebuild incrementally if any tracked source changed (cheap shas)."""
    import subprocess as _sp
    import sys as _sys

    r = _sp.run(
        [_sys.executable, str(Path(__file__).resolve()), "build"],
        capture_output=True,
        text=True,
        timeout=600,
    )
    if "skipped" not in r.stdout:
        import sys as _s

        print("[fractal: refreshed]", file=_s.stderr, flush=True)


def zoom(topic: str, level: int | None = None, k: int = 6, fresh: bool = True) -> dict:
    """Coarse-first retrieval: best factlets at the coarsest level that answers,
    with drill-down pointers. Read less; zoom only when needed."""
    if fresh:
        _freshen()
    db = _connect()
    try:
        import re as _re

        tokens = _re.findall(r"\w{2,}", topic.lower())
        match = " OR ".join(f'"{t}"' for t in tokens) or '""'
        # one query across ALL levels: bm25 scores are comparable within a single
        # FTS index, so the ranking is global — chunk noise cannot bury the file
        # that actually answers (the first-non-empty-level design had exactly
        # that failure; the eval caught it)
        where = "WHERE factlets_fts MATCH ? AND f.level = ?" if level is not None else "WHERE factlets_fts MATCH ?"
        params = [match, level, k] if level is not None else [match, k]
        rows = db.execute(
            f"SELECT f.id, f.level, f.title, substr(f.text, 1, 300), f.parent, f.source "
            f"FROM factlets_fts ft JOIN factlets f ON f.rowid = ft.rowid "
            f"{where} ORDER BY bm25(factlets_fts, 8.0, 1.0) LIMIT ?",
            params,
        ).fetchall()
        out = {"topic": topic, "levels": {}}
        for r in rows:
            out["levels"].setdefault(LEVELS[r[1]], []).append(
                {
                    "id": r[0],
                    "title": r[2],
                    "snippet": r[3],
                    "parent": r[4],
                    "source": r[5],
                    "drill": f"kb fractal show {r[0]}",
                }
            )
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


def coverage() -> dict:
    """The airtight check: walk every memory surface, verify each prose file
    has at least one factlet. Gaps listed by surface."""
    db = _connect()
    try:
        sources = {r[0] for r in db.execute("SELECT DISTINCT source FROM factlets")}
        gaps: dict[str, list] = defaultdict(list)
        checked = 0

        def check(path: Path, surface: str):
            nonlocal checked
            checked += 1
            sp = str(path)
            # factlet sources are often repo-relative (agents/x.md, domains/y.md)
            # and skills drop the SKILL.md tail (skills/<name>); match on suffix
            # or directory so format differences can't fake a gap
            hit = any(
                item in sources
                or any(s == item or item.endswith("/" + s) or s.endswith("/" + item) for s in sources)
                for item in {sp, sp.removesuffix("/SKILL.md"), path.name}
            )
            if not hit:
                gaps[surface].append(sp)

        # knowledge tree
        for sub in ("domains", "projects"):
            for p_f in (KT / sub).glob("*.md"):
                check(p_f, f"knowledge/{sub}")
        # claims
        if (KT / "claims/claims.jsonl").exists():
            check(KT / "claims/claims.jsonl", "claims")
        # agents
        for p_a in Path.home().joinpath(".claude/agents").glob("*.md"):
            check(p_a, "agents")
        # skills
        for p_s in Path.home().joinpath(".claude/skills").glob("*/SKILL.md"):
            check(p_s, "skills")
        # claude tiers + workbench memory
        for label, cpath in [
            ("global-CLAUDE.md", Path.home() / ".claude/CLAUDE.md"),
            ("project-CLAUDE.md", Path.home() / "Documents/CLAUDE.md"),
        ]:
            if cpath.exists():
                check(cpath, "claude-tiers")
        mem_dir = Path.home() / ".claude/projects/-Users-joshcramoy-Documents-workbench/memory"
        for p_m in mem_dir.glob("*.md"):
            check(p_m, "memory-workbench")
        # all other project memory dirs
        for mem_d in Path.home().joinpath(".claude/projects").glob("*/memory"):
            if mem_d == mem_dir:
                continue
            for p_m in mem_d.glob("*.md"):
                check(p_m, f"memory:{mem_d.parent.name[-40:]}")
        # repo instructions
        for pat in ("*/CLAUDE.md", "*/AGENTS.md"):
            for cpath in Path.home().joinpath("Documents").glob(pat):
                check(cpath, "repo-instructions")
        # fleet prompts
        for p_j in Path.home().joinpath(".local/bin/fleet/jobs").glob("*.prompt"):
            check(p_j, "fleet-jobs")
        # loose docs
        for p_d in Path.home().joinpath("Documents/Claude").glob("*.md"):
            if p_d.name != "CLAUDE.md":
                check(p_d, "loose-docs")
        # KB corpus: every docs row should have >=1 chunk factlet
        kb = get_db()
        n_docs = kb.execute("SELECT COUNT(*) FROM docs").fetchone()[0]
        n_pages = db.execute(
            "SELECT COUNT(*) FROM factlets WHERE level=1 AND source LIKE 'http%'"
        ).fetchone()[0]
        kb.close()
        gap_total = sum(len(v) for v in gaps.values())
        return {
            "checked_files": checked,
            "gap_total": gap_total,
            "gaps_by_surface": {k: v[:8] for k, v in gaps.items() if v},
            "kb_pages_covered": f"{n_pages}/{n_docs}",
            "verdict": "AIRTIGHT" if gap_total == 0 else f"{gap_total} gaps",
        }
    finally:
        db.close()


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    b = sub.add_parser("build")
    b.add_argument("--full", action="store_true")
    z = sub.add_parser("zoom")
    z.add_argument("topic")
    z.add_argument("--level", type=int, default=None)
    z.add_argument("-k", type=int, default=6)
    s = sub.add_parser("show")
    s.add_argument("id")
    sub.add_parser("coverage")
    a = ap.parse_args()
    if a.cmd == "build":
        print(json.dumps(build(full=a.full), indent=2))
    elif a.cmd == "zoom":
        print(json.dumps(zoom(a.topic, a.level, a.k), indent=2))
    elif a.cmd == "show":
        print(json.dumps(show(a.id), indent=2))
    elif a.cmd == "coverage":
        print(json.dumps(coverage(), indent=2))
