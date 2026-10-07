# Agentic Workato Kit

A self-teaching, self-learning, and self-healing development harness for
agentic Workato work in Claude Code. It wraps an AI-assisted Workato
developer (human or agent) in four layers: enforcement mods that make the
standing rules mechanical, watcher agents that inspect the estate on a
schedule, a curated knowledge system that captures lessons and verifies them
against live behavior, and a promotion pipeline that turns tracked dev work
into governed production releases.

The design goal: no rule should depend on memory, no failure should depend on
luck, and no knowledge should live only in one session's context.

## How the layers fit together

1. **Enforce (always on).** Two mods hook every tool call. They redact
   secrets, audit production writes, score push risk, gate Jira ticket
   quality, record every mutation, and snapshot every pushed recipe. Rules
   that used to live in instruction files are now code.
2. **Watch (nightly).** Scheduled agents inspect the estate: broken
   connections with blast radius, stalled schedulers, failed-job autopsies,
   platform release notes. Each run leaves a heartbeat; the last job of the
   night checks the others and reports a skipped machine.
3. **Learn (nightly + weekly).** A curator agent ("brain gardener") reviews
   the knowledge base for drift, conflicts, and rot, mines session
   transcripts for unrecorded lessons, measures the harvest rate, and files
   proposals as git branches. Behavioral claims about the platform get
   re-verified as a side effect of real work.
4. **Promote (on demand).** A promotion orchestrator assembles batches from
   the build ledger, files the deployment story with your site's real field
   IDs, and stages production execution behind explicit approval.

## The inventory in detail

### Mods (plugins, always loaded)

`workato-guardrails` registers 12 hooks on tool calls, prompts, and UI
renders. Each hook is a few lines; `claude plugin validate` lists exactly
what each touches before you load anything.

| # | Hook | Fires on | What it does |
|---|---|---|---|
| 1 | Secret redaction | every tool result | Strips API keys, tokens, Bearer headers, and `key: value` shaped secrets from results before the model reads them. Prose is untouched. Registered first so it sees every other hook's output last. |
| 2 | Prod-write audit | any write tool on the production AIRO MCP | Appends one line to an audit log and prints a transcript band. Never blocks. |
| 3 | Push risk scorer | every `recipe_builder_push` | Looks up the recipe's live health through the dependency tracker (running state, fail rate, last-run age, never-run) and annotates the result. On production pushes scoring medium or above, holds the call for an explicit proceed or cancel dialog. |
| 4 | Story-points gate | `createJiraIssue` | Denies ticket creation without a points value in the configured custom field, with the scale inline. Configurable exempt projects where the field is not on the screen. |
| 5 | URL linker | AIRO and tracker results | Appends canonical `app.workato.com` URLs for any recipe, table, or folder ID found in a result, so summaries always carry links. Skips results that already link. |
| 6 | Standards injection | prompts that create Jira work | Adds your story-standards document to the prompt as hidden context. Reads the live skill file at session start; embeds a fallback digest. |
| 7 | Datapill warning | `recipe_builder_pull` | Warns at the moment of exposure that DSL exports can show mapped datapills as literal sample values. |
| 8 | Writeback nudge | every Jira or Confluence write | Reminds to re-read the artifact and confirm rendering before calling it done. |
| 9 | Build ledger (AIRO) | every successful AIRO mutation | Appends one JSON line per mutation to a shared ledger: tool, server (dev or prod), session, recipe, folder, ticket. |
| 10 | Build ledger (CLI and browser) | Bash commands using the Workato CLI or Orca | Ledgers the paths that bypass AIRO. A successful CLI start also triggers a read-back that verifies the start actually took, refreshing the relevant platform claim. |
| 11 | Slash commands | user | `/guardrails` (hook status), `/builds` (ledger summary for today, week, or all), `/promotion-ready` (dev edits newer than their last promotion mark), `/promoted` (mark recipes shipped), `/diff` (recipe snapshot history). |
| 12 | Snapshot history and cockpit | every push; on demand | After each push, pulls the fresh DSL from the matching server and commits it to a local git repo, so "what changed in this recipe" is a diff. `/cockpit` opens a pane with session counters and the ledger tail. |

`brain-guard` registers 5 hooks for the knowledge system itself:

| Hook | Fires on | What it does |
|---|---|---|
| MCP telemetry | every MCP call | Logs tool, result byte size, and error class. This is what makes cost and failure reports possible. |
| Turn usage | every completed turn | Logs input, output, and cache token counts. |
| Skill telemetry | every skill load | Logs which skills sessions actually use. |
| Knowledge telemetry | every read or write of knowledge and memory files | Logs which knowledge is load-bearing and which is dead. |
| Write linter | every write or edit under the knowledge or memory trees | Nudges on relative dates without absolute anchors, memory files missing frontmatter, and knowledge writes with no index update. Annotates, never blocks. |

### Agents

Each agent is a markdown SOP in `~/.claude/agents/`. They are advisory: they
report and propose, they never mutate the estate or the knowledge base
without approval. The exception is proposal branches, which land only on
`gardener/*` branches of the knowledge repo.

