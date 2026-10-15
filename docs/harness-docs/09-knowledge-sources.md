# The knowledge sources: what the harness knows, and where it lives

Parent page: The Agentic Workato Harness

Everything the harness knows lives in two connected layers: a large
retrieval corpus (everything worth looking up, indexed and searchable) and
a small curated knowledge tree (everything worth remembering, hand-shaped
and versioned). This page inventories both, with the live counts, and
explains what the combination buys. Numbers are as of 2026-10-15 and are
re-derivable from the index in one query; the nightly sync keeps them
moving.

## The one-sentence case

A model with the whole corpus behind it answers from real documentation
with a citation; a model without it answers from memory, confidently, and
on platform specifics it confabulates the details that price a design. The
corpus is why the harness's answers are correct on grounded questions, and
the knowledge tree is why they get better every week: every session's hard-
won lesson lands in one of these layers and loads into every session after
it.

## The corpus at a glance

**104,722 documents. 382,773 chunks. 40 indexed sources.** One store, one
SQLite index over all of it: full-text search, dense vectors, entropy
scores, and a concept graph. A query does not need to know which source
has the answer, and an architecture question can pull a Workato manual, a
team postmortem, and a distributed-systems chapter in one retrieval.

Three kinds of knowledge live here:

| Kind | What it is | Sources | Docs | Chunks |
|---|---|---|---|---|
| Product and platform | The manuals of the systems the fleet builds on | 6 indexed, 1 syncing | 6,012 | 35,630 |
| Engineering canon | The public science: architecture, integration, AI, data engineering | 24 | 87,542 | 287,000 |
| Team and internal | The org's own knowledge, local-only by policy | 10 | 11,168 | 60,143 |

## Product and platform sources

| Source | What it holds | Docs | Chunks |
|---|---|---|---|
| docs | All Workato product docs as raw Markdown (the site ships a first-party Markdown twin: no scraping) | 4,395 | 22,596 |
| changelog | Product changelog posts | 257 | 2,611 |
| blog | The Workato blog | 1,205 | 9,812 |
| inspiration | Real-world automation pattern posts | 88 | 343 |
| connector | Workato customer-story integration posts | 250 | pending |
| hubs | Topic-hub pattern pages | 52 | 104 |
| trigger | Trigger.dev docs (durable execution) | 15 | 164 |

## The engineering canon

The corpus outgrew Workato documentation early and became a general
engineering library, expanded by a standing beat list (the librarian
procures; the nightly sync ingests):

| Source | What it holds | Docs | Chunks |
|---|---|---|---|
| github | The architecture canon: system design, software architecture, engineering resource catalogs | 16,450 | 48,673 |
| pwc | The PwC method corpus: professional practice knowledge, the largest single source | 31,733 | 37,489 |
| langchain-hub | LangChain reference and patterns | 9,961 | 27,257 |
| snowflake | Snowflake product docs | 8,922 | 57,645 |
| webcrawl | Curated web documentation crawls | 3,529 | 30,569 |
| terraform-registry | Terraform provider docs | 5,560 | 5,562 |
| rss | Research paper digests (AI/ML) | 1,328 | 6,927 |
| n8n | n8n workflow platform docs | 1,366 | 9,034 |
| dbt | dbt documentation | 1,309 | 8,523 |
| Hugging Face docs | transformers, diffusers, hub, PEFT, datasets, accelerate | 1,604 | 15,801 |
| claude | The Claude platform docs | 638 | 13,872 |
| camel | Apache Camel component docs | 813 | 4,780 |
| temporal | Temporal docs (durable execution) | 788 | 6,415 |
| mcp | The Model Context Protocol specification and docs | 358 | 4,122 |
| prefect | Prefect docs | 331 | 3,938 |
| apis-guru | The API description catalog | 2,519 | 3,822 |
| eip | Enterprise Integration Patterns, with the worked examples | 103 | 725 |
| restate | Restate docs (durable execution) | 221 | 1,837 |
| figshare | misc research deposits | 9 | 9 |

## Team and internal sources (local-only by policy)

These never leave the machine: not committed to git, not in backups, not
transmitted. They are also the reason a fleet answer can cite the team's
own postmortem next to the vendor manual.

| Source | What it holds | Docs | Chunks |
|---|---|---|---|
| workday | Workday platform docs and WQL references | 2,676 | 23,005 |
| slack | Slack platform docs (API, Block Kit) | 3,275 | 15,699 |
| confluence (5 team spaces) | The BT team's internal and external spaces, quality-scored per page | 4,184 | 14,012 |
| atlassian | Atlassian REST API references | 652 | 5,485 |
| harness | The harness's own artifacts, mirrored in: every skill, every agent SOP, the knowledge files | 377 | 1,894 |
| confluence attachments | Text-bearing page attachments, extracted | 4 | 48 |
| jira | Tracker-derived case material | queued | pending |

