# workato-kb

Local RAG++ knowledge base over all Workato documentation and the BT team's
Confluence — grown (2026-10-10/11) into a general engineering canon: AI
engineering (the major AI labs' cookbooks and docs, MCP specification,
leading AI newsletters and blogs), systems architecture (cloud providers'
architecture centers, SRE and distributed-systems canon, database design
classics), integration patterns (enterprise integration patterns, webhook
and event specs), durable execution engines, and performance engineering —
24.6k documents and 165k+ chunks with the team's Confluence aboard — plus
the dreaming-team science layer: fractal memory, the
prediction-error protocol, neuromodulation, agent calibration, the dissenter
triad, and the rehearsal cortex. The agent's daily companion for planning,
scoping, building, and testing — and the corpus the dreamers dream on.

Built 2026-10-08 for Josh's agentic harness (v0.7.3). Companion skill:
`workato-kb`; human slash command: `/kb`. Adoption package: the
`workato-agentic-kit` repo carries this code + the harness scripts + skills +
authoring rules.

**Why this matters, in plain terms.** The agentic tools — AIRO MCP, the CLI, the Dev API — give an agent hands: the ability to build, push, and run things on Workato. But hands without experience means the agent starts every session knowing nothing, re-discovers the platform's traps by breaking things, and claims success without proof. This harness supplies the missing half: a local knowledge base over all Workato documentation, a case base built from the team's own solved bugs, catalogued platform traps that load into every session, and a verification habit that predicts outcomes before acting and checks them against real job traces after. Every lesson learned gets captured and loads into the next session, so the agent arrives smarter each day. Same tools, same model — development compounds instead of resetting.

## What this page covers

The knowledge base architecture (below): nine sources, the RAG++ retrieval stack, the fractal memory layer, the dreaming team's science layer, the five learning modalities, the immune system, the warm access layers, and the measured ROI. The two-minute version for sharing lives in the kit repo: `OVERVIEW.md`.

## Sources (9, one index)

| Source | What it holds | Sync mechanism |
|---|---|---|
| `docs` | docs.workato.com (4,396 pages via first-party `llms.txt`, raw-Markdown twins) | ETag conditional GET |
| `changelog` | product-hub changelog (WordPress category "What's New") | RSS + wp-json |
| `blog` | Workato blog + The Connector (one WP install) | wp-json pagination |
| `inspiration` | Automation Inspiration posts | wp-json pagination |
| `github` | system-design-primer, awesome-software-architecture, awesome-system-design-resources | shallow clone + git pull |
| `eip` | enterpriseintegrationpatterns.com (patterns + ramblings) | link-walk, ETag |
| `claude` | Claude platform docs (llms.txt Markdown twins) | ETag conditional |
| `confluence` | BT spaces extbt + intbt — **LOCAL-ONLY: never committed, backed up, or transmitted** | v2 API pagination + content-hash compare |
| `attachments` | text-bearing Confluence attachments (PDF/Office) → markdown | per-page scan |

Data root: `~/.claude/workato-kb/` (gitignored everywhere) — `corpus/`,
`manifest/*.jsonl`, `index/kb.db` (FTS5 + sqlite-vec + entropy + coarse layers),
`index/fractal.db` (factlets), `diffs/` nightly change reports.

## The retrieval stack (RAG++)

BM25 (FTS5) + dense (bge-base via sqlite-vec) → RRF fusion → cross-encoder
rerank (bge-reranker-base) → **entropy modulation** (information-density
bits/word lifts distinctive chunks among relevant ones) → **PMI** (query-term
concentration, log2 P(t|chunk)/P(t|corpus)) → **confidence gate** (Shannon
entropy of the final-score distribution; weak+flat triggers one expanded
second round). Chunking is contextual: a deterministic header
`[source|section|page|url]` plus a local-LLM situating line per document.

## The fractal memory layer

One factlet schema at every scale — topic (1) → file (112) → section (~370)
→ chunk (~64K) — with parent links and zoom retrieval
(`kb zoom "topic"` answers coarse and drills on demand). The projection
covers ALL harness memory: knowledge tree, claims ledger, agent SOPs, skills,
CLAUDE.md tiers, every project's auto-memory, dream reports, calibration
cards. `kb fractal coverage` audits it (currently 268/268 files, 0 gaps,
AIRTIGHT). Files stay the source of truth; the factlet store is a
rebuildable projection (incremental, per-source sha freshness). MRL-style
funnel: doc-context embeddings as the coarse page layer boost chunk search.

