# The Workato KB: RAG++ over all documentation, and the dreaming team

Parent page: The Agentic Workato Harness

**Why this matters, in plain terms.** The agentic tools (AIRO MCP, the CLI, the Dev API) give an agent hands: the ability to build, push, and run things on Workato. But hands without experience means the agent starts every session knowing nothing, re-discovers the platform's traps by breaking things, and claims success without proof. This harness supplies the missing half: a local knowledge base over all Workato documentation, a case base built from the team's own solved bugs, catalogued platform traps that load into every session, and a verification habit that predicts outcomes before acting and checks them against real job traces after. Every lesson learned gets captured and loads into the next session, so the agent arrives smarter each day. Same tools, same model: development compounds instead of resetting.

## What this page covers

The knowledge base architecture (below): the sources, the RAG++ retrieval stack, the fractal memory layer, the dreaming team's science layer, the five learning modalities, the immune system, the warm access layers, and the measured ROI. The two-minute version for sharing lives in the kit repo: `OVERVIEW.md`.

## Sources (9, one index)

| Source | What it holds | Sync |
| --- | --- | --- |
| docs | All Workato product docs as raw Markdown (the site ships a first-party llms.txt with a Markdown twin per page: no scraping) | ETag conditional, nightly |
| changelog | Product changelog posts (WordPress underneath; the archive HTML renders client-side, so counts come from its API category) | RSS incremental |
| blog | The Workato blog and The Connector (they share one WordPress install; both front doors serve the same collection) | API pagination |
| inspiration | Real-world automation pattern posts | API pagination |
| github | The architecture canon: system design primer, software-architecture and system-design resource catalogs | shallow clone + git pull |
| eip | The Enterprise Integration Patterns catalog: every messaging pattern plus the real-world example walk-throughs | link-walk from the index |
| claude | The Claude platform docs (also llms.txt with Markdown twins) | ETag conditional |
| confluence | The BT team's two Confluence spaces (internal + external), **local-only by policy: never committed, backed up, or transmitted** | v2 API pagination + content-hash compare (token in the keychain) |
| attachments | Text-bearing Confluence attachments (PDF, Office formats), extracted to Markdown | per-page scan |

All of it lands in one local store outside the curated knowledge tree (which stays curated), plus a SQLite index with full-text search, dense vector embeddings, entropy scores, and a concept graph.

## The canon expansion (2026-10-10/11)

The corpus outgrew Workato documentation and became a general engineering canon: 24.6k documents and 165k+ chunks, via a scout expansion with a standing beat list:

- **AI engineering**: the major labs' cookbooks and platform docs, the MCP specification, leading AI newsletters, blogs, and research digests.
- **Systems architecture**: the cloud providers' architecture centers, the SRE and distributed-systems canon, database design classics.
- **Integration patterns**: enterprise integration patterns, webhook and event specifications, durable-execution engine docs.
- **Performance engineering**: the USE method and adjacent canon.
- **Team spaces**: three additional internal Confluence spaces ingested (797 pages, quality-scored per page) alongside the original two.

The retrieval layer treats every source identically (one index, one zoom), so an architecture question can pull an SRE chapter, a Workdoc page, and the team's own postmortem in one query. Team content never leaves the machine.

## The retrieval stack (RAG++)

A query runs: full-text search and dense vector search in parallel, then reciprocal-rank fusion, then a local cross-encoder rerank, then two modulation layers, then a confidence gate.

