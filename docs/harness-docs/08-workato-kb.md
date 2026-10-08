# The Workato KB: RAG++ over all documentation, and the dreaming team

Parent page: The Agentic Workato Harness

The KB is the harness's deep knowledge of the Workato platform — and of
software architecture itself — as a local, nightly-synced RAG++ corpus that
every agent queries before guessing, and that the dreaming team dreams on.

## Nine sources, one index

| Source | What it holds | Sync |
|---|---|---|
| docs | All Workato product docs as raw Markdown (the site ships a first-party llms.txt with a Markdown twin per page — no scraping) | ETag conditional, nightly |
| changelog | Product changelog posts (the underlying CMS is WordPress; the archive HTML renders client-side, so the count comes from its API category) | RSS incremental |
| blog | The Workato blog and The Connector (they share one WordPress install; both front doors serve the same collection) | API pagination |
| inspiration | Real-world automation pattern posts | API pagination |
| github | The architecture canon: system design primer, software-architecture and system-design resource catalogs | shallow clone + git pull |
| eip | The Enterprise Integration Patterns catalog: every messaging pattern plus the real-world example walk-throughs | link-walk from the index |
| claude | The Claude platform docs (also llms.txt with Markdown twins) | ETag conditional |
| confluence | The BT team's two Confluence spaces (internal + external) — **local-only by policy: never committed, backed up, or transmitted** | v2 API pagination + content-hash compare (token lives in the keychain) |
| attachments | Text-bearing Confluence attachments (PDF, Office formats), extracted to Markdown | per-page scan |

All of it lands in one local store outside the curated knowledge tree (which
stays curated), plus a SQLite index with full-text search, dense vector
embeddings, and a concept graph.

## The retrieval stack (RAG++)

A query runs: full-text search and dense vector search in parallel →
reciprocal-rank fusion → a local cross-encoder rerank → two modulation
layers → a confidence gate.

- **Entropy modulation**: every chunk carries an information-density score
  (bits per word under the corpus's own unigram model). Distinctive content —
  a formula gotcha, a connector quirk — floats above boilerplate once
  relevance is established. Proper-noun lists also score high on raw rarity,
  which is why entropy only modulates rerank-surviving candidates.
- **PMI**: pointwise mutual information between query terms and chunks —
  rewards chunks where query terms are rare corpus-wide and dense locally.
- **Confidence gate**: the Shannon entropy of the distribution over final
  scores. Flat-but-strong is confidence; flat-and-weak triggers one expanded
  second round automatically, reported in the output.

Chunking is contextual: every chunk carries a header naming source, section,
page, and URL, with a local LLM writing a one-sentence situating line per
document (incremental, capped per night).

## How agents reach it

- **`kb "query"`** — a CLI shim that works from any directory; the
  zero-friction path. Subcommands: read a full document, the lateral engine,
  the dream math, the entropy report.
- **The `workato-kb` skill** — the loop as method: search, refine at most
  twice, read, cite the canonical URL; fetch the live page as tiebreaker when
  staleness is suspected.
- **`/kb`** — the human-facing slash command; decision-ready answers with
  citations.
- **Nightly digests** — a per-agent brief of what changed (change surface +
  live lens queries), written after the sync so every agent opens its night
  with what moved in the platform.

The standing rule: Workato platform questions get answered from the KB before
guessing or asking Josh — at phase boundaries and on uncertainty, not on
every tool call. Confluence content never leaves the machine.

## The dreaming team

The dreamer is not one agent with a poetic name; it is a board.

- **The Board**: nine professional lenses — doctor, lawyer, artist, musician,
  CEO, engineer, accountant, product manager, CTO — rotating two or three per
  night, full tour weekly. Each argues from its craft's instincts.
- **Cross-model diversity**: the lenses run on three different model
  lineages through the AI gateway — a frontier model, and two fast models
  with different training histories. The frontier model is cost-governed:
  one rotating seat per night, the full board on Sundays. Different priors,
  not different prompts on one prior.
- **The lateral engine**: network science applied to the corpus. Build a
  concept co-occurrence graph (concepts = bursty technical terms only —
  words that appear in concentrations, not spread thin; prose filler fails
  this test), keep only edges whose co-occurrence beats chance (positive
  PMI), then find concept pairs that share deep structural neighborhoods
  (high Adamic-Adar) but never appear in the same documents. Those pairs are
  "seemingly unrelated concepts that are secretly related" — the dreamer's
  raw feedstock. On Sundays the graph spans the product docs AND Josh's own
  knowledge tree and project memories, so the hidden pairs can connect the
  platform to the practice.
- **Math self-evaluation**: every proposal carries a math block — a Bayesian
  posterior of acceptance probability learned from Josh's real
  accept/reject ledger, expected value with a break-even sensitivity line,
  and registered assumptions that get re-checked against the KB nightly
  (assumption regression: an accepted proposal silently outliving its
  premise is the most dangerous object in a dreaming system).
- **The incubation lane**: the sharpest critique of automated dreaming is
  that same-night proposals are the least-stable version of an idea — formed
  inside the context that generated it, never re-looked at. So ideas file as
  incubating; each night a DIFFERENT model re-judges them cold; promotion
  requires surviving two re-looks or new evidence. Decay ideas are dropped
  and the drop rate is reported — it is the number that says whether the
  filter earns its latency.
- **Empirical dreams** (in the dreamer's autonomous mode): a small budget to
  test an idea with a probe recipe and report a measurement instead of
  speculation. Dreams with data outrank dreams without; null results are
  results.
- **Board minutes**: weekly, the dreaming team's advice renders through a
  sanitizer and publishes as a draft page in the team's Confluence space for
  review — the ROI made visible without anyone building a deck.

The division of labor is mechanical: every agent in the fleet reads its
digest and posts an OPINION to the shared bus; only the dreamer files
PROPOSALS; only Josh's verdicts in the proposal queue are the training data.
