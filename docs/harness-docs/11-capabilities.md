# The capabilities catalog

Parent page: The Agentic Workato Harness

Everything the harness can do, in one page: the agents, the skills, the CLI,
the scheduled fleet, the MCP servers, the slash commands, and the zero-LLM
script stack. Each section states its live count so the page can be verified
against the directories it describes. Counts current as of 2026-10-17.

## The agents: 12

Every agent is a markdown SOP in `~/.claude/agents/`. Details in
[01-agents.md](01-agents.md); the roster in one line each:

| Agent | Trigger | What it does |
|---|---|---|
| brain-gardener | Nightly 22:43, full review weekly | Curates the knowledge tree: staleness, duplication, conflicts, structure, index discipline. |
| workato-watchdog | Nightly 23:13 | Estate proprioception: connection health, stalled schedulers, failure autopsies, external-edit detection. Opens with the heartbeat check. |
| estate-architect | Mondays 06:37 | Weekly estate review: cost heatmap, zombie hygiene, config parity, lineage, security posture, deprecation radar. |
| promotion-orchestrator | On demand | Selects the promotion batch from the build ledger, assembles the manifest, files the deployment story, stages execution. |
| harness-dreamer | Nightly 23:43 | Mines session transcripts and reads the whole night's bus; writes the dream report. Runs last, reader-in-chief. |
| project-dreamer | Nightly 00:37, deep pass Sundays | Architecture dreamer for one project per night; dissenter-gated proposals, advisory only. |
| dissenter | On call, mandatory before proposals reach a human | The immune system: produces the strongest evidence-cited argument against whatever it is handed. Never proposes fixes. |
| evidence | On demand, and nightly at 00:53 | Re-checks the last 24 hours of "done/fixed/verified" claims against live evidence. FALSE verdicts get a dissenter review. |
| spec-distiller | At the start of any build | Writes the build spec (goal, scope, acceptance criteria, risks) before any code. Advisory only. |
| librarian | Weekly | Organizes the knowledge corpus and procures external content on a beat list. |
| cortex | Hourly pulse | Attention (a ranked queue capped at 7), coherence (contradiction hunting across all surfaces), curiosity. Reads everything, mutates nothing. |
| red-team | On demand, at promotion prep | Independent security review of assets heading to production. A FAIL blocks promotion unless the human overrides by name. |

## The skills: 54

Each skill is a `SKILL.md` in `~/.claude/skills/`, a loaded-on-trigger SOP.
49 are cataloged below in five groups; 3 are private or intentionally
unpublished and deliberately omitted (noted at the end).
(2026-10-17 sync: 54 skills live, up from 52 — additions: failure-close-gate,
wt-cookbook.)

### Playbooks: how to drive the platform (22)

| Skill | Purpose |
|---|---|
| airo-mcp-playbook | Gotcha catalog for the platform MCP server (recipe builder, data tables, blueprints, Genies). |
| wt-cookbook | Known-good `wt` invocation recipes — profiles, raw API shapes, hot-swap and test surfaces, and the traps that cost sessions. |
| google-slides-mcp-playbook | Gotcha catalog for the Google Slides MCP server: decks, templates, tables, shapes. |
| workato-kb | Query the local RAG++ knowledge base (docs, changelog, blog, Confluence) with cited hits. |
| kb | Interactive slash-command front end for the same knowledge base. |
| workato-development-playbook | The full inventory-to-release doctrine for Workato systems across environments. |
| workato-skill-builder | SOP for building, wiring, and testing a Genie skill or recipe through the platform MCP, dev only. |
| workato-recipe-control | Start or stop recipes through the Developer CLI when the platform MCP cannot. |
| workato-hot-swap | Edit and redeploy a RUNNING recipe with proof at every step: stop, edit, start, live-run verification. |
| workato-browser-editor | UI-only edits in the signed-in browser when the API surfaces cannot safely do the change. |
| orca-browser | Driving the authenticated built-in browser: perception loop, element refs, screenshots, network capture. |
| efficient-airo-delivery | Low-token evidence gathering and delegation discipline for AIRO build and investigation work. |
| mcp-optimization-playbook | Measured optimization of an MCP server's latency, cost, and caller experience. |
| mermaid-drafting | Draft, render, and debug mermaid diagrams; self-training traps ledger. |
| arch-diagram | Produce and refresh a project's two-level architecture map and rendered SVGs. |
| platform-onboarding | Cold-start the harness on an unseen platform: API discovery, auth mapping, first integration with tests. |
| ahq-prod-recipes | Inspect and operate production-workspace assets handed over by URL or ID, via the prod CLI profile. |
| slack-bot-connection | End-to-end SOP for a workspace-owned Slack bot integration: app, OAuth profile, connection, first test. |
| slack-cli | Official Slack CLI for building and deploying Slack apps from the terminal. |
| workday-wsdl-lookup | Look up Workday SOAP operations and fields from a pre-built index. |
| wql-query-builder | Build, review, and safely execute Workday Query Language queries. |
| fusion | Cost-gated multi-model execution: N models answer the same task, answers are cross-checked. |