**Why fractal memory matters (the case in numbers):** before it, a question
paid for a whole file even when one section answered it — 2-10K tokens per
memory look-up. The fractal ladder answers at the coarsest level that's
correct (~300-500 tokens) and drills only when a decision needs the detail:
10-30x less context per memory question, with provenance (the exact evidence
line) one drill away. The single schema at every scale means one tool set
serves all of memory — the same zoom works on a transcript line, a knowledge
file, a claim, or a docs page — and the coverage auditor makes completeness
a checked fact instead of a hope. Brains organize memory this way (the same
code recurs at every scale, retrieval zooms by cue); the harness version is
queryable at any depth instantly, which is where it beats biology.

## The science layer (the dreaming team)

- **Prediction-error protocol** (`predict.py`): open a prediction before
  consequential actions, close against reality; deviations spike to the bus.
- **Neuromodulation** (`mood.py`): one broadcast state (arousal/exploration/
  risk/verification), 24h decay, spike coupling — a P1 puts the fleet in
  incident posture.
- **Calibration** (`calibration.py`): per-agent prediction accuracy +
  overconfidence gap; weekly cards. The harness's improvement is a curve.
- **Dissenter triad** (`dissent_ledger.py`): three critics on three model
  lineages; critics whose severity predicts real rejections gain weight;
  `attack-classes` is the dreamer's pre-empt list — GAN dynamics for
  proposals.
- **Rehearsal cortex** (`rehearsal.py`): counterfactual replay — a recipe's
  historical job fixtures, run against a candidate version, diffed against
  history.
- **Dream math** (`dream_math.py`): Beta posterior P(accept) from Josh's real
  ledger (logistic fit at n≥20), EV with break-even sensitivity, assumption
  registry re-checked nightly.
- **Lateral engine** (`lateral.py`): concept co-occurrence graph, PMI-
  chance-corrected edges, vectorized Adamic-Adar — hidden pairs across docs ×
  practice; the dreamers' feedstock.
- **Criticality** (`criticality.py`): fleet cascade power-law fit — is the
  network's information flow at the critical point? (alpha 1.8, small-n)
- **Contextualize** (`contextualize.py`): local LLM (ollama qwen2.5:3b)
  writes per-doc situating lines, incremental 400/night.
- **Board minutes** (`board_minutes.py`): weekly dreaming-team advice →
  sanitized draft page in the team Confluence (Mondays 06:27).

## Performance (measured)

| Path | Latency |
|---|---|
| `kb` CLI via daemon (warm) | search ~2s, read 0.16s, zoom 0.11s |
| cold fallback (daemon down) | ~9-10s (model load) |
| MCP server (resident, warm) | 0.16-0.18s per query |

Three warmth layers: the **kb-daemon** (launchd KeepAlive, boots at login)
serves the CLI; the **KB MCP server** (registered user-scope, resident per
session) serves MCP clients; the process-wide model cache serves any
long-lived process. Local everything: $0 per query.

## CLI

```bash
kb "query"                    # search (daemon-first, cold fallback)
kb read <id> | kb read --url  # full document + citation
kb zoom "topic"               # fractal coarse-first retrieval
kb fractal coverage           # the airtight check (268 files, 0 gaps)
kb funnel search "q"          # MRL coarse-fine retrieval
kb criticality                # fleet cascade power-law fit
kb entropy score | kb pmi build | kb lateral top
kb sync                       # full nightly pipeline (all steps)
```

## Nightly machine

21:37 sync (all sources → contextualize → index → pmi → entropy → lateral →
entropy report) → 22:07 per-agent digests → the fleet reads and posts
opinions → 23:43 the dreamer synthesizes (Board lenses, cross-model, lateral
feedstock, incubation re-looks) → 00:37 project dreamer → 00:15 regression
gym → 07:13 morning brief. Mondays: estate architect + board minutes.

## Roadmap

- [ ] Counterfactual diff stage live (awaits the liveness-sentinel build, approved)
- [ ] Co-evolution weight curves as the outcomes ledger matures
- [ ] Criticality trend over weeks (the meter is live; the finding needs data)
- [ ] MCP fast path as the fleet default in every client
- [ ] Confluence attachments: tables/images OCR when worth it
