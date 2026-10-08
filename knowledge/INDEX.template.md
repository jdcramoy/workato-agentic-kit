# Knowledge Index — routing table

One line per knowledge file. Read the line, load the file if relevant to the
current work. Update the line whenever you update a file.

## Domains (cross-project: load whenever working in this domain, any project)

- [Workato platform](domains/workato-platform.md) — AIRO/Workato platform behavior, traps, asset conventions; watchdog + estate-architect + promotion-orchestrator agents; build ledger + recipe history
- [Workday platform](domains/workday-platform.md) — Workday SOAP/WSDL/WQL knowledge
- [MCP operations](domains/mcp-operations.md) — MCP server/reconnect/reauth operations
- [Claude Code mods](domains/claude-code-mods.md) — building/installing/rolling back mods; the kit's guardrails plugins
- [Brain gardener](domains/brain-gardener.md) — knowledge-base curator agent + brain-guard plugin; nightly/weekly curation
- [Brain architecture rulebook](domains/brain-architecture.md) — structural best practices the gardener audits against (size budgets, modularization SOP, thin-index rules, routing surfaces)

## Projects (load when working in this project)

<!-- one line per project: [Name](projects/<name>.md) — canonical repo/doc pointers, current state headline -->

## Rules

1. **Scope test**: makes ANY project better → domains/. Makes THIS project's
   next session better → projects/<name>.md. Is a procedure → global skill.
   Is the full canonical story → project repo; knowledge file points to it.
2. **Auto-save**: every true build/technical session deposits durable lessons
   into the project file + updates its INDEX line at session end.
3. Claims that are load-bearing and verifiable go in claims/claims.jsonl.
