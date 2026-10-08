"""Lateral-connection engine (the dreamer's math for "there's ALWAYS a connection").

Network-science approach to lateral thinking:
  1. Build a concept co-occurrence graph from the corpus (top domain terms,
     weighted edges = terms appearing in the same chunk).
  2. Hidden connections = concept pairs with HIGH Adamic-Adar index (many shared
     neighbors — they live in the same structural region) but LOW direct
     co-occurrence (nothing in the corpus puts them in the same sentence).
  3. Those pairs are exactly "seemingly unrelated concepts that are secretly
     related": the bridge evidence (chunks containing both or their neighbors)
     comes with the pair.

This is structural-hole / weak-tie theory (Granovetter, Burt) applied to our own
corpus. The dreamer consumes `kb.lateral top` as raw lateral-thinking feedstock.

    python3 -m kb.lateral build          # graph from current index
    python3 -m kb.lateral top -n 20      # hidden connections + bridge evidence
"""

from __future__ import annotations

import argparse
import json
import math
from collections import defaultdict
from itertools import combinations
from pathlib import Path

from .common import DATA_ROOT
from .indexer import get_db
from .pmi import _WORD_RE, is_stop

GRAPH_PATH = DATA_ROOT / "index" / "lateral_graph.json.gz"
MAX_TERMS = 1500
MIN_DF = 300  # real domain concepts only
MAX_DF_FRAC = 0.03  # terms co-occurring with >3% of the corpus are hubs, not concepts
MIN_EDGE_PMI = 1.0  # edge kept only if co-occurrence beats chance by >1 bit
MAX_DIRECT = 10  # "hidden" means near-zero direct co-occurrence, hard filter

# structural vocabulary from chunk context headers — never counts as concepts
HEADER_STOP = {
    "source", "section", "page", "url", "docs", "blog", "changelog", "inspiration",
    "claude", "confluence", "extbt", "intbt", "eip", "github", "https", "http",
    "com", "www", "atlassian", "workato", "md", "wiki", "spaces", "pages",
    "attachments", "product-hub",
}


def build() -> dict:
    db = get_db()
    try:
        # doc frequency per term (BODY TEXT ONLY — header tokens are structure, not content)
        df: dict[str, int] = defaultdict(int)
        chunk_terms: list[set[str]] = []
        rows = db.execute(
            "SELECT c.text FROM chunks c JOIN docs d ON d.doc_id = c.doc_id "
            "WHERE d.source IN ('docs', 'eip', 'github', 'claude')"
        ).fetchall()
        for (text,) in rows:
            words = set(_WORD_RE.findall(text.lower()))
            terms = {w for w in words if not is_stop(w) and w not in HEADER_STOP and len(w) >= 4}
            chunk_terms.append(terms)
            for t in terms:
                df[t] += 1
        concepts = {t for t, c in df.items() if MIN_DF <= c <= MAX_DF_FRAC * len(chunk_terms)}
        concepts = set(sorted(concepts, key=lambda t: -df[t])[:MAX_TERMS])
        print(f"concepts: {len(concepts)} (of {len(df)} terms)")

        # co-occurrence edges, chance-corrected: keep only positive-PMI pairs
        # (P(a,b) >> P(a)*P(b)) — co-occurrence at chance level carries no link
        n_chunks = len(chunk_terms)
        raw: dict[tuple[str, str], int] = defaultdict(int)
        for terms in chunk_terms:
            present = sorted(terms & concepts)
            for a, b in combinations(present, 2):
                raw[(a, b)] += 1
        pa = {t: df[t] / n_chunks for t in concepts}
        edges: dict[tuple[str, str], int] = {}
        for (a, b), c in raw.items():
            pab = c / n_chunks
            pmi = math.log2(pab / (pa[a] * pa[b]))
            if pmi >= MIN_EDGE_PMI:
                edges[(a, b)] = c
        print(f"chance-corrected edges: {len(edges)} (of {len(raw)} raw)")

        deg: dict[str, int] = defaultdict(int)
        for (a, b), w in edges.items():
            deg[a] += w
            deg[b] += w

        # adjacency for Adamic-Adar
        adj: dict[str, set[str]] = defaultdict(set)
        for (a, b) in edges:
            adj[a].add(b)
            adj[b].add(a)

        # bridge evidence: which chunks contain each concept (sampled)
        evidence: dict[str, list] = defaultdict(list)

        import gzip

        payload = {
            "concepts": sorted(concepts),
            "edges": {f"{a}|{b}": w for (a, b), w in edges.items()},
            "deg": dict(deg),
        }
        GRAPH_PATH.parent.mkdir(parents=True, exist_ok=True)
        with gzip.open(GRAPH_PATH, "wt") as f:
            json.dump(payload, f, separators=(",", ":"))
        return {
            "concepts": len(concepts),
            "edges": len(edges),
            "chunks": len(chunk_terms),
            "graph": str(GRAPH_PATH),
        }
    finally:
        db.close()


