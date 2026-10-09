# workato-kb

Local RAG++ knowledge base over all Workato documentation and the BT team's
Confluence, plus the dreaming-team science layer: fractal memory, the
prediction-error protocol, neuromodulation, agent calibration, the dissenter
triad, and the rehearsal cortex. The agent's daily companion for planning,
scoping, building, and testing — and the corpus the dreamers dream on.

Built 2026-10-08 for Josh's agentic harness (v0.7.3). Companion skill:
`workato-kb`; human slash command: `/kb`. Adoption package: the
the agentic-kit repo carries this code + the harness scripts + skills + authoring rules.

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


## The five builds (Oct 9, v0.8.0)

- **Chief of staff (`/today`)**: one ranked agenda from every surface — machine heartbeats first (a silent job is the headline), decisions blocking the fleet, calendar, then deep work — with each item PRE-STAGED (draft replies in Josh's voice, first commands ready). The loadout loads context; /today prioritizes the day.
- **The benchmark** (`kb benchmark`): the "best harness" claim turned into a measurement — same tasks, two arms (harness vs a truly-isolated bare agent via config-dir override), scored accuracy-first (per-task graded checks), turns second, cost third; latency demoted (bare wins it by construction). First scored result: on trivial docs questions the arms TIE on quality and the harness costs ~6x — the honest finding; the differentiating evidence comes from diagnosis/UAT/manifest tasks. Weekly auto-run (Sundays 04:07) feeds a trend ledger.
- **Learned model routing** (`model_routing.py`): which model's opinions get accepted is MEASURED (via `models:` attribution on every proposal) and future lens assignment routes by acceptance-at-lowest-cost, explore-exploit kept live.
- **The skill forge** (`skill_forge.py`): the dreamer doesn't propose "there should be a skill" — it drafts the SKILL.md into staging, the forge validates it (description-as-trigger, length, TODOs), and Josh's accept installs it. The loop from idea to working artifact, reviewed.
- **The typed bus** (`bus_post.py`): finding/opinion/vote schema so corroboration (1 observation / 2 pattern / 3+ act) is arithmetic, not prose-reading.

## The ROI study (the proof the anecdote needed)

All BSYS tickets assigned to Josh, resolved since May (n=142), stratified by
CREATION era, backlog-hygiene closures (>60d) separated:

| Cohort | n | median created→resolved | same/next-day |
|---|---|---|---|
| Pre-harness (May–Aug) | 102 | 12.8 days | 11% |
| Harness era (Sept+) | 12 | **0.7 days** | **67%** |

18x cycle-time reduction on fresh work; 6x same-day rate; 28 stale backlog
closures as a bonus. Re-runs monthly from one JQL — the claim is reproducible,
not anecdotal.

## The five learning modalities (Oct 9, v0.9.0)

The harness so far learned by consolidation only. Five new channels — the other ways brains learn:

- **Case-based reasoning** (`kb cases`): the medical model. Every incident/bug/fix becomes a CASE (presentation → diagnosis → treatment → outcome); at decision time, retrieve similar cases FIRST instead of re-deriving from facts. **Seeded from Josh's closed Jira tickets (BSYS + BTSUP, 2025→: 209 tickets pulled, 28 clinical cases after problem-shape + resolution-evidence filters) + the regression canon + autopsies — years of solved issues as clinical experience.**
- **Apprenticeship from the estate** (`kb apprentice`): the org's own recipes are a corpus nobody learns from. Pattern-level mining (error-handling idioms, retry patterns, safe-navigation usage — never business logic verbatim, read-only, sanitized) distilled into the KB: the fleet learns what colleagues already know.
- **The judgment gym** (`kb gym_judgment`): spaced repetition for fleet judgment — past incidents re-presented as drills, answers graded against known outcomes, failed cases resurface sooner; the diagnosis-accuracy curve is the improvement metric.
- **The curiosity engine** (`kb curiosity`): surprises MINT questions into a standing ledger (why did that prediction deviate? why is this metric anomalous?); the dreamer spends nightly effort on the highest-value open questions; answers bind back as claims. The harness goes from a system that answers to a system that wants to know.
- **The competence map** (`kb competence`): questions route by measured track record per agent/model/domain — a division of labor that emerges from evidence, not assignment.

All five report into `science-state.json` (read by the ops dashboard) and are gym-invariant-checked (A6: fresh < 36h).