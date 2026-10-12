# Spec: The Librarian agent

Date: 2026-10-11. Approved by Josh in-session (brainstorming + grill-gate,
all four directional calls settled by recommendation-accept).

## Goal

Add a librarian/technical-writer agent to the fleet: organize the KB
corpus, write novel documentation, and procure external content — the
first agent whose output is new written content rather than a report.

## Directional rulings (Josh, 2026-10-11)

1. **Standalone agent** (not a gardener extension). Gardener audits;
   librarian produces; gardener audits librarian output.
2. **Write authority: additive=direct, edits=branch.** New files → main
   with INDEX line in same commit. Consolidations/rewrites of existing
   files and position pieces → `librarian/YYYY-MM-DD` branch for Josh.
   Never delete/rewrite existing content on main. Git-safety procedure
   (stash-never-force, post-2026-10-11-incident) mandatory.
3. **Procurement: consume + targeted beats.** Four weekly AI-news skills
   stay the crawl layer; librarian consumes their outputs + kb-digests,
   then targeted searches on a rotated beat list via MCP web-search
   servers only.
4. **Cadence: weekly deep + on-demand.** Sunday 21:37 (clear of gardener
   22:43 / dreamer 23:43 / project-dreamer 00:37), self-rearming durable
   cron, project scheduled_tasks.json.

## Components

- `~/.claude/agents/librarian.md` — agent file (role, constitution, 5-phase
  weekly procedure: context read → corpus sweep → novel doc → position
  piece (mandatory dissenter) → procurement → report).
- `domains/librarian.md` — hub: rulings, content homes, relationships, state.
- `knowledge/library/` — procured external synthesis (additive → main).
- `knowledge/positions/` — dissenter-collab position pieces (branch-gated,
  each with a dissent log).
- INDEX.md lines for all of the above (one line per file).
- Gossip bus node: `dreams/bus/librarian.jsonl` (own outbox, read-first).
- Schedule: durable cron Sun 21:37, self-rearming prompt (7-day expiry
  workaround), persists to project `.claude/scheduled_tasks.json`.
- Kit sync: agents/librarian.md, knowledge/domains/librarian.md,
  schedules/librarian-weekly.txt in agentic-workato-kit.

## Content homes (scope test applies)

| Content | Home | Lane |
|---|---|---|
| Procured external synthesis | library/<topic>.md | additive → main |
| Novel internal docs | domains/ or projects/ | additive → main |
| Position pieces | positions/ | branch until Josh |
| Consolidations of existing files | librarian/* branch | Josh merges |

## Hard rules

Additive-only on main; git safety before any checkout; citations with
URL + fetch date; absolute dates; brain-architecture size budgets;
external publishing Josh-gated in josh-writing-voice (internal KB docs
in neutral agent prose, no em/en dashes anywhere); transcripts
grep-and-sample; KB corpus read-only.

## Acceptance criteria

- Agent file routes on Josh's natural asks ("run the librarian",
  "write this up", "consolidate", "procure", "position piece").
- First smoke run produces: one library doc (additive, cited, INDEX'd),
  a report, a bus post — and either a position piece or an explicit
  pass-with-reason.
- Schedule visible in project scheduled_tasks.json with self-rearming.
- Kit repo carries the synced copies.

## Not built (future decisions)

Feeding accepted library docs into the RAG++ kb-corpus for /kb retrieval;
trust-ladder auto-safe expansion; nightly light pass.