### Governance and gates: rules as procedure (16)

| Skill | Purpose |
|---|---|
| manifest-creation | The only sanctioned way to build a Workato export manifest: crawl, populate, verify. |
| manifest-hygiene | Dry-run a promotion manifest before filing; catch missing dependencies and stale references. |
| manifest-review | Itemized blocking/non-blocking review of a manifest on a deployment ticket. |
| deployment-request | The exact promotion process: file the DR ticket, attach the manifest, hand off to final tech review. |
| promotion-readiness | Score an asset's promotion readiness as a checklist with evidence per row. |
| red-team-review | The risk-tiered security-review framework the red-team agent executes. |
| post-deploy-smoke | Prove deployed assets actually run in the target environment after a promotion. |
| rollback-rehearsal | Prove a fix is revertable by rehearsing the revert: snapshot restore, verify, re-apply. |
| uat-evidence | Assemble the UAT evidence block for a story: test runs, traces, masking checks. |
| verify | Enforce live-probe-before-done before any "complete" claim. |
| verify-recipe | End-to-end recipe verification against a real job trace; pass/fail table citing evidence. |
| diff-reading | Read a recipe DSL diff and separate behavioral changes from cosmetic ones. |
| claim-verification | Systematic re-verification procedures for claims in the ledger, per claim type. |
| grill-gate | Planning gate: pin requirements before designing; batch the real judgment calls to one round. |
| run-to-completion | Turn discipline: no ending a multi-step task until done and verified, or genuinely blocked. |

### Estate operations (6)

| Skill | Purpose |
|---|---|
| blast-radius | Compute what breaks if an asset fails or changes: dependents, shared connections, downstream tables. |
| workato-autopsy | Root-cause a failed job to the ORIGIN step, classify the failure, produce a fix-ready report. |
| tdd-fix-loop | Failing-test-first fix loop for recipe bugs, with a 5-iteration stop rule. |
| testcase-authoring | Author a test case that reproduces a failure class and proves the fix. |
| jira-autotriage | The autonomous Jira identify-triage-investigate-plan loop; development stays human-gated. |
| failure-close-gate | A run may mark a finding resolved only if it updates the durable record (canon row, triage card, ledger) in the same run. |

### Human interface (6)

| Skill | Purpose |
|---|---|
| today | Chief of staff: the ranked daily agenda with work pre-staged. |
| triage | Interactive approval queue for fleet-discovered findings; files and dispatches approved work. |
| proposals | Interactive approval queue for dreamer proposals, rendered as decision cards. |
| handoff | Write a resumable handoff: state, verified vs claimed, blockers, exact next command. |
| jira-slack-formatting | Formatting standard for every outbound tracker comment and message: verdict first, strong whitespace. |
| jira-story-standards | Required sections and conventions for epics and stories. |

### Builder lifecycle (2)

| Skill | Purpose |
|---|---|
| squad-build | Parallel multi-agent construction of a multi-asset project over the gossip bus, one verified integration pass at the end. |
| compound-capability-executor | Execute a reviewed compound capability (composition-as-data row) through the Google Semantic MCP, plus conformance checks. |

### Deliberately omitted (3)

`claude-ai-web` (no description in frontmatter), `josh-writing-voice` (a
private prose-voice skill), and `otto-house-style` (house rules for one
specific internal repo). They load locally; they do not belong in a published
catalog.

## The wt CLI: 15 subcommands

`wt`, the Workato Toolbox, wraps the Developer API capabilities that the
platform MCP and the Dev CLI do not expose. Auth is an API token from the
environment or the OS keychain; profiles select dev or production.

| Subcommand | What it does |
|---|---|
| api | Raw Developer API passthrough. |
| recipes | Recipe lifecycle: list, start, stop, force-run. |
| jobs | Job list, repeat, cancel. |
| connections | Connection CRUD. |
| lookup | Lookup-table row CRUD. |
| properties | Project properties list and upsert. |
| folders | Folder CRUD. |
| projects | Project list, update, delete. |
| manifests | Export manifest management. |
| packages | Package export and import. |
| dt | Data-table records: query and CRUD. |
| apic | API platform collections and endpoints. |
| discover | Self-discover the Developer API surface; coverage and gap report. |
| testcases | Test Automation API: run and poll recipe test cases. |
| fixture | Browser-free recipe testing: invoke via webhook, API, or force-run, then assert on the job output. |

