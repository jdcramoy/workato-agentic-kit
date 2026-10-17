# Project Dreamer — domain knowledge

The project dreamer is the 7th agent in Josh's network: the harness-dreamer's
sibling for PROJECT content. Where the harness dreamer mines sessions to
improve the harness itself, the project dreamer mines a project's session
history, durable memory (`knowledge/projects/<name>.md`), repo architecture
docs, and git history — and dreams about IMPROVING THE PROJECT: architecture
improvements, new features, better architectural solutions.

## Constitution

- Advisory-only, unconditionally. Project repos are NEVER edited — no
  auto-dev arm exists for this agent (architecture changes are
  `major-development-refactor`, hard-blocked network-wide). It reads the
  same `dreams/config.json` trust ladder; the mode gates only what it
  WRITES (proposals, knowledge-file touches), never code.
- Dissenter gate: in propose+ modes every filed proposal goes through the
  dissenter agent first (fatal/material unanswered = dissent-blocked).
- Blast radius required for proposals touching live Workato assets.

## Shape

- **Agent**: `~/.claude/agents/project-dreamer.md` (full SOP: config read →
  bus read → project selection → four grounding inputs → Mandate A
  pragmatic mine (architecture debt, repeated friction) → Mandate B
  architect's dream (features, better solutions, visions) → dissenter gate
  → report → mode-gated proposal filing with FILE-GATE).
- **Schedule**: launchd `com.josh.fleet.project-dreamer` → fleet
  `run-job.sh project-dreamer`, NIGHTLY 00:37 (after the harness dreamer's
  23:43 slot so it reads the full night's bus). Sunday runs are the deep
  pass (up to three projects, cross-project view). Job dir:
  `~/.local/bin/fleet/jobs/project-dreamer.{env,prompt}`.
- **Reports**: `knowledge/dreams/project/YYYY-MM-DD-<project-slug>.md`.
- **Proposals**: same `knowledge/dreams/proposals/` queue as the harness
  dreamer, `kind: architecture|feature|vision|inventive`, `project: <name>`
  frontmatter, cap 3/night. Brain-gardener Phase 4.5 triages the queue.
- **Bus outbox**: `knowledge/dreams/bus/project-dreamer.jsonl` (added to
  GOSSIP.md roster 2026-10-07 — network is 7 agents + orca-main).

## Selection rule (nightly)

One project per night: the most REAL recent activity (projects/*.md recency
+ transcript activity + git recency). Josh naming a project in the prompt
overrides. Zero activity anywhere = two-line quiet report, no filler.

## First run

2026-10-07 (Josh-built on request: "a co-pilot or dreamer agent for project
content ... what this agent dreams about is actually IMPROVING ARCHITECTURE
and suggesting new features and better architectural solutions"). Run
on-demand before the first scheduled fire to prove the loop; first scheduled
fire is 2026-10-08 00:37.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Memory and the knowledge base architecture](../../kb-corpus/confluence/extbt/2939158533-memory-and-the-knowledge-base-architecture.md)
- [The dreamer and the trust ladder: self-improvement with a human in the loop](../../kb-corpus/confluence/extbt/2939387948-the-dreamer-and-the-trust-ladder-self-improvement-with-a-human-in-the-loop.md)
- [The agents: a nervous system of specialists](../../kb-corpus/confluence/extbt/2938961981-the-agents-a-nervous-system-of-specialists.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
<!-- kb-bridges:end -->
