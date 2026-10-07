# Agentic Workato Kit

A self-teaching, self-healing Workato development harness for Claude Code:
enforcement mods, curator/watchdog/architect agents, a cross-session build
ledger, recipe snapshot history, a claim ledger, and a knowledge tree that
curates itself nightly.

## What you get

**Mods (always-on enforcement, Claude Code >= 2.1.287):**
- `workato-guardrails` — secret redaction, prod-write audit + push risk
  scorer (holds risky prod pushes for confirmation), Jira story-points gate,
  Workato asset URL linking, standards injection, datapill/writeback
  warnings, build ledger (every AIRO + CLI + Orca mutation, ticket-tracked),
  recipe snapshot history (git-diffable "what changed"), `/guardrails
  /cockpit /builds /promotion-ready /promoted /diff` commands
- `brain-guard` — write-time linting of memory/knowledge (relative dates,
  missing frontmatter, INDEX drift), usage telemetry (skill loads, knowledge
  reads, MCP bytes + error classes, turn token usage)

**Agents (on-demand + scheduled):**
- `brain-gardener` — nightly knowledge curation: drift, conflicts, transcript
  dreaming, harvest-rate metric, claim re-verification; proposals land as
  git branches you merge
- `workato-watchdog` — nightly estate checks: broken connections with
  running-recipe blast radius, stalled schedulers, failure autopsies,
  postmortem drafts, external-edit detection
- `estate-architect` — weekly architecture review: cost heatmap (runtime
  tasks vs dev tokens), zombie hygiene, environment parity, lineage maps,
  security posture, deprecation radar
- `promotion-orchestrator` — on-demand: ledger-driven promotion batches,
  manifest with ONLY touched assets, the Jira story with your field map,
  staged execution with UAT evidence

## Install

1. Prerequisites: Claude Code >= 2.1.287, git, python3, jq. Connect the MCP
   servers you use (AIRO dev/prod, dependency tracker, Atlassian) — the kit
   can't do your auth.
2. Copy `config.example.sh` → `config.sh`, fill in your workspace IDs and
   Jira field IDs (see comments for how to discover them).
3. `./install.sh`
4. Restart Claude Code, run `/guardrails` to smoke-test.
5. Set up the schedules: `schedules/README.md`.

## Trust model

Mods run with your permissions, unsandboxed. Every file in this kit is
readable in minutes: hooks declare exactly which events they touch, and
`claude plugin validate <dir>` lists every event + API call before you load
anything. The agents are advisory — they propose; you merge. Production
import steps only run on your explicit go, per stage.

## Layout

    config.example.sh     per-person settings (workspaces, Jira fields)
    install.sh            renders templates + installs everything
    mods/                 the two plugins (hooks modules + tests)
    agents/               the four agent SOPs
    skills/               Jira/story conventions (adapt to your team)
    knowledge/            INDEX template + scripts + claim-ledger schema
    schedules/            cron prompt templates + launchd plist

Tested with Claude Code 2.1.289 on macOS (darwin). The mods use standard
mods events (`tool.call`, `prompt.submit`, `ui.render`, `turn.complete`);
Windows/WSL is untested.
