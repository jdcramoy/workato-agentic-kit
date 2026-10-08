# The agents: a nervous system of specialists

Parent page: The Agentic Workato Harness

Every agent is a markdown SOP in `~/.claude/agents/`: role, grounds, cadence,
phase-by-phase procedure, hard rules. They are advisory by construction. They
report and propose; they never mutate the estate or the knowledge base without
approval. The one exception is proposal branches, which land only on
`gardener/*` branches of the knowledge repo, where a human reviews the diff
before merging.

## The roster

**brain-gardener** (nightly 22:43, full review weekly). The curator and the
architect of memory. Reads its own acceptance-rate log first (which kinds of
proposals get rejected, and at what rate), then inventories the knowledge tree
against its index, checks for conflicts, duplication, and temporal rot, runs
structural audits (file size budgets, modularization, index discipline,
routing quality of skill and agent descriptions), rolls up opportunistic claim
verifications, mines session transcripts for unrecorded lessons, and files a
garden report with a top five priority list. Nightly runs review only what
changed since the last report; the weekly run does the full inventory.

**workato-watchdog** (nightly 23:13). The body's proprioception. Five checks:
exception connections with running-recipe blast radius (P1), stalled
schedulers (running recipes with no recent jobs, the silent post-restart
failure class), failure autopsies clustered by error class with proposed
playbook entries, external edit detection (recipes whose update time moved
with no ledger entry, which is how human UI edits and other agents show up),
and postmortem drafts for P1 incidents, filed only on approval. It opens with
a machine-health line: if last night's gardener or crawler never heartbeated,
that is a P0.

**estate-architect** (Mondays 06:37). Six phases: cost heatmap coupling
runtime tasks per folder with development token spend; zombie hygiene (recipes
with no runs in 90 days, orphaned tables and connections); configuration
parity between environments; lineage maps per folder; security posture
heuristics (personal-account connections, identity per skill); and a
deprecation radar matching platform release deltas against recipes that use
the affected features.

**promotion-orchestrator** (on demand; batches are inventory-driven, never
scheduled). Phase 1 selects the batch from the build ledger: dev mutations
newer than their last promotion marker, nothing else, ever. Phase 2 assembles
the manifest with only those assets and captures the rollback snapshot hash.
Phase 3 files the deployment story with the manifest URL, environment fields,
and points, showing the draft for approval first. Phase 4 stages production
execution: dependency order, verification after import, smoke tests per
stage, each step on an explicit go.

**harness-dreamer** (nightly 23:43). The only agent that reads the harness
instead of the estate. Mines recent session transcripts for corrections,
repeats, and recurring errors, reads the whole night's gossip bus as
reader-in-chief (it runs last), and writes a dream report under two mandates:
a pragmatic one (what is being worked on, what is being repeated, what went
wrong, what would have made yesterday faster) and a visionary one, freed from
evidence, writing forward-looking seeds for what the harness becomes. Proposals
are mode-gated by the trust ladder (see the trust ladder page).

**dissenter** (on call, and mandatory before any dream proposal reaches a
human). The immune system. Its only job is to produce the strongest possible
argument against whatever is placed in front of it. Every objection cites a
file, a trace, a claim, or a concrete failure scenario; "feels risky" is not
an objection. It names severity (fatal, material, cosmetic) and never
softens it. It never proposes fixes; it diagnoses. When a proposal survives
its best attack, it posts one line: "steel manned, could not break it". That
line is worth more than ten approvals.

**cortex** (hourly pulse, inside the hidden lane). The brain. The other agents
are specialists; the cortex attends. Three jobs: attention (a ranked queue of
what deserves focus, capped at 7 items, rebuilt every pulse), coherence
(cross-checking the bus, the dreams, the claims, the canon, and the watchdog
reports against each other; contradictions are its highest-value output), and
curiosity (the questions nobody is asking, routed to the right agent as
handoffs). It reads everything and mutates nothing. Its only surface is the
morning brief's top three.

## How they validate and challenge each other

The design assumes agents will be wrong individually, so correctness is a
network property:

- **The watchdog checks the checkers.** Every scheduled job must check in to
  a heartbeat ledger. The watchdog runs last among the watchers and opens its
  report with the heartbeat line: a silently skipped curator or crawler is
  itself a P0 finding.
- **Corroboration is the confidence unit.** One witness is an observation,
  two witnesses is a pattern, three or more means act on it. Independent
  agents reaching the same conclusion through different methods is the
  strongest evidence class the harness has, and it is computed mechanically
  by the gossip bus (see the gossip bus page).
- **The dissenter attacks before a human sees anything.** Dream proposals
  must survive adversarial review first. The network agrees too easily; the
  dissenter exists to break that.
- **The cortex hunts contradictions.** A claim that says X while the watchdog
  saw not-X, two agents reporting opposite states, a dream proposal for
  something the regression canon already covers: these are the findings it
  leads with.
- **The gardener audits the claims and the structure.** Stale claims get
  re-verified or disputed; conflicting knowledge gets an edit proposal;
  files that have grown past their budget get a modularization proposal.
- **Nothing self-approves.** No agent may approve its own proposal, and the
  humans' only required reading, the morning brief, leads with what the
  whole network corroborated.

Verdict: individually each agent is a competent specialist with no memory;
together they are a system that notices its own gaps, argues with itself
before bothering a human, and gets harder to fool every week.
