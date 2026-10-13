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
line is worth more than ten approvals. The gate is wired into the dreamers
themselves: the project-dreamer spawns the dissenter on every proposal
before filing, and a proposal with unanswered fatal or material dissent is
dissent-blocked and goes to the human instead.

**project-dreamer** (nightly 00:37, deep pass Sundays). The harness-dreamer
dreams about the harness; the project-dreamer dreams about the actual
PROJECTS. Each night it picks the project with the most real activity
(Josh can name one instead), grounds itself in four inputs: the project's
session history (mined for the archaeology of decisions, not read whole),
the durable project memory in the knowledge tree (with a staleness sample
against the repo), the repo's actual architecture and code shape, and the
last 14 days of git history where churn hotspots confess architecture
debt. Mandate A finds architecture debt, repeated friction, and
operational reality, every finding evidence-cited. Mandate B is the
architect's dream: features worth building next, better architectural
solutions, and the 3 to 12 month version of the project, marked as vision
so they travel the pipeline honestly. It files at most 3 proposals a
night, each with the exact change drafted and the rollback stated, and it
never touches project code: advisory-only is constitutional, and that arm
does not exist even at the auto-dev rung.

**evidence** (on demand, and nightly in the background). The claim hunter.
It finds every "done / built / fixed / verified" statement from the last 24
hours (in reports, on the bus, in ledgers) and re-checks each against live
evidence: a Workato read, a job trace, a file, a Jira state. A FALSE verdict
routes the claim to a dissenter review automatically. It never mutes and
never edits the things it audits.

**spec-distiller** (at the start of any build). Writes the build spec before
any code: goal, scope in and out, objectively verifiable acceptance criteria,
a design-gate note, and risks. Advisory only: it never builds. The point is
that requirements get pinned into a contract while changing them is still
cheap.

**librarian** (weekly, and on demand). The fleet's first producer. Two jobs:
organize the knowledge corpus (consolidation of related docs, distilled
documentation, position pieces written collaboratively with the dissenter;
every position carries a dissent log), and procure external content on a
beat list (AI advancements, platform releases, engineering best practices),
synthesized rather than pasted.

**cortex** (hourly pulse, inside the hidden lane). The brain. The other agents
are specialists; the cortex attends. Three jobs: attention (a ranked queue of
what deserves focus, capped at 7 items, rebuilt every pulse), coherence
(cross-checking the bus, the dreams, the claims, the canon, and the watchdog
reports against each other; contradictions are its highest-value output), and
curiosity (the questions nobody is asking, routed to the right agent as
handoffs). It reads everything and mutates nothing. Its only surface is the
morning brief's top three.

**red-team** (on demand, at promotion prep). The independent security
reviewer. Before any asset is promoted to production, the build session
dispatches it to attack the asset across five surfaces: secrets and
credentials, data exposure, injection (including prompt injection), identity
and auth, and logic abuse. Reviews are risk-tiered: full review for anything
touching personal or financial data or facing outward, standard for internal
assets with shared dependencies, light self-certification for config flips.
The verdict is evidence-cited (pass, pass with notes, or fail, with severity
named as fatal, material, or cosmetic) and lands in the knowledge tree and on
the governing ticket. A fail blocks promotion unless the human overrides by
name, and the override is recorded in the verdict itself. The rule the whole
gate rests on: the builder never reviews its own work, and a review written
from the recipe definition alone, without the live configuration and real job
traces, does not count.

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
- **The evidence agent closes the loop.** Claims are spot-checked against
  live state within a day of being made, and the reconciler cross-checks
  internal ledgers against external systems nightly (see the memory page).
- **Every agent runs on a pinned model family.** Each agent's frontmatter
  pins the gateway model its role needs (a watchdog on the cost-efficient
  flagship, the dissenter on a different family than the dreamer it
  reviews, and so on), chosen from a benchmarked roster with a ledgered
  bench script. Advisers and reviewers on different model lineages catch
  errors that a single-family fleet shares blind.

Verdict: individually each agent is a competent specialist with no memory;
together they are a system that notices its own gaps, argues with itself
before bothering a human, and gets harder to fool every week.

## The dreaming team

The two dreamers (harness and project) are where the night's learning
compounds. Their constitution: convene a board of professional lenses
(doctor, lawyer, artist, musician, CEO, engineer, accountant, product
manager, CTO, rotating, running on three different model lineages with the
frontier model cost-governed to one seat per night); consume the lateral
engine's hidden concept pairs as raw material; attach a math block to every
proposal (Bayesian acceptance probability learned from Josh's real ledger,
expected value, break-even sensitivity); register load-bearing assumptions
for nightly re-checking; file same-night ideas as incubating: a different
model re-judges them cold, and only ideas that survive two re-looks or gain
evidence reach Josh's queue. In the dreamer's autonomous mode it may spend a
small budget testing an idea with a probe recipe: dreams with measurements
outrank dreams with speculation. Weekly board minutes publish as a reviewable
draft page in the team space.
