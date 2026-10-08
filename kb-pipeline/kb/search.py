"""Hybrid retrieval, phase 2 (RAG++): BM25 (FTS5) + dense (sqlite-vec) -> RRF fusion
-> cross-encoder rerank -> entropy + PMI modulation -> retrieval-distribution
confidence gate (uncertainty triggers one expanded second round).

Entropy: corpus self-information density (bits/word, kb.entropy) lifts distinctive
chunks among relevant ones; raw list-heavy pages over-score, so entropy only
modulates rerank-gated candidates.
PMI (kb.pmi): query-term concentration, log2(P(t|chunk)/P(t|corpus)) — rewards
chunks where query terms are rare corpus-wide and dense locally.
Confidence gate: entropy H of the softmax over final scores; flat distribution
(H > 0.9 bits) triggers one expanded second round, capped.

    python3 -m kb.search "how do datapills handle nulls"            # top 8
    python3 -m kb.search "..." --source docs --section Connectors   # scoped
    python3 -m kb.search "..." --no-entropy --no-pmi                # ablations
    python3 -m kb.read <doc_id>                                     # full doc + url
"""

from __future__ import annotations

import argparse
import json
import math
import sqlite3
import struct
from dataclasses import dataclass

from .indexer import DB_PATH, MODEL_NAME, get_db
from .pmi import pmi_score, query_terms

RRF_K = 60
ENTROPY_WEIGHT = 0.15
PMI_WEIGHT = 0.10
CONFIDENCE_BITS = 0.9  # distribution entropy above this = uncertain -> second round

SYNONYMS = {
    "datapill": ["datapill", "pill", "data pill"],
    "recipe": ["recipe", "recipes"],
    "formula": ["formula", "formulas"],
    "if": ["condition", "if step", "conditional"],
    "opa": ["on-prem agent", "opa", "on-premise agent"],
    "vua": ["verified user access", "vua", "end-user connection"],
    "genie": ["genie", "genies", "agent studio"],
    "mcp": ["mcp", "model context protocol"],
    "wabt": ["workflow app", "workflow apps"],
    "gear": ["gears", "gear"],
}


@dataclass
class Hit:
    chunk_id: int
    doc_id: int
    url: str
    title: str
    source: str
    section: str
    context: str
    text: str
    bm25_rank: int = 999
    vec_rank: int = 999
    fused: float = 0.0
    rerank: float | None = None
    entropy: float = 0.0
    pmi: float = 0.0
    final: float = 0.0


def expand_query(query: str) -> str:
    q = query.lower()
    parts = [query]
    for canonical, variants in SYNONYMS.items():
        if canonical in q:
            parts.extend(v for v in variants if v not in q)
    return " ".join(parts)


def _fts_safe(query: str) -> str:
    """FTS5 MATCH breaks on raw hyphens/punctuation (bare '-run' = column filter
    or exclusion). Rebuild as quoted tokens joined by OR — ranking fixes itself
    in the fusion layer."""
    import re as _re

    tokens = _re.findall(r"\w{2,}", query.lower())
    return " OR ".join(f'"{t}"' for t in tokens) or '""'


def _bm25(db: sqlite3.Connection, query: str, k: int, source: str | None, section: str | None) -> list[Hit]:
    sql = """
        SELECT c.chunk_id, c.doc_id, d.url, d.title, d.source, d.section, c.context, c.text
        FROM chunks_fts f
        JOIN chunks c ON c.chunk_id = f.rowid
        JOIN docs d ON d.doc_id = c.doc_id
        WHERE chunks_fts MATCH ?
    """
    params: list = [_fts_safe(query)]
    if source:
        sql += " AND d.source = ?"
        params.append(source)
    if section:
        sql += " AND d.section LIKE ?"
        params.append(f"%{section}%")
    sql += " ORDER BY bm25(chunks_fts) LIMIT ?"
    params.append(k)
    return [Hit(*row) for row in db.execute(sql, params).fetchall()]