The five team spaces total 4,184 documents and 14,012 chunks, and the
retrieval layer treats them identically to the public canon: one index,
one zoom, provenance on every hit.

## The fractal memory layer

On top of the chunk index sits one self-similar schema at every scale, so
retrieval can zoom from a topic to a file to a section to the exact chunk,
paying only for the level that answers the question. Live counts:

| Level | Count | What a hit at this level gives you |
|---|---|---|
| topic | 91 | the map of a whole subject area |
| file | 105,150 | a document with its situating line |
| section | 288,149 | the passage that carries the answer |
| chunk | 382,991 | the exact evidence text, with provenance |

The projection covers the corpus and all harness memory alike: the
knowledge tree, the claims ledger, every agent SOP, every skill, the
instruction tiers, project memories, dream reports, calibration cards.
The harness-memory projection's last coverage audit: 268 files across 12
surfaces, zero gaps. Files stay the source of truth; the factlet store is
a rebuildable projection.

**Why this matters in numbers:** before it, a question paid for a whole
file even when one section answered it (2 to 10k tokens per lookup). The
ladder answers at the coarsest correct level (300 to 500 tokens) and
drills only when a decision needs detail: 10 to 30x less context per
memory question. Measured retrieval behavior in the benchmark: a few
search roundtrips at a median of 13.6 seconds, then near-free full-document
reads (0.11 seconds).

## The curated knowledge tree (the harness's own memory)

The corpus is everything worth looking up. The knowledge tree is the much
smaller set of things worth REMEMBERING: git-versioned, hand-shaped,
re-verified against live platform behavior by the curator agent, and
routed by a one-line-per-file index that every session reads first.

| Directory | Files | What lives there |
|---|---|---|
| domains/ | 34 | cross-project platform knowledge |
| projects/ | 111 | per-project state for the next session on that project |
| scripts/ | 128 | the stdlib-only tooling fleet |
| cortex/ | 105 | the cortex's investigations and dispatch log |
| dreams/ | 137 | dream reports, proposal queue, trust-ladder config |
| garden-reports/ | 114 | every agent run's report |
| people/ | 56 | people files feeding the writing voice |
| skills-telemetry/ | 14 | per-skill usage and fitness |
| config/ | 14 | fleet job definitions and the model routing table |
| instruction-patches/ | 10 | self-learning corrections to instruction files |
| library/ | 3 | the librarian's positions and consolidations |
| claims/, integrity/, predictions/, coverage/, sagas/, policies/, twin/, now/ | small | the integrity and governance ledgers |

The 34 domain files are the tree's top layer, and they read like a map of
what the fleet has paid to learn: the Workato and Workday platform
behavior files, the AIRO MCP trap-adjacent operations files, the harness's
own benchmarking, docs, dream-loop, and science-stack files, the model
gateway playbook, the red-team gate, the writing voice corpus, and the
brain architecture rulebook.

The scope test keeps the tree honest: something that makes any project
better goes to domains/, something that makes one project's next session
better goes to projects/, a procedure becomes a skill, and the full
canonical story lives in a project repo the knowledge file points to.
Every true build session deposits its durable lessons before it ends;
question-and-answer sessions save nothing.

## How it gets used

The nightly machine runs on these layers in order: the 21:37 sync ingests
and re-indexes every source, contextualizes new documents, and rebuilds
the concept graph; the 22:07 digest writes each agent a brief on what
moved in its domain; the agents read their digests, post opinions to the
gossip bus, and file findings; the dreamer reads the whole night last.
During the day, three warm access layers serve queries: the kb CLI
(daemon-first, about 2 seconds a search), the resident MCP server (model
warm from the first query, 0.16 to 0.18 seconds), and the /kb command for
the human. The standing rule: platform questions get answered from the KB
before guessing or asking, at phase boundaries and on uncertainty. The
autopsy skill consults the case base before walking any trace; the
forensics scripts read the same ledgers they write; the A/B benchmark's
differentiating evidence (the bare model's confabulated billing facts)
was scored directly against this corpus.

Verdict: the corpus is what makes the fleet's answers citable, the
fractal layer is what makes them cheap, and the knowledge tree is what
makes them compound. Take away any one and the harness is either slow,
expensive, or amnesiac; together they are why a session on Monday starts
knowing what Friday paid for.

## Related pages

1. [The Workato KB: RAG++ over all documentation, and the dreaming team]
2. [Memory and the knowledge base architecture]