**brain-gardener** (nightly 22:43, full review weekly). Reads its own
acceptance-rate log first, then inventories the knowledge tree against its
index, checks for conflicts, duplication, and temporal rot, rolls up
opportunistic claim verifications, mines session transcripts for unrecorded
lessons, and files a garden report with a top five priority list. Cadence
design: nightly runs review only what changed since the last report; the
weekly run does the full inventory.

**workato-watchdog** (nightly 23:13). Five checks: exception connections
with running-recipe blast radius (P1), stalled schedulers (running recipes
with no recent jobs, the silent post-restart failure class), failure
autopsies clustered by error class with proposed playbook entries, external
edit detection (recipes whose update time moved with no ledger entry, which
is how human UI edits and other agents show up), and postmortem drafts for
P1 incidents, filed only on approval. Opens with a machine-health line: if
last night's gardener or crawler never heartbeated, that is a P0.

**estate-architect** (Mondays 06:37, after the corpus indexer refreshes the
index). Six phases: cost heatmap coupling runtime tasks per folder with dev
token spend; zombie hygiene (recipes with no runs in 90 days, orphaned
tables and connections); config parity between environments (properties
diffed, secrets reported as set and hidden); lineage maps per folder as
mermaid diagrams with an optional field-level harvest on named folders;
security posture heuristics (personal-account connections, identity per
skill); and a deprecation radar matching platform release deltas against
recipes that use the affected features.

**promotion-orchestrator** (on demand; batches are inventory-driven, not
scheduled). Phase 1 selects the batch from the build ledger: dev mutations
newer than their last promotion marker, nothing else, ever. Phase 2
assembles the manifest with only those assets and captures the rollback
snapshot hash. Phase 3 files the deployment story (Story type, never a
deployment-request type) with the manifest URL, source and target
environment fields, points, and parent epic, showing the draft for approval
first. Phase 4 stages production execution: dependency order, VUA
verification after import, smoke tests per stage, each step on an explicit
go.

### Knowledge system

- **Knowledge tree** (`~/.claude/knowledge/`): a git repo. `INDEX.md` routes
  to `domains/` (cross-project knowledge) and `projects/` (per-project
  state). Everything is committed; the gardener's proposals arrive as
  branches you merge.
- **Claim ledger** (`claims/claims.jsonl`): durable knowledge as structured
  claims with evidence, confidence, and a last-verified date. Load-bearing
  behavioral assertions (does the platform still do X) live here so they can
  be checked rather than remembered. Supersede, never edit.
- **Opportunistic verification** (`claims/verifications.jsonl`): the mods
  stamp claims as real work exercises them (a push that succeeded while a
  recipe was running, a CLI start that was read back). The gardener rolls
  these into last-verified dates. A synthetic probe harness is deliberately
  parked; passive verification from real work covers most of its value.
- **Telemetry ledgers** (`garden-reports/usage-ledger.jsonl`): the usage
  feed the gardener and heatmap read. Build ledger lives at
  `~/.claude/knowledge/build-ledger.jsonl`.
- **Scripts** (`knowledge/scripts/`): cost heatmap, recipe corpus search,
  dedup shortlister, harvest-rate gauge, and the docs crawler. All stdlib
  python.
- **Garden reports** (`garden-reports/`): dated reports from every agent
  run, plus the proposal-outcomes log the gardener uses to grade itself.

### Schedules

All agent schedules are self-rearming: each run re-creates its task before
the platform's 7-day scheduler expiry lapses. See `schedules/README.md` for
the exact prompts.

| When | Job |
|---|---|
| 22:15 daily (launchd) | Docs crawler, unattended, no session needed |
| 22:31 daily | Docs crawler summary in-session |
| 22:43 daily | Brain gardener (incremental) |
| 23:13 daily | Workato watchdog, including the heartbeat check |
| Mon 06:07 | Corpus indexer (recipes + task counters, dev and prod) |
| Mon 06:37 | Estate architect (full review) |

## Install

1. Prerequisites: Claude Code 2.1.287 or later, git, python3, jq. Connect
   your MCP servers first (AIRO dev and prod, dependency tracker, Jira);
   the kit cannot do your authentication.
2. `cp config.example.sh config.sh` and fill in your workspace IDs and Jira
   field IDs. The comments explain how to discover the field IDs from one
   of your past promotion stories.
3. `./install.sh`
4. Restart Claude Code, then run `/guardrails` to confirm the hooks loaded.
5. Set up schedules from `schedules/README.md`.

## Trust model

The mods run with your permissions and are not sandboxed. Every hook
declares the events it handles, and `claude plugin validate <dir>` prints
every event and API call before you install. The agents are read-only
against Workato: production import steps run only on explicit approval, one
stage at a time, and knowledge mutations land as proposal branches. Rollback
for the whole kit is two commands: `claude plugin uninstall <mod>` and
deleting `~/.claude/agents` entries.

## Tested with

Claude Code 2.1.289 on macOS. The mods use standard mod events (`tool.call`,
`prompt.submit`, `ui.render`, `turn.complete`, `command.run`); drawing
surfaces fall back to text in VS Code, headless, and SDK contexts. Windows
is untested.
