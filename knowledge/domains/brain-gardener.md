# Brain Gardener — domain knowledge

The brain gardener is Josh's knowledge-base curator agent: a gardener that
regularly reviews the memory/knowledge architecture and files a report.
Advisory-only by design — it is NOT in the decision loop; it proposes,
Josh + the main session apply.

## v2: the nervous system (built 2026-10-06, Josh: "build all 7")

Seven capabilities, three tiers (prevention → nightly curation → weekly
architecture):

1. **Write-time linting** — `brain-guard` plugin (`~/mods/brain-guard`,
   installed via josh-mods marketplace): lints memory/knowledge writes at the
   moment of writing (relative dates without absolute anchors, memory files
   missing frontmatter/type, knowledge writes with no INDEX.md touch this
   session). Annotates the tool result + `$.ui.log`, never blocks. 7/7 tests.
2. **Usage telemetry** — same plugin: every Skill load, INDEX/knowledge/memory
   read, and memory/knowledge write appends one JSON line to
   `garden-reports/usage-ledger.jsonl` (gitignored — churn, not knowledge).
   The gardener reads it to see which knowledge is load-bearing vs dead.
3. **Claim ledger** — `~/.claude/knowledge/claims/` (claims.jsonl + README
   schema): durable knowledge as structured claims {subject, claim, evidence,
   confidence, asserted_at, last_verified, status}. Contradictions =
   mechanically detectable (same subject, conflicting active claims).
   Supersede, never edit. Seeded with 6 claims from 2026-10-05/06 work.
4. **Semantic dedup** — `knowledge/scripts/dedup-shortlist.py` (stdlib-only
   Jaccard token-set similarity): shortlists candidate duplicate pairs; the
   gardener's LLM adjudicates. Verified live: 0 pairs ≥0.6 on 2026-10-06.
5. **Harvest-rate metric** — `knowledge/scripts/harvest-rate.py`: event
   signatures in today's transcripts vs knowledge/memory writes same window.
   Directional trend gauge (event regexes over-match tool output — treat as
   trend, cross-check surprising numbers by hand).
6. **Proposals as git branch** — knowledge tree IS a git repo (main). Weekly
   gardener runs commit proposed edits to `gardener/YYYY-MM-DD` branch only;
   review = `git diff main gardener/*`, apply = merge. NEVER touches main.
   GIT SAFETY (hardened 2026-10-11, proven incident: `checkout -q -f main`
   over a dirty tree destroyed ~49 uncommitted triage/outcome rows, patch
   restore failed twice unverified): before ANY checkout, `git status
   --porcelain` must be clean; if dirty, `git stash push --include-untracked
   -- <paths>` then checkout then `git stash pop`; pop conflict → exit
   non-zero with the stash ref preserved, never force/patch-over-dirty.
   Full procedure: Phase 5 of the agent definition.
7. **Meta-improvement** — `garden-reports/proposal-outcomes.jsonl`: every
   proposal's fate (accepted/rejected/false-alarm/modified). Phase 0 of each
  run reads it and proposes SOP threshold changes when a proposal kind
   exceeds ~30% rejection. Seeded with the 7 outcomes from run 1.

## Architecture (set up 2026-10-06)