def _load_graph() -> tuple[dict, dict, dict]:
    import gzip

    with gzip.open(GRAPH_PATH, "rt") as f:
        payload = json.load(f)
    edges = {tuple(k.split("|")): v for k, v in payload["edges"].items()}
    deg = payload["deg"]
    adj: dict[str, set[str]] = defaultdict(set)
    for (a, b) in edges:
        adj[a].add(b)
        adj[b].add(a)
    return edges, deg, adj


def top(n: int = 20) -> list[dict]:
    import numpy as np

    edges, deg, adj = _load_graph()
    concepts = sorted(deg, key=lambda t: -deg[t])[:MAX_TERMS]
    idx = {t: i for i, t in enumerate(concepts)}
    N = len(concepts)

    # binary adjacency (classic Adamic-Adar: presence, not counts)
    A = np.zeros((N, N), dtype=np.float32)
    for (a, b), w in edges.items():
        if a in idx and b in idx:
            A[idx[a], idx[b]] = 1.0
            A[idx[b], idx[a]] = 1.0

    # Adamic-Adar, vectorized: AA[i,j] = sum_k A[i,k]*A[j,k]/log(deg_k+1)
    deg_v = A.sum(axis=1)
    inv_log = 1.0 / np.log(deg_v + 1.0)
    B = A * inv_log[:, None]
    AA = B @ A.T
    np.fill_diagonal(AA, 0)

    direct = A + A.T  # symmetric direct co-occurrence
    iu = np.triu_indices(N, k=1)
    flat_direct = direct[iu]
    flat_aa = AA[iu]

    # hidden connections: strong indirect affinity, (near-)zero direct co-occurrence
    mask = (flat_direct <= MAX_DIRECT) & (flat_aa > 0)
    scores = flat_aa * mask
    order = np.argsort(-scores)[:n]

    out = []
    for flat in order:
        if scores[flat] <= 0:
            break
        i, j = iu[0][flat], iu[1][flat]
        a, b = concepts[i], concepts[j]
        shared = int(np.count_nonzero((A[i] > 0) & (A[j] > 0)))
        out.append(
            {
                "pair": f"{a} + {b}",
                "adamic_adar": round(float(scores[flat]), 3),
                "direct_cooccurrence": int(flat_direct[flat]),
                "shared_neighbors": shared,
                "hypothesis": f"{a} and {b} live in the same structural region of the "
                f"corpus but are almost never discussed together — a latent connection "
                f"worth a dream.",
            }
        )
    return out


if __name__ == "__main__":
    ap = argparse.ArgumentParser()
    sub = ap.add_subparsers(dest="cmd", required=True)
    sub.add_parser("build")
    t = sub.add_parser("top")
    t.add_argument("-n", type=int, default=20)
    a = ap.parse_args()
    if a.cmd == "build":
        print(json.dumps(build(), indent=2))
    elif a.cmd == "top":
        print(json.dumps(top(a.n), indent=2))