def _vec(db: sqlite3.Connection, query: str, k: int, source: str | None, section: str | None) -> list[Hit]:
    from sentence_transformers import SentenceTransformer

    model = SentenceTransformer(MODEL_NAME)
    emb = model.encode([query], normalize_embeddings=True)[0].tolist()
    binding = struct.pack(f"{len(emb)}f", *emb)
    sql = """
        SELECT c.chunk_id, c.doc_id, d.url, d.title, d.source, d.section, c.context, c.text
        FROM chunks_vec v
        JOIN chunks c ON c.chunk_id = v.chunk_id
        JOIN docs d ON d.doc_id = c.doc_id
        WHERE v.embedding MATCH ? AND k = ?
    """
    params: list = [binding, k * 3]
    if source:
        sql += " AND d.source = ?"
        params.append(source)
    sql = f"SELECT * FROM ({sql}) WHERE 1=1"
    if section:
        sql += " AND section LIKE ?"
        params.append(f"%{section}%")
    sql += f" LIMIT {k}"
    return [Hit(*row) for row in db.execute(sql, params).fetchall()]


def _rrf_fuse(bm25_hits: list[Hit], vec_hits: list[Hit]) -> dict[int, Hit]:
    fused: dict[int, Hit] = {}
    for rank, h in enumerate(bm25_hits):
        h.bm25_rank = rank
        h.fused += 1.0 / (RRF_K + rank + 1)
        fused[h.chunk_id] = h
    for rank, h in enumerate(vec_hits):
        h.vec_rank = rank
        h.fused += 1.0 / (RRF_K + rank + 1)
        fused[h.chunk_id] = h
    return fused


def _hydrate_entropy(db: sqlite3.Connection, hits: list[Hit]) -> None:
    if not hits:
        return
    ids = [h.chunk_id for h in hits]
    qmarks = ",".join("?" * len(ids))
    for cid, ent in db.execute(
        f"SELECT chunk_id, entropy FROM chunks WHERE chunk_id IN ({qmarks})", ids
    ):
        for h in hits:
            if h.chunk_id == cid:
                h.entropy = ent or 0.0


def _rerank(query: str, hits: list[Hit], top_k: int, use_entropy: bool, use_pmi: bool) -> list[Hit]:
    if not hits:
        return hits
    try:
        from sentence_transformers import CrossEncoder

        model = CrossEncoder("BAAI/bge-reranker-base")
        pairs = [(query, f"{h.context}\n\n{h.text}") for h in hits]
        scores = model.predict(pairs)
        for h, s in zip(hits, scores):
            h.rerank = float(s)
        hits.sort(key=lambda h: h.rerank, reverse=True)
    except Exception as e:  # noqa: BLE001 - rerank failure falls back to RRF order
        print(f"[rerank unavailable: {e}; using RRF order]", flush=True)
        return hits[:top_k]

    hits = hits[:top_k]

    # --- entropy modulation: relevance first, surprise density as tiebreak ---
    if use_entropy:
        ents = [h.entropy for h in hits]
        lo, hi = min(ents), max(ents)
        span = (hi - lo) or 1.0
        for h in hits:
            e_norm = (h.entropy - lo) / span
            h.final = h.rerank * (1.0 + ENTROPY_WEIGHT * e_norm)
    else:
        for h in hits:
            h.final = h.rerank

    # --- PMI modulation: distinctive query-term concentration ---
    if use_pmi:
        pmis = [pmi_score(query, h.text) for h in hits]
        lo, hi = min(pmis), max(pmis)
        span = (hi - lo) or 1.0
        for h, p in zip(hits, pmis):
            h.pmi = p
            h.final *= 1.0 + PMI_WEIGHT * ((p - lo) / span)

    hits.sort(key=lambda h: h.final, reverse=True)
    return hits


def _distribution_entropy(hits: list[Hit]) -> float:
    """Shannon entropy (bits) of the softmax over final scores of the top-k."""
    finals = [h.final for h in hits]
    if len(finals) < 2:
        return 0.0
    mx = max(finals)
    exps = [math.exp(f - mx) for f in finals]
    z = sum(exps)
    ps = [e / z for e in exps]
    return -sum(p * math.log2(p) for p in ps if p > 0)


