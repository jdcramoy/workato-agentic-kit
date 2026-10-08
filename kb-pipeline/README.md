# workato-kb

Local RAG++ knowledge base over all Workato documentation and the BT team's Confluence.
The agent's daily companion for planning, scoping, building, and testing Workato work.

Built 2026-10-08 for Josh's agentic harness. Companion skill: `~/.claude/skills/workato-kb`.

## Sources

| Source | Endpoint | Sync mechanism |
|---|---|---|
| `docs` | docs.workato.com (4,396 pages via first-party `llms.txt`, raw-Markdown twins) | ETag conditional GET, nightly |
| `changelog` | workato.com/product-hub/changelog (RSS + archive pagination) | RSS incremental + quarterly backfill |
| `blog` | blog2workato.wpengine.com (1,197 posts — blog + The Connector share one WP install) | wp-json pagination, sha256 change detect |
| `confluence-extbt` / `confluence-intbt` | workato.atlassian.net BT spaces (1,098 + 2,254 pages) | CQL lastmodified window via API token (keychain `atlassian-confluence`) |
| `github` | system-design-primer, awesome-software-architecture, awesome-system-design-resources (320 md files) | shallow clone + git pull, file-sha256 manifest |
| `eip` | enterpriseintegrationpatterns.com (103 pages: all messaging patterns + ramblings) | link-walk from index, ETag conditional |
| `claude` | Claude platform docs, platform.claude.com (625 en pages via llms.txt md-twins) | ETag conditional GET (generic llms.txt source — add future sites in `kb/llms_source.py`) |
| `inspiration` | Workato Automation Inspiration posts (88, product-hub WP category 436) | wp-json pagination, sha256 change detect |

Corpus lives in `~/.claude/workato-kb/` (gitignored data root):
`corpus/<source>/` markdown, `manifest/<source>.jsonl` per-doc metadata, `index/kb.db`
SQLite (FTS5 + sqlite-vec), `diffs/YYYY-MM-DD.json` nightly change reports.

**Privacy wall:** Confluence corpora are local-only. Never commit, back up, or transmit
them beyond this machine.

## Architecture (RAG++)

1. **Hybrid retrieval** — SQLite FTS5 BM25 + `BAAI/bge-base-en-v1.5` dense embeddings
   (sqlite-vec, MPS) → reciprocal-rank fusion.
2. **Contextual chunking** — deterministic variant: every chunk carries a
   `[source | section | page | url]` header so it's self-describing when retrieved alone.
3. **Cross-encoder rerank** — `BAAI/bge-reranker-base` over fused candidates.
4. **Agentic retrieval loop** — search (snippets) → refine → read (full doc) → cite;
   freshness guard re-fetches the live `.md` when staleness is suspected.
5. **Entropy modulation (phase 2, live)** — per-chunk self-information density
   (bits/word under the corpus unigram model) lifts distinctive chunks among
   rerank-relevant candidates; proper-noun list edge handled by rerank gating.
6. **PMI (phase 2, live)** — pointwise mutual information between query terms and
   chunks: log2(P(t|chunk)/P(t|corpus)) rewards distinctive query-term
   concentration (`kb.pmi build` persists term stats).
7. **Retrieval-distribution entropy gate (phase 2, live)** — Shannon entropy of
   the softmax over final scores; weak + flat distributions trigger one expanded
   second round (confidence reported per query).

## CLI

```bash
cd ~/Documents/workato-kb
.venv/bin/python -m kb.search "how do datapills handle nulls" --source docs
.venv/bin/python -m kb.read 42
.venv/bin/python -m kb.sync                # full sync + reindex (the nightly job)
.venv/bin/python -m kb.indexer             # rebuild chunks + embeddings only
.venv/bin/python -m kb.entropy score       # information-density pass
```

## Nightly job

launchd `com.josh.workato-kb-sync` (02:07): sync all sources → incremental re-index →
diff report → gossip-bus line (`knowledge/dreams/bus/workato-kb.jsonl`).

## Roadmap

- [x] Phase 2: entropy modulation + PMI + retrieval-distribution confidence gate (live 2026-10-08)
- [x] Confluence token sync (v2 pagination, sha-compare; live 2026-10-08)
- [x] Dreamer nightly KB review (3 modes) wired
- [ ] LLM-generated contextual chunk headers (upgrade from deterministic headers)
- [ ] Confluence attachments (PDF extraction)
- [ ] Fleet packaging: public sources into the org kit repo (Confluence stays local)
