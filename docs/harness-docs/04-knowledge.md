# Memory and the knowledge base architecture

Parent page: The Agentic Workato Harness

The knowledge system is the harness's long-term memory: a git-versioned
tree of knowledge files, a structured claim ledger, telemetry on what is
actually used, and a curator agent with both a content mandate and an
architecture mandate.

## The knowledge tree

Everything durable lives in one git repo. `INDEX.md` is the router: one
line per knowledge file, and nothing else. A session reads the index,
loads only what is relevant, and updates the index line whenever it
updates a file.

- **`domains/`**: cross-project knowledge (platform behavior, connection
  standards, the writing voice, the brain architecture rulebook).
- **`projects/`**: per-project state that only that project's next session
  needs.
- **`claims/`**: the structured claim ledger (below).
- **`scripts/`**: stdlib-only tooling (cost heatmap, dedup shortlister,
  harvest-rate gauge, docs crawler, dream miner, gossip reader, backup).
- **`dreams/`**: dream reports, the proposal queue, the trust-ladder
  config, and the gossip bus.
- **`garden-reports/`**: dated reports from every agent run, plus the
  proposal-outcomes log the gardener grades itself against.

The scope test decides where knowledge lives: something that makes any
project better goes to `domains/`; something that makes this project's
next session better goes to `projects/`; a procedure becomes a skill; the
full canonical story lives in a project repo and the knowledge file points
to it. An auto-save rule makes every true build session deposit its
durable lessons before it ends; question-and-answer sessions save nothing.

## The claim ledger

Durable knowledge is stored as structured claims, one JSON line each:
subject, claim, evidence, confidence, asserted date, last-verified date,
status. Contradictions are mechanically detectable: two active claims on
the same subject that conflict. Claims are superseded, never edited, so
the history of what the team believed and when is preserved.

The freshness mechanism is opportunistic, not synthetic: the mods stamp
claims as real work exercises them. A push that succeeded while a recipe
was running, a CLI start that was read back and confirmed: each becomes a
verification observation, and the gardener rolls observations into
last-verified dates. A claim that keeps getting refuted gets superseded.
Synthetic probe harnesses are deliberately parked; verification as a side
effect of real work covers most of the value at none of the cost.

## Telemetry: which knowledge is load-bearing

brain-guard logs every skill load, knowledge read, and knowledge write to
a usage ledger. The gardener reads it and finds knowledge with zero loads
whose subject has moved on (candidate tombstones) and heavily-loaded
knowledge (candidate hardening: verify its claims live). The same ledger
feeds MCP cost and failure reporting, so context economics is measured,
not guessed.

## The gardener's two mandates

**Content curation** keeps the knowledge true: index-to-file inventory in
both directions, conflict detection (newer and more specific wins),
duplication adjudication, temporal rot (relative dates, finished-work
memories, "current" claims weeks old), and transcript mining for lessons
that never got recorded. Every proposal cites its evidence.

**Architecture review** keeps the knowledge shaped right, against a
written rulebook: file size budgets per type, a hub-and-reference
modularization pattern for files that grow past their budget, thin-index
discipline, skill and agent description quality (a description that does
not say when to use the thing will never route), and content living in
the wrong layer (facts in skills, procedures in knowledge files, project
state in memory). Modularization proposals arrive as split maps: what
stays in the hub, what moves to the reference file, what the new file
names are, with the index lines updated in the same commit.

All proposals land as commits on a `gardener/*` branch, never on main.
Review is `git diff main gardener/*`; acceptance is a merge.

Verdict: memory that is not audited rots silently until it misleads
someone at a critical moment; this architecture audits itself on a
schedule and treats structure as a first-class property, not an accident.