def search(
    query: str, k: int = 8, source: str | None = None, section: str | None = None,
    rerank: bool = True, use_entropy: bool = True, use_pmi: bool = True,
) -> tuple[list[Hit], dict]:
    """Returns (hits, meta). meta carries the confidence-gate trace."""
    meta: dict = {"rounds": 1, "confidence_bits": None, "expanded": False}
    db = get_db()
    try:
        expanded = expand_query(query)
        bm25_hits = _bm25(db, expanded, k * 5, source, section)
        vec_hits = _vec(db, expanded, k * 5, source, section)
        fused = _rrf_fuse(bm25_hits, vec_hits)
        ranked = sorted(fused.values(), key=lambda h: h.fused, reverse=True)[: k * 2]

        if not rerank:
            return ranked[:k], meta

        _hydrate_entropy(db, ranked)
        hits = _rerank(query, ranked, k, use_entropy, use_pmi)
        meta["confidence_bits"] = round(_distribution_entropy(hits), 3)

        # --- retrieval-distribution entropy gate: uncertain (flat distribution AND
        # weak top rerank) -> one expanded second round. Flat among strong hits is
        # confidence, not uncertainty; only flat-and-weak justifies more fetching. ---
        top_rerank = hits[0].rerank if hits and hits[0].rerank is not None else 0.0
        uncertain = meta["confidence_bits"] > CONFIDENCE_BITS and top_rerank < 0.5
        if uncertain and not meta["expanded"]:
            meta["expanded"] = True
            meta["rounds"] = 2
            title_terms = [t for t in query_terms(hits[0].title) if len(t) >= 3] if hits else []
            second_query = f"{query} {' '.join(title_terms[:4])}".strip()
            bm25_2 = _bm25(db, expand_query(second_query), k * 3, source, section)
            vec_2 = _vec(db, expand_query(second_query), k * 3, source, section)
            fused_2 = _rrf_fuse(bm25_2, vec_2)
            seen = {h.chunk_id for h in hits}
            extra = [h for h in fused_2.values() if h.chunk_id not in seen]
            if extra:
                _hydrate_entropy(db, extra)
                more = _rerank(second_query, extra[: k * 2], k // 2, use_entropy, use_pmi)
                hits = sorted(hits + more, key=lambda h: h.final, reverse=True)[:k]
                meta["confidence_bits"] = round(_distribution_entropy(hits), 3)
                meta["second_query"] = second_query
        return hits, meta
    finally:
        db.close()


def format_hits(hits: list[Hit], meta: dict | None = None) -> str:
    lines = []
    if meta:
        conf = meta.get("confidence_bits")
        gate = f", expanded to round 2 ({meta.get('second_query', '')[:60]})" if meta.get("expanded") else ""
        lines.append(f"[confidence: {conf} bits over {meta.get('rounds')} round(s){gate}]")
    for i, h in enumerate(hits, 1):
        score = h.final if h.final else (h.rerank or h.fused)
        lines.append(
            f"{i}. [{h.source}] {h.title} ({score:.3f})"
            + (f" ent {h.entropy:.1f}" if h.entropy else "")
            + (f" pmi {h.pmi:.2f}" if h.pmi else "")
            + f"\n   url: {h.url}\n"
            f"   section: {h.section}\n"
            f"   {h.text[:300]}...".replace("\n", " ")
        )
    return "\n\n".join(lines) if lines else "no results"


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("query")
    ap.add_argument("-k", type=int, default=8)
    ap.add_argument("--source", default=None)
    ap.add_argument("--section", default=None)
    ap.add_argument("--no-rerank", action="store_true")
    ap.add_argument("--no-entropy", action="store_true")
    ap.add_argument("--no-pmi", action="store_true")
    a = ap.parse_args()
    hits, meta = search(
        a.query, k=a.k, source=a.source, section=a.section,
        rerank=not a.no_rerank, use_entropy=not a.no_entropy, use_pmi=not a.no_pmi,
    )
    print(format_hits(hits, meta))


if __name__ == "__main__":
    main()