The production twin wrappers mirror the MCP dev/prod split. `wt-prod` runs
the same toolbox against the production profile; `workato-prod` does the same
for the Developer CLI. Both read the production token from the OS keychain
per invocation, so it never lands in a shell profile, and both print a
production banner. Every write through either wrapper is still held by the
prod-write confirm gate. For deliberate batches of production work,
`prod-bypass` stands the gates down for a time-boxed window (30 minutes or 2
hours): the flag expires by itself, shows in the status band while active,
and every write in the window stays audit-logged as bypassed.

## The fleet: 42 launchd jobs

Schedules live in launchd plists; job definitions in
`~/.claude/knowledge/config/fleet/jobs/`. Full mechanics in
[05-schedules.md](05-schedules.md). Jobs marked zero-LLM run python only and
spawn no model.

| Job | Schedule | Purpose |
|---|---|---|
| kb-corpus-sync | Tue 07:27 | Weekly knowledge-corpus export with PII and secrets sweep, then commit and push. |
| corpus | Mon 06:07 | Corpus indexer: recipe and task counters, dev and prod. |
| minutes | Mon 06:27 | Board minutes: render the dreaming team's week, publish as a reviewable draft page. |
| roi-weekly | Mon 06:27 | Refresh weekly cost telemetry and ROI report (zero-LLM scripts, verified by a session). |
| architect | Mon 06:37 | Estate-architect weekly review. |
| antigen | Wed 06:07 | Antigen drill: inject one known fault class into the dev canary, record detection and immunity. |
| turn-audit | Tue 07:07 | Weekly zero-LLM turn-discipline classification over transcripts; waste-rate trend. |
| canary | Daily 06:05 | Chaos canary probe (command-canary.py). |
| ops-autopsy | Daily 06:07 | Incident autopsies, gated against repeat autopsies of a known cause. |
| cost-governor | Daily 05:07 | Per-task-class cost/quality posteriors; posts proposals, never mutates routing itself. |
| decision-inbox | Daily 07:20 | One ranked, budgeted decision surface, before the brief (zero-LLM). |
| brief | Daily 07:13 | The morning brief. |
| loadout | Daily 07:45 | Morning load-out: the knowledge files and skills worth loading for the first session. |
| kb-audit | Daily 07:37, 14:07, 19:37 | KB corpus and pipeline integrity audit (zero-LLM), findings to the bus. |
| bus-actuate | Daily, hour :41 | Corroboration tally to consequences: files triage cards when threads cross the act threshold (zero-LLM). |
| harness-fix | Daily 08:10 | Auto-lane worker that fixes the harness's own tooling. |
| gym | Daily 01:07 | Replay gym: nightly harness-regression replay; Sundays add the immune fire drill. |
| synaptic-strength | Daily 03:07 | Synapse-strength scoring (zero-LLM). |
| titer-report | Daily 03:27 | Antibody/immunity titer report (zero-LLM). |
| queue-drift | Daily 03:47 | Rebuild-and-diff the triage queue projection against the live queue; alarms on drift (zero-LLM). |
| index-budget | Daily 03:17 | Index and file-size budget audit (zero-LLM). |
| replay-sample | Daily 03:37 | Replay sampling (zero-LLM). |
| restore-drill | Daily 04:37 | Backup-restore drill (zero-LLM). |
| frontier-nightly | Daily 04:43 | The zero-LLM frontier stack (below). |
| wave3-nightly | Daily 05:07 | Wave-3 zero-LLM loop: trigger scoring, coincidence detection, ratchet watch; Sundays add the null-miner run. |
| instruction-miner | Daily 00:47 | Nightly correction-mining for the instruction-patch loop (zero-LLM). |
| evidence | Daily 00:53 | Evidence hunt: re-check the last 24 hours of claims against live state. |
| dreamer | Daily 23:43 | Harness-dreamer run. |
| project-dreamer | Daily 00:37 | Project-dreamer run. |
| gardener | Daily 22:43 | Brain-gardener run. |
| watchdog | Daily 23:13 | Workato-watchdog run. |
| healer | Daily 23:37 | The watchdog's repair phase, dev workspace only; proposes, never touches production. |
| backup | Daily 23:33 | Snapshot the whole harness, secrets redacted; auto-push the knowledge and kit remotes. |
| harness-health | Daily 23:20 | Watchdog for the harness itself: fleet liveness, ledger freshness, queue dedup. |
| value-ledger | Daily 23:50 | Derive nightly value rows; roll the value-versus-cost report monthly (zero-LLM). |
| docs-watch | Daily 22:31 | Docs crawler summary: fold platform documentation and status deltas into the bus. |
| uat-sweep | Daily 03:17 | Read-only nightly UAT sweep of dev recipes through test cases and fixtures; proposes, never applies. |
| cortex | Hourly | Cortex pulse in the hidden lane, silent unless there is new signal. |
| health | Hourly | Estate health probe (workato-health.py). |
| jira-triage | Every 2 hours | The Jira triage loop pass. |
| ops-visibility | Manual | Local ops visibility server. |

