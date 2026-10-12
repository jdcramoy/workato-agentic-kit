# Librarian — domain knowledge

The librarian is Josh's technical-writer/content-producer agent — the
first PRODUCER in the fleet (everyone else audits, mines, or watches).
Designed and approved 2026-10-11 (brainstorming + grill-gate, all four
directional calls settled by Josh).

## The four design rulings (Josh, 2026-10-11)

1. **Standalone agent**, not a gardener extension. Boundary: gardener
   audits shape/truth, librarian produces content; the gardener audits
   the librarian's output like everything else.
2. **Write authority: additive=direct, edits=branch.** Brand-new files
   (library docs, novel docs, position pieces) go straight to main with
   their INDEX line in the same commit. Consolidations/rewrites of
   existing files, and position pieces, go to a `librarian/YYYY-MM-DD`
   branch for Josh to merge. Never delete or rewrite existing content
   on main. Full git-safety procedure (stash-never-force, the
   2026-10-11 dirty-checkout incident) is mandatory before any checkout.
3. **Procurement: consume + targeted beats.** The four existing weekly
   AI-news skills are the crawl layer; the librarian consumes their
   outputs + kb-digests and does its own TARGETED web searches on a
   rotated beat list (AI advancements, AI thought leadership, business
   systems, software dev best practices, integration patterns). Via MCP
   web-search servers only; native WebSearch/WebFetch never.
4. **Cadence: weekly deep + on-demand.** Sunday 21:37 (clear of gardener
   22:43 / dreamer 23:43 / project-dreamer 00:37). Self-rearming durable
   cron persisting to the project's `.claude/scheduled_tasks.json`.
   On-demand triggers: "run the librarian", "write this up",
   "consolidate these", "procure on X", "position piece".

## Content homes

| Content | Home | Lane |
|---|---|---|
| Procured external synthesis | `knowledge/library/<topic>.md` | additive → main |
| Novel internal docs (primers, how-it-works, integration guides) | `domains/` or `projects/` per scope test | additive → main |
| Position pieces (dissenter-collab) | `knowledge/positions/` | branch until Josh approves; file with dissent log |
| Consolidations of existing files | rewrite on `librarian/*` branch | branch → Josh merges |

Position-piece procedure is constitutional: draft → mandatory dissenter
attack → revise → file WITH a "Dissent log" section carrying the
strongest objection and the answer. A piece whose core attack stands
says so; that is a valid outcome.

## Relationships

- **brain-gardener**: finds consolidation targets (dedup shortlist,
  conflict findings, garden reports) — those are the librarian's work
  order. Gardener audits librarian output.
- **dissenter**: mandatory collaborator on position pieces.
- **harness/project-dreamer**: proposals may hand the librarian a doc to
  write; the librarian does not file proposals.
- **cortex/watchdog/etc.**: no coupling; librarian is content-side only.

## Current state

- 2026-10-11: agent file `~/.claude/agents/librarian.md` + this hub +
  `library/` + `positions/` created; schedule armed (Sun 21:37, durable,
  self-rearming, project scheduled_tasks.json); kit sync
  (agentic-workato-kit: agents/, knowledge/domains/, schedules/).
  First smoke run: see specs/2026-10-11-librarian-design.md verdict.

## Related

- Agent file: `~/.claude/agents/librarian.md` (role + procedure skeleton)
- `domains/brain-architecture.md` — the structural rulebook every doc obeys
- `domains/dream-loop.md` — gossip bus protocol + trust-ladder precedent
- `domains/harness-docs.md` — external publishing stays Josh-gated
