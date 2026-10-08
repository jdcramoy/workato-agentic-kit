---
name: workato-kb
description: Deep Workato knowledge base (RAG++) over docs.workato.com, the product changelog, the Workato blog/The Connector, architecture-canon GitHub repos (system-design-primer, awesome-software-architecture, awesome-system-design-resources), and the BT Confluence spaces (extbt + intbt). Use during planning, scoping, design, build, and test phases of ANY Workato work, when a Workato platform question could be answered from documentation, when you need a formula/connector/best-practice detail, when designing system architecture, when citing docs, or when Josh asks to "check the docs", "search the KB", "what does Workato documentation say", or "have we seen this before internally". Daily companion during planning and build.
---

# Workato KB (RAG++)

A local, nightly-synced knowledge base. Four sources, one index, mandatory citations.

| Source | What it holds | Privacy |
|---|---|---|
| `docs` | All 4,396 docs.workato.com pages as Markdown (Gears, frameworks, best practices, formulas, connectors, SDK, AIRO, Agent Studio...) | public |
| `changelog` | product-hub changelog posts (releases, deprecations, new connectors) | public |
| `blog` | Workato blog + The Connector posts (1,197; thought leadership, launch announcements, patterns) | public |
| `github` | Architecture canon: system-design-primer, awesome-software-architecture, awesome-system-design-resources (320 md files, shallow-cloned, git-pull sync) | public |
| `eip` | Enterprise Integration Patterns (103 pages: every messaging pattern + ramblings/real-world examples) | public |
| `claude` | Claude platform docs (625 en pages, llms.txt markdown twins) | public |
| `inspiration` | Workato Automation Inspiration (88 real-world automation pattern posts) | public |
| `confluence/extbt` + `confluence/intbt` | BT team KB: troubleshooting runbooks, change requests, architecture pages, AEM/ops docs | **INTERNAL — never leave this machine, never quote verbatim externally, never sync to any repo or backup** |

## The retrieval loop (agentic — do NOT dump results into context)

1. **Query**: `~/Documents/workato-kb/.venv/bin/python -m kb.search "your question" [-k 8] [--source docs] [--section Connectors]` (run from `~/Documents/workato-kb`).
   - Phase-2 stack: BM25 + dense vector + RRF fusion + cross-encoder rerank, then entropy modulation (surprise density lifts distinctive chunks) and PMI (query-term concentration), then a retrieval-distribution confidence gate — weak+flat results trigger one expanded second round automatically (reported in the output header).
   - Ablate with `--no-entropy` / `--no-pmi` when comparing result quality.
   - `--source` narrows: `docs|changelog|blog|inspiration|github|eip|claude|confluence/extbt|confluence/intbt`.
2. **Skim and refine**: snippets tell you if the hits are on target. Refine the query or add a filter before reading anything in full. Two refinements max, then widen.
3. **Read**: `python3 -m kb.read <doc_id>` or `python3 -m kb.read --url "..."` for the full document. Read only what you need.
4. **Cite every claim**: canonical URL from the hit. For Confluence sources, cite the page URL and note it is internal BT documentation.
5. **Freshness guard**: if a page might be stale (recent release, deprecation), fetch the live page — docs pages accept `.md` suffix (e.g. `https://docs.workato.com/en/airo.md` returns raw Markdown); use `mcp__fireworks-websearch__web_fetch` for others. If live and local disagree, the live page wins; report the divergence.

## Corpus maintenance

- Nightly sync (launchd `com.josh.workato-kb-sync`): etag-conditional docs sync, changelog RSS, blog pagination, Confluence lastmodified window, re-index of changed docs, diff report to `~/.claude/workato-kb/diffs/YYYY-MM-DD.json` + gossip bus.
- Confluence incremental sync needs the API token in keychain (service `atlassian-confluence`); if missing the step self-skips and says so in the diff report.
- Re-run index manually: `cd ~/Documents/workato-kb && .venv/bin/python -m kb.indexer`. After a corpus change, also rebuild term stats + entropy: `.venv/bin/python -m kb.pmi build && .venv/bin/python -m kb.entropy score` (search.py auto-builds term stats if missing).
- Phase-2 layers are LIVE in `kb/search.py`: entropy modulation (ENTROPY_WEIGHT 0.15), PMI (PMI_WEIGHT 0.10, term stats in `index/terms.json.gz`), confidence gate (expand when distribution entropy > 0.9 bits AND top rerank < 0.5). Known entropy edge: proper-noun lists score high on raw rarity — that's why entropy only modulates rerank-gated candidates.

## Advanced modes (v0.6)

- `kb zoom "topic"` — fractal zoom: coarse-first retrieval over the factlet
  hierarchy (topic → file → section → chunk); read the coarsest level that
  answers, drill only on decision. The factlet schema is identical at every
  scale — same unit, any depth.
- `kb funnel search "query"` — Matryoshka-style funnel: coarse page-context
  embedding shortlists, fine chunk search refines. Falls back to plain fine
  search when the coarse layer's coverage is weak. Coverage grows as the
  contextualize backlog drains.
- `kb criticality` — fleet cascade power-law fit; tells you whether the agent
  network's information flow is subcritical, critical, or flooded.
- MCP server: `~/Documents/workato-kb/.venv/bin/python -m kb.mcp_server`
  (stdio; kb_search / kb_read / kb_zoom) for any MCP client.

## Known limits (v0.1)

- Attachments (PDFs) not crawled.
- Confluence tables/emojis render imperfectly through markdown conversion.
- bge-base embeddings + bge-reranker-base are local and good, not frontier. If keyword recall fails on a fuzzy concept question, try synonyms via the query-expansion table in `kb/search.py` or rephrase.
- The changelog backfill is archive-pagination based; if Workato changes the archive structure, backfill via `python3 -m kb.wp_source`-style scripts with the feed as fallback.