- **Entropy modulation**: every chunk carries an information-density score (bits per word under the corpus's own unigram model). Distinctive content (a formula gotcha, a connector quirk) floats above boilerplate once relevance is established. Proper-noun lists also score high on raw rarity, which is why entropy only modulates rerank-surviving candidates.
- **PMI**: pointwise mutual information between query terms and chunks. It rewards chunks where query terms are rare corpus-wide and dense locally.
- **Confidence gate**: the Shannon entropy of the distribution over final scores. Flat-but-strong is confidence; flat-and-weak triggers one expanded second round automatically, reported in the output.

Chunking is contextual: every chunk carries a header naming source, section, page, and URL, with a local LLM writing a one-sentence situating line per document (incremental, capped per night).

## The fractal memory layer

One factlet schema at every scale: topic (1), file (112), section (~370), chunk (~64K), with parent links and zoom retrieval (`kb zoom "topic"` answers coarse and drills on demand). The projection covers ALL harness memory: the knowledge tree, the claims ledger, every agent SOP, every skill, the instruction tiers, every project's auto-memory, dream reports, and calibration cards. A coverage auditor checks it mechanically: currently 268 files across 12 surfaces, 0 gaps. Files stay the source of truth; the factlet store is a rebuildable projection. A Matryoshka-style funnel adds a coarse page layer (the situating lines, embedded) that boosts chunk search.

**Why fractal memory matters (the case in numbers):** before it, a question paid for a whole file even when one section answered it: 2-10K tokens per memory look-up. The fractal ladder answers at the coarsest level that's correct (~300-500 tokens) and drills only when a decision needs the detail: 10-30x less context per memory question, with provenance (the exact evidence line) one drill away. The single schema at every scale means one tool set serves all of memory: the same zoom works on a transcript line, a knowledge file, a claim, or a docs page, and the coverage auditor makes completeness a checked fact instead of a hope. Brains organize memory this way (the same code recurs at every scale, retrieval zooms by cue); the harness version is queryable at any depth instantly, which is where it beats biology.

## The science layer (the dreaming team)

- **Prediction-error protocol**: open a prediction before consequential actions, close it against the observed outcome; deviations spike to the bus as attention events. Calibration is tracked per agent.
- **Neuromodulation**: one broadcast mood register (arousal / exploration / risk tolerance / verification depth) with 24-hour decay and spike coupling. A P1 finding puts the whole fleet in incident posture automatically.
- **Agent calibration**: per-agent prediction accuracy and an overconfidence gap, weekly cards. The harness's improvement is a curve, not a claim.
- **The dissenter triad**: three critics on three model lineages; critics whose severity calls predict real rejections gain weight; the attack-class list is the dreamers' pre-empt plan (generator and discriminator training each other).
- **The rehearsal cortex**: counterfactual replay. A recipe's historical job fixtures run against a candidate version and diff against history before a change ships.
- **Dream math**: a Bayesian acceptance probability learned from Josh's real accept/reject ledger, expected value with a break-even sensitivity line, and an assumption registry re-checked nightly (an accepted proposal silently outliving its premise is the most dangerous object in a dreaming system).
- **The lateral engine**: a concept co-occurrence graph over the corpus plus Josh's own knowledge tree; PMI-chance-corrected edges; vectorized Adamic-Adar to find concept pairs that share deep structure but are never discussed together. The dreamers' raw feedstock. Sundays: the full cross-domain pass.
- **Criticality meter**: the fleet's information cascades fitted to a power law. Is the network at the critical point (maximum information transmission)? First reading: alpha 1.8, in the zone (small n).
- **The incubation lane**: ideas file as incubating; a DIFFERENT model re-judges them cold each night; promotion requires surviving two re-looks or new evidence. First live result: a cold critic decayed a same-night proposal the original model had filed with enthusiasm. The lane works.
- **Empirical dreams** (autonomous mode): a small budget to test an idea with a probe recipe and report a measurement instead of speculation.
- **Board minutes**: weekly, the dreaming team's advice renders through a sanitizer and publishes as a draft page in this space for review.

The division of labor is mechanical: every agent in the fleet reads its digest and posts an OPINION to the shared bus; only the dreamer files PROPOSALS; only Josh's verdicts in the proposal queue are the training data.

## The five learning modalities (Oct 9)

The harness so far learned by consolidation only. Five new channels: the other ways brains learn.

- **Case-based reasoning** (`kb cases`): the medical model. Every incident/bug/fix becomes a CASE (presentation, diagnosis, treatment, outcome); at decision time, retrieve similar cases FIRST instead of re-deriving from facts. Seeded from the team's closed tickets (2025 onward: thousands of closed bugs pulled via the tracker API, ~500 clinical cases after problem-shape and resolution-evidence filters), the regression canon, and autopsies: a year of the department's solved bugs as clinical experience. The autopsy skill consults the case base before walking any trace.
- **Apprenticeship from the estate** (`kb apprentice`): the org's own recipes are a corpus nobody learns from. Pattern-level mining (error-handling idioms, retry patterns, safe-navigation usage; never business logic verbatim, read-only, sanitized) distilled into the KB: the fleet learns what colleagues already know.
- **The judgment gym** (`kb gym_judgment`): spaced repetition for fleet judgment. Past incidents re-presented as drills, answers graded against known outcomes, failed cases resurface sooner; the diagnosis-accuracy curve is the improvement metric.
- **The curiosity engine** (`kb curiosity`): surprises MINT questions into a standing ledger (why did that prediction deviate? why is this metric anomalous?); the dreamer spends nightly effort on the highest-value open questions; answers bind back as claims. The harness goes from a system that answers to a system that wants to know.
- **The competence map** (`kb competence`): questions route by measured track record per agent/model/domain: a division of labor that emerges from evidence, not assignment.

All five report into a science-state file (read by the ops dashboard) and are liveness-checked nightly.

## The science stack, wave 3 (added 2026-10-11)

Where the integrity layer measures the estate, the third wave of the science stack measures the dreamers themselves, with an instrument per scientific virtue. All of it is standard-library scripts, all of it is ledgered, and several pieces were audited into honesty the same week they shipped (a claimed proof that existed only in console output was caught and required to be recorded; a spore row silently writing into a literal tilde directory was caught by three independent auditors).

- **The null model**: every claimed dream pattern is tested against a permutation null of shuffled sessions. The dreamer's best real pattern sat inside the null, which turned a suspected confabulation class into a measured one.
- **The noise floor**: every "this change made things better" claim is recorded with a robust spread estimate and comes back confirmed, within noise, refuted, or with insufficient data. Retroactive proofs count only when persisted, never when merely printed.
- **Fusion discipline**: a fusion panel may not stack two models of the same family (the failure class that motivated fusion in the first place), enforced by policy, and always advisory: the human can still order any panel.
- **The trigger and the coincidence analyzer**: borrowed from particle physics. A prescaled sampler mines the fleet's logs for event classes with a minimum-bias floor so no stream escapes sampling, and a cadence-aware coincidence analyzer collapses signals that share an upstream cause, so two agents noticing the same outage count as one sighting.
- **The patch genome and the ratchet**: every applied self-improvement is mirrored into a lineage ledger, and a stateless ratchet counts regressions across the real outcome surfaces.
- **The quality archive**: a MAP-Elites archive grades every attempted improvement into cells (failure class, loop, blast radius), with fitness defined as benchmarkable evidence only. Acceptance probability was banned from the fitness function twice, on its way in both times.
- **Change rungs**: an item's dependency degree sets who may change it and how. The first live pass: 141 knowledge items sorted into 103 human-gated, 25 propose, 13 auto-safe.
- **The spore router (shadow only)**: records which model family would have handled each task and how that would have returned, routing nothing yet. The enforcement hooks stay untouched until a week of real returns exists.

## The immune system (Oct 9)

Two structural-safety additions from the adversarial review of the harness itself:

- **The state hasher**: one cryptographic snapshot of the whole workspace state (knowledge-tree git, all memory DBs, the bus, the corpus manifests) with atomic restore to any known-clean hash. Every autonomous mutation now follows snap, mutate, verify, keep-or-restore; a bad mutation path is a revert, not an incident.
- **Antigen drills** (`kb antigen` + the weekly chaos-drill job): proactive immunity. A dedicated canary recipe (dev-only) carries an injectable fault; the weekly job injects a synthetic failure (from the antigen pool: null-payload, schema-drift, timeout-gateway, duplicate-write, spaced-repetition picked), forces the canary to fail with a logged signature, verifies the fleet's detection pipelines would notice, then reverts and proves the clean state. First drill: full cycle proven live (inject, job failed with the signature in the trace, revert, clean run succeeded). The codebase gets vaccinated against failure classes before they manifest for real.

## The five builds (Oct 9, v0.8.0)

- **Chief of staff (`/today`)**: one ranked agenda from every surface (machine heartbeats first: a silent job is the headline; decisions blocking the fleet; calendar; then deep work) with each item PRE-STAGED (draft replies in Josh's voice, first commands ready). The loadout loads context; /today prioritizes the day.
- **The benchmark** (`kb benchmark`): the "best harness" claim turned into a measurement. Same tasks, two arms (harness vs a truly-isolated bare agent via config-dir override), scored accuracy-first (per-task graded checks), turns second, cost third; latency demoted (bare wins it by construction). First scored result: on trivial docs questions the arms TIE on quality and the harness costs ~6x: the honest finding; the differentiating evidence comes from diagnosis/UAT/manifest tasks. Weekly auto-run feeds a trend ledger.

## The bench, matured (2026-10-12)

Four battery generations later, the benchmark answers the question that
matters: where does the harness actually earn its overhead?

- **The hallucination discriminator.** On grounded platform questions the
  bare model's failures are never random. It gets structure and design
  right, and confabulates exactly the domain facts that price the solution:
  a billing model that does not exist, stated confidently, twice, in
  different words, mispricing a real architecture by five to ten times. The
  harness's cited answers were correct on every run of every battery.
- **Cost inverts at depth.** On trivial lookups the harness pays more
  context, and the honest framing correction (from the human reviewing the
  data) is that one-shot numbers overstate it: a live session loads its
  context once and amortizes it across the day. On deep retrieval the
  relationship flips: the bare model crawled the web for one to two minutes
  and half a million tokens to find a changelog fact the KB answered in
  under thirty seconds with a citation.
- **The retrieval map.** Measured in-bench across 27 queries: search
  median 13.6 seconds, full-document read 0.11 seconds. A few search
  roundtrips, then near-free reads.

The claim this supports is specific and quotable: a bare frontier model is
a brilliant generalist with unverified memory; the harness is the
difference between plausible and correct on the domain where the team's
work actually lives.
- **Learned model routing**: which model's opinions get accepted is MEASURED (via attribution on every proposal) and future lens assignment routes by acceptance-at-lowest-cost, explore-exploit kept live.
- **The skill forge**: the dreamer doesn't propose "there should be a skill"; it drafts the SKILL.md into staging, the forge validates it (description-as-trigger, length, TODOs), and Josh's accept installs it. The loop from idea to working artifact, reviewed.
- **The typed bus**: finding/opinion/vote schema so corroboration (1 observation / 2 pattern / 3+ act) is arithmetic, not prose-reading.

## How agents reach it (three warm layers)

- **`kb` CLI**: daemon-first. A resident daemon holds the models warm; search ~2s, read 0.16s, zoom 0.11s; transparent cold fallback (~10s) if the daemon is down.
- **The `workato-kb` MCP server**: resident per session, model warm from the first query (0.16-0.18s/query vs ~9s cold); registered for every new session.
- **The `workato-kb` skill + `/kb`**: the method (search, refine twice max, read, cite) and the human-facing command.

The standing rule: platform questions get answered from the KB before guessing or asking Josh, at phase boundaries and on uncertainty, not on every tool call. Confluence content never leaves the machine.

## The ROI study (the proof the anecdote needed)

All tickets assigned to Josh and resolved since May (n=142), stratified by creation era, backlog-hygiene closures (>60d) separated:

| Cohort | n | median created-to-resolved | same/next-day |
| --- | --- | --- | --- |
| Pre-harness (May-Aug) | 102 | 12.8 days | 11% |
| Harness era (Sept+) | 12 | **0.7 days** | **67%** |

18x cycle-time reduction on fresh work; 6x same-day rate; 28 stale backlog closures as a bonus. Re-runs monthly from one query: the claim is reproducible, not anecdotal.

The dollar side got its own calibration story (2026-10-14), and the story is the point. The cost basis was corrected three times in two days: list prices nobody pays (17 to 33 times too high for the flagship model), then a dashboard estimator 2.7 to 3.3 times hot on identical token counts, then the gateway's actual spend page as the canonical basis. On the settled basis, year-to-date harness spend is about $13.6k, and value-based ROI against it runs 9.6x on shipped work and 43.9x on resolved work. The precision is modest; the practice is the claim: every dollar figure published from this harness has survived a reconciliation or is labeled as an estimate, and the corrections are kept in the record instead of quietly overwritten.

## The nightly machine

21:37 sync (all sources, contextualize, index, PMI, entropy, lateral, entropy report) -> 22:07 per-agent digests -> the fleet reads and posts opinions -> 23:43 the dreamer synthesizes (board lenses, cross-model, lateral feedstock, incubation re-looks) -> 00:37 project dreamer -> 00:15 regression gym (now incl. science-layer liveness) -> 04:43 frontier nightly (twin, calibration, radar, skill fitness; zero-LLM) -> 07:13 morning brief. Mondays: estate architect + board minutes.