Every job checks in to a shared heartbeat ledger, and the fleet runner
validates each attempt for evidence of work: a silent zero-output exit is a
stub, retried once, then escalated.

## The MCP servers: 12

`claude mcp list` as of 2026-10-17:

| Server | Provides |
|---|---|
| workato-airo-mcp-server | The Workato platform MCP for the dev workspace: recipe builder, Genies, data tables, blueprints, MCP servers, knowledge bases, jobs, docs. |
| atlassian | Jira and Confluence: tickets, comments, pages. |
| slack-workato | Bounded, confirmation-gated Slack operations as the authenticated identity. |
| workato-dependency-tracker | Blast-radius queries: which recipes touch an object, field, or connection; recipe internals; connection health. |
| google-slides | Full Google Slides authoring: decks, templates, layouts, tables, shapes, comments. |
| org-chart | Read-only org-chart lookups (manager, reports, chains) from a materialized snapshot. |
| google-workspace-semantic | The semantic layer for Gmail, Drive, Calendar, People, Docs, Sheets: reviewed capabilities, mutation plans, explicit confirmation. |
| workato-kb | The local RAG++ knowledge base server over roughly 25k documents with hybrid retrieval and citations. |
| brain | The harness's own gossip bus, claim ledger, dream reports, and knowledge-tree read APIs. |
| fireworks-websearch | Web search and fetch. |
| slack-native | Slack's first-party MCP (installed; auth compatibility issue in this environment). |
| seismic-dev | Seismic MCP (installed; requires OAuth). |

## The slash commands

Registered by the guardrails mod and session tools:

| Command | Source | What it does |
|---|---|---|
| /guardrails | workato-guardrails | Hook and gate status. |
| /builds | workato-guardrails | Build ledger summary. |
| /promotion-ready | workato-guardrails | Promotion readiness for a changed asset. |
| /promoted | workato-guardrails | Record a completed promotion. |
| /cockpit | workato-guardrails | Live cockpit view of the estate and the fleet. |
| /snapdiff | workato-guardrails | Recipe snapshot history diff. |
| /budget | session-budget | Session spend and context budget status. |
| /today | today skill | The ranked daily agenda. |
| /triage | triage skill | The findings approval queue. |
| /proposals | proposals skill | The dreamer-proposal approval queue. |
| /kb | kb skill | Query the local knowledge base. |
| /loop | built-in | Run a prompt or command on a recurring interval. |
| /reload-session | session command | Re-absorb current harness state into a live session without losing history. |

## The zero-LLM frontier stack

Jobs that need no judgment spawn no model. The nightly wrapper
(04:43) runs five python scripts in sequence, one log, zero tokens:

1. `twin-snapshot.py` refreshes the estate twin: a local snapshot of the
   workspace state that makes "what changed" a diff instead of a re-discovery.
2. `brier-resolve.py` resolves due predictions and publishes the calibration
   table: how well the harness's own forecasts scored.
3. `precursor-radar.py` runs the precursor scan for early-warning signals.
4. `skill-fitness.py backfill` mines recent transcripts for skill usage.
5. `skill-fitness.py report` publishes which skills actually earn their load.

Sibling zero-LLM scripts round out the stack: `chaos-canary.py` and
`command-canary.py` (the daily canary probes behind the antigen drill),
`twin-query.py` (query the twin ad hoc), `predict.py` and
`prediction-submit.py` (open and check predictions before and after
consequential actions), plus the zero-LLM fleet jobs listed above
(bus-actuator, decision-inbox, queue-drift, value-ledger, synaptic-strength,
titer-report, replay-sample, restore-drill, index-budget,
instruction-miner). The frontier directory
(`~/.claude/knowledge/scripts/frontier/`) holds the stack's contract notes;
the scripts live one level up.

## Where this lives

The kit repo: https://github.com/Workato-All/workato-agentic-kit (docs under
`docs/harness-docs/`, the CLI under `bin/`, schedules under `schedules/`).
The knowledge corpus the agents read and write:
https://github.com/Workato-All/knowledge-corpus, mirrored locally at
`~/.claude/knowledge/`.
