---
name: kb
description: Query the local Workato RAG++ knowledge base interactively — /kb <query> or /kb --source docs|changelog|blog|inspiration|github|eip|claude|confluence <query>. Returns hybrid-retrieval results (BM25 + vectors + entropy + PMI + rerank) with citations. Use when Josh asks a Workato/platform/architecture question directly and wants KB answers with sources.
---

# /kb — query the Workato RAG++ knowledge base

## Parse the invocation

- Everything after `/kb` is the query.
- Flags (before or in the query): `--source <name>`, `--section <name>`, `-k <n>`.
- Sources: `docs` (Workato product docs) `changelog` `blog` `inspiration` `github` (architecture canon) `eip` (integration patterns) `claude` (Claude platform docs) `confluence` (BT Confluence extbt + intbt, INTERNAL) or a specific confluence space.
- No query → show source stats and recent diff summaries instead of searching.

## Search procedure

1. Run from the KB repo:
   `cd ~/Documents/workato-kb && .venv/bin/python -m kb.search "<query>" [-k 8] [--source ...] [--section ...]`
2. Present the results as a decision-ready answer:
   - Lead with a 1-3 sentence direct answer synthesized from the top hits (not a dump).
   - Then the source list: title, source, score, clickable URL — one line each.
   - Flag the confidence line (bits / rounds) when it says "expanded" — it means retrieval was hard and the answer may be partial.
3. If the top hits are close but not conclusive, READ the full doc before answering:
   `cd ~/Documents/workato-kb && .venv/bin/python -m kb.read <doc_id>` — never quote a snippet you haven't seen in context when the stakes are a decision.
4. Cite the canonical URL on every claim. For `confluence` results, mark them "internal BT Confluence".
5. If the answer needs the very latest state (new release, deprecation), fetch the live page as the tiebreaker (docs pages: same URL with `.md`; else `mcp__fireworks-websearch__web_fetch`) and say which source won.

## Conventions

- Never fabricate a KB answer — if retrieval returns nothing relevant, say so and offer a web search fallback.
- Confluence content never leaves this machine: do not paste it into external services, tickets, or Slack.
- Multiple queries are fine (`/kb` then refine) — but batch: one search, refine once, read once is the healthy loop.
