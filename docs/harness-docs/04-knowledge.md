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
- **`integrity/`**: claim receipts and the nightly reconciliation reports.
- **`predictions/`**: the calibration ledger (falsifiable predictions and
  their Brier resolutions).
- **`coverage/`**: denominator declarations ("green" = coverage, not exit code).
- **`sagas/`**: hash-chained, resumable mission journals.
- **`policies/`**: standing orders (human-approved decision rules) and the
  regret ledger for deferred decisions.
- **`skills-telemetry/`**: per-skill usage and fitness reports.
- **`twin/`**: the offline snapshot of the whole estate (recipes,
  connections, schedulers).
- **`instruction-patches/`**: self-learning corrections to instruction
  files, mined nightly by a zero-LLM script.
- **`now/`**: the decision inbox and the day's ranked agenda.

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

## The integrity layer (added 2026-10-11)

Three mechanisms now attack "the estate that lies to itself" at the source
rather than by spot-check:

- **Proof-carrying claims.** A claim of action ("deployed", "fixed",
  "verified") carries a re-fetchable proof artifact: a job ID with a
  row-count delta, a file hash, an API response digest, or a tracker
  transition with a postcondition result. Claims without proofs are tier
  "asserted" and rendered second-class everywhere; the nightly reconciler
  flags any asserted claim older than a day.
- **The reconciler.** A nightly diff of internal ledgers (claims, the
  build ledger) against live external state (tracker statuses, the
  platform API), flagging orphans (internal entry, no external proof) and
  ghosts (external state, no internal record). Its first live run found
  fifteen legacy claims without proof, the class this exists to kill.
- **The denominator oracle.** Every job declares its expected population
  (computed independently from the source), and "green" requires coverage
  at or above a threshold, not exit code zero. Coverage numbers are
  ledgered per run, so under-collection is arithmetic, not a hunch.

## The calibration ledger (added 2026-10-11)

Agents file falsifiable predictions with a confidence and a resolution
date ("this recipe fails again within 7 days"; "this promotion passes
first try"). A nightly resolver grades every due prediction and computes a
Brier score per agent. Calibration becomes measured trust: the scores feed
the trust ladder, adversarial-review fast-paths, and (planned) autonomy
sizing. The first backfill mined twenty real predictions out of the
watchdog, dream, and claim records; the first table already separates
well-calibrated reporters from the rest.

The precursor radar rides the
same ledger: leading indicators over the estate's health history fire
pre-failure predictions, so the radar's hit rate is itself scored.

## The estate twin (added 2026-10-11)

A nightly zero-LLM snapshot of the whole estate (every recipe, connection,
and scheduler) into an offline, queryable twin. Questions like "what
depends on this connection" are answered offline in a second; every answer
stamps its snapshot age and refuses when older than a day. The twin is
also the rehearsal surface: fault scenarios are injected into copies of it,
and detection latency is measured against it (schedules page).

## Telemetry: which knowledge is load-bearing

brain-guard logs every skill load, knowledge read, and knowledge write to
a usage ledger. The gardener reads it and finds knowledge with zero loads
whose subject has moved on (candidate tombstones) and heavily-loaded
knowledge (candidate hardening: verify its claims live). The same ledger
feeds MCP cost and failure reporting, so context economics is measured,
not guessed.

The Skill League (added 2026-10-11) extends this to the skill catalogue
itself: every skill invocation is logged with an outcome, backfilled from
session transcripts, and rolled into a fitness table (usage, applied-ratio,
trend). Bottom performers become reversible quarantine candidates and top
performers get cited in the morning loadout: the catalogue is a managed
portfolio instead of a junk drawer.

## The context economy, measured (added 2026-10-12)

The same discipline turned on the harness's own running cost. A per-layer
measurement of a cold session start found the model servers alone carried
81% of the always-on context bill, with two of them (a development and a
production instance of the same platform) accounting for a third of the
total by themselves. The cuts that followed, each verified by re-measuring
the whole configuration rather than trusting additive estimates:

- **Server tiering.** A small core stays in every session (the platform dev
  server, the knowledge base, the brain, the tracker, web search); the heavy
  and production servers now attach on demand with a one-flag include file.
  Fleet jobs were checked first and read production through the CLI
  keychain, not the server, so nothing scheduled needed touching.
- **The context diet.** The instruction files became pointers to doctrine
  that lives in skills and knowledge files (rulings and dates up front,
  reasoning one hop away), thirteen skills were parked, the memory index was
  halved to a thin pointer list, and the session-start health check became
  one line.
- **The number.** Cold start fell from 128k to 58k input tokens, about 55%,
  and live sessions measured roughly half the cost per turn at equal work
  after the change. One measurement lesson travels with it: per-server
  additive estimates overpredicted the savings; only whole-configuration
  runs tell the truth.

The A/B bench behind the numbers runs the same tasks through the full
harness and a stripped bare agent in isolated scratch directories and scores
both. Its most useful finding is not about cost: on grounded platform
questions, the bare model's failure class is always the same, confident and
fabricated domain facts (it priced an architecture design on a billing model
that does not exist, twice, in different words). The harness's knowledge
layer is what stands between a plausible answer and a correct one, and on
deep retrieval tasks the cost relationship inverts: the bare model crawls
the web for minutes where a cited local answer takes seconds.

**The waste audit (2026-10-13/14).** The next measurement went after failure
instead of spend, and the week's number was 3,175 failed tool calls across
547 sessions. The taxonomy mattered more than the total: permission denials
that each burn a full turn at full context footprint, platform-builder
schema errors committed at the highest average context of any tool in the
fleet, and blind retries, while consulting the knowledge base after a
failure happened 0.25% of the time. Four fixes shipped the same week, all
verified end to end against fresh probes: the error-guide hook (found built
but never wired) now registered and extended to inject the exact reference
call a schema error asks for; a pre-flight guard that denies malformed
tracker comments before they reach the API (a third of comment writes had
been failing); writer-class fleet jobs running with permissions resolved,
which deleted the denial class outright; and the CLI's error classes
documented as playbook traps. Measured forward savings at calibrated rates
run about a hundred dollars a week; the bigger wins are the roughly 2,500
wasted turns a week that stop happening and the failure-recovery turns no
longer paid at half a million tokens of context each.

**One price book (settled 2026-10-13).** The question "what does a session
actually cost" survived three answers. The engine's built-in ledger turned
out to apply list rates nobody pays (17 to 33 times too high for the
flagship model), a team dashboard estimator ran 2.7 to 3.3 times hot on the
same token counts, and the gateway's own spend page is the canonical basis.
The durable rules: compare models in tokens, quote dollars only from the
gateway's card, and treat any cost number that has not survived a
reconciliation as an estimate.

**The efficiency dashboard (2026-10-14).** A daily zero-LLM job renders the
whole bill as one self-contained page: burn by day and token class, failure
rates with hooked classes split from unhooked so the green line's fall is
checkable, tokens per shipped closeout and per story point, and a session
catalog that classifies every session the harness runs. The first week's
catalog: platform builds carry 75% of all burn, the harness's own
self-improvement 25%, and the fleet's routine analysis pulse costs about
2.4 million tokens per session. Where a chart needs projection (days before
the registry existed), the projected segment is dotted and flagged; where a
denominator changed meaning, both lines are shown so nobody oversells the
drop.

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