- **Agent**: `~/.claude/agents/brain-gardener.md` (user-level, all projects).
  Full SOP inside: 4 phases — inventory, health checks, transcript dreaming,
  garden report. Hard rules: no writes except to garden-reports/; grep-and-
  sample transcripts (never read whole, they're tens of MB); cite evidence;
  relative dates → absolute; UAT/prod-touching proposals marked "needs Josh".
- **Report destination**: `~/.claude/knowledge/garden-reports/YYYY-MM-DD-<slug>.md`.
- **Schedule**: durable cron job id df43b546, NIGHTLY 22:43 (Josh: "with the
  amount of work I do, shouldn't it be running nightly?" — weekly was too
  sparse; nightly keeps dream-scrape windows small and drift-catching fast).
  Cadence design: nightly runs review today's transcript(s) + changes since
  the last garden report; a FULL inventory/health review happens weekly.
  The scheduled prompt is SELF-REARMING: it checks the task's createdAt and
  re-creates itself before the 7-day auto-expiry lapses (recurring native
  tasks die after 7 days — this is the workaround). **Persists to the
  PROJECT's `.claude/scheduled_tasks.json`**
  (`~/Documents/workbench/.claude/scheduled_tasks.json`), NOT
  `~/.claude/scheduled_tasks.json` — the first gardener run misread the home
  copy as evidence the schedule was missing.

## The grounds it curates

1. `~/.claude/knowledge/` — INDEX.md router + domains/ + projects/
2. `~/.claude/projects/<slug>/memory/` — auto-memory files + MEMORY.md index
3. CLAUDE.md instruction files (global, ~/Documents/, per-project)
4. `~/.claude/skills/` — global procedure skills
5. `~/mods/` + installed plugins — rules enforced in code
6. `~/.claude/projects/<slug>/*.jsonl` — session transcripts (dreaming material)
7. `~/.claude/agents/*.md` — agent definition files (added 2026-10-07)

## Architecture role (added 2026-10-07)

Josh: "not just the content management system but also the architecture
and infrastructure agent."

The gardener is also the brain's ARCHITECT: Phase 2.3 (weekly) audits
STRUCTURE — file size budgets, hub/reference modularization, thin-index
discipline, skill/agent description routing, layer violations, prose-that-
should-be-a-hook. The rulebook it audits against lives in
`domains/brain-architecture.md` (agent file points to it, keeping the
agent file lean — the gardener practices its own modularization rule).
New proposal kinds: modularize / extract-index / split-file, tracked in
the Phase 0 outcomes log like the rest. Still propose-only: splits land
as `gardener/*` branch commits for Josh's review.

## Scheduling caveats (important)

- Native scheduled tasks: **recurring jobs auto-expire after 7 days** — the
  Monday cron needs re-arming (or convert to a launchd job running
  `claude -p` headless for true durability; headless runs can't ask
  permissions, so the agent must stay read-only — which it is by design).
- Scheduled tasks fire only while a REPL session is idle, not headless.

## Known drift found at setup (first-run seeds)

- `projects/event-process-mcp.md` existed in knowledge tree with NO INDEX.md
  line — caught in the first terrain survey; intentionally left unfixed so
  the gardener's first report demonstrates the conflict-detection flow.
- Agent types load at session start: a newly written .md in ~/.claude/agents/
  is not spawnable until the next session (spawn general-purpose with the SOP
  path as brief as the fallback).

## Platform-delta feed (docs crawler, 2026-10-06)

- `knowledge/scripts/workato-docs-watch.py` + `docs-watch-sources.json`:
  stdlib crawler over Workato changelog (product-hub), docs product-updates
  (`.md` variant — docs.workato.com serves LLM-optimized markdown), and
  status.workato.com RSS. Snapshots + diffs to
  garden-reports/platform-delta.jsonl. Nightly cron 22:31 summarizes changes
  and proposes (never applies) playbook/skill updates.
- Dynamic-JS pages (product.workato.com/changelog/) and CSS-noisy pages
  (community.workato.com) are unusable sources — removed after live testing.
- Weekly gardener folds platform deltas into its report: "Workato shipped X —
  does playbook Y need updating?" with the delta excerpt as evidence.

## Official docs canon (added 2026-10-07)

The gardener audits against `domains/claude-code-docs-canon.md` — official
Claude Code doc best practices (CLAUDE.md sizing/adherence, auto-memory caps
and type taxonomy, Agent Skills spec + authoring checklist, settings
precedence). Wired into the agent file as a load-before-audit rulebook, same
pattern as brain-architecture.md. When official docs change materially
(legit channel: the docs-watch crawler), refresh the canon's rules + sources
section, don't fork a second file.

## Drift gate (added 2026-10-09)

`scripts/drift-gate.py` (run in the kb venv) = the memory-vs-WORLD alignment
check that dream_entropy's memory-STATE entropy doesn't cover: every active
claim is retrieved against the kb ground-truth corpus (BM25+vector+rerank)
and classified doc-supported / weak-support / no-source. The gardener
adjudicates weak-support rows (kb.read + entailment), reclassifies
mis-routed platform-behavior claims (their ground truth is a live probe, no
doc could exist — e.g. clm-005 payload-size claim), and watches the TREND in
garden-reports/drift-gate.jsonl: persistent weak-support = wrong corpus;
falling top_score = real semantic drift → propose supersede. Born from the
"Semantic Entropy Shielding" paradigm — adopted as this mundane kernel;
the GNN/hypergraph/quantum siblings were rejected (kernels already live:
dissent_ledger.py, canon.jsonl, evidence agent).

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Memory and the knowledge base architecture](../../kb-corpus/confluence/extbt/2939158533-memory-and-the-knowledge-base-architecture.md)
- [The Agentic Workato Harness: a self-improving development organism](../../kb-corpus/confluence/extbt/2938830860-the-agentic-workato-harness-a-self-improving-development-organism.md)
- [Knowledge base recipes](../../kb-corpus/docs/en/agentic/agent-studio/knowledge-bases/knowledge-base-recipes.md)
- [Knowledge bases versus databases](../../kb-corpus/docs/en/agentic/agent-studio/knowledge-bases/knowledge-bases-and-databases.md)
<!-- kb-bridges:end -->
