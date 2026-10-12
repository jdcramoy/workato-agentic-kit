---
name: mcp-optimization-playbook
description: Optimize an MCP server's latency, token/output cost, and caller experience through measured, contract-safe upstream projections, bounded modes, and live verification. Use when benchmarking or improving MCP tools; do not use for unrelated feature work.
metadata:
  short-description: Measure and optimize MCP tools safely
---

# MCP Optimization Playbook

Improve useful-work efficiency, not just an individual tool's byte count. Aggressively remove every upstream field, result property, enrichment call, and parsing step that is not needed for the current task. A smaller response is a win only when the normal user/LLM workflow can still discover, decide, and complete the task with equivalent or better clarity, safety, and total cost. Retain only the information needed for the next sensible action, and preserve a clear bounded detail path for everything else.

## Workflow

1. Identify the deployed tool route, active asset/version, public input/output contract, auth boundary, and rollback target. Do not modify stale exports or archival clones.
2. Measure comparable warm before/after trials: p50/p95 latency, errors, MCP response bytes/token estimate, upstream projection, and call/fan-out count. Keep fixture, projection, page size, and caller context constant.
3. Diagnose whether the cost is upstream over-fetch, unnecessary enrichment, output placeholders, type coercion, serial calls, hidden caps, or telemetry on the response path.
4. Define the standard workflow before removing data: what does a caller need to identify the right item, make the next decision, and complete the task? Make the default projection the smallest task-complete response; put richer bodies, history, metadata, or attachment detail behind an obvious bounded detail mode or follow-up. Compare end-to-end calls, latency, bytes/tokens, and success—not only a single response. Keep a richer default only when evidence shows most standard workflows need it and progressive detail would cost more overall.
5. Apply the smallest suitable change:
   - provider partial fields/select;
   - compact/default plus an intentional detail mode or follow-up read;
   - explicit, hard-capped read override with applied-limit feedback;
   - omission of unnecessary parsing/attachments/artifact work;
   - typed compact output rather than blank/null padded records.
6. Classify any public change. Preserve defaults where possible; for a breaking shape/type change, version or add a named tool unless the owner explicitly accepts the break.
7. Validate locally, at schema/mapping level, and live. Check serialized types—not only the internal object. Run at least one representative end-to-end workflow through the compact and detail paths. Repeat warm trials and confirm caller isolation, error handling, and bounded operational behavior.
8. Record release version, measured gains, workflow tradeoffs, and rollback point. Do not promote or alter production without separate authorization.

## Non-negotiable checks

- Never call a client queueing result evidence of backend concurrency.
- Keep hard ceilings even when callers can opt into extended read limits.
- Do not stringify arrays/objects through interpolation; use platform-native typed bindings.
- Do not return fabricated empty/null optional fields in compact records.
- Do not remove selection-critical fields merely to reduce tokens. Preserve minimal decision context or a first-class detail path, and measure the complete workflow before claiming a gain.
- Treat unused payload as a defect: trim it at the provider request, connector/function mapping, and public response layers. Do not stop at a smaller upstream request if the MCP envelope remains bloated.
- Keep telemetry asynchronous and metadata-only; retain masking, caller scope, idempotency, confirmation, and cleanup protections.

Read the full reusable reference when planning, benchmarking, or documenting an optimization: [playbook](references/playbook.md).

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [MCP server tool design](../../kb-corpus/docs/en/mcp/mcp-server-tool-design.md)
- [Prompt Optimization Project README](../../kb-corpus/confluence/intbt/2911502687-prompt-optimization-project-readme.md)
- [Workato MCP Server Development Framework](../../kb-corpus/confluence/extbt/2159444213-workato-mcp-server-development-framework.md)
- [Common MCP Troubleshooting](../../kb-corpus/confluence/extbt/2308833651-common-mcp-troubleshooting.md)
<!-- kb-bridges:end -->
