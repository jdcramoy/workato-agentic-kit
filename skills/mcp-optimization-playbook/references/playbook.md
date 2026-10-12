# MCP Optimization Reference

Inlined 2026-10-10 from the canonical source
`~/Documents/ChatGPT/Gmail MCP/mcp-optimization-playbook.md` (the reference
was previously a dead pointer to that file — mined and absorbed during the
legacy-tree migration). The source file stays as archive; treat THIS copy
as the live reference and edit here.

Use this playbook to make an MCP server faster, smaller, more predictable, and easier for agents to use—without turning optimization into an undocumented breaking change or a less capable workflow. The target is useful-work efficiency: aggressively remove payload that is not needed for the current task, while completing standard user/LLM tasks with equal or better clarity, safety, and total cost.

## What good looks like

An optimized tool has a clear purpose, a bounded cost, an honest result contract, and measured behavior:

- It fetches only the upstream fields it returns or genuinely needs to compute them.
- It gives callers a cheap discovery projection and an intentional richer projection.
- It reports pagination, applied limits, truncation, partial outcomes, and clamping rather than silently hiding them.
- It keeps expensive fan-out, MIME/body parsing, attachment inspection, and artifact staging opt-in and bounded.
- It preserves stable types. Arrays are arrays, booleans are booleans, and absent optional fields are omitted rather than represented as fabricated blank data.
- It retains the minimal context needed to select the right item and make the next decision. Any omitted detail remains available through an obvious, bounded projection or follow-up tool.
- It remains caller-scoped and safe under invalid input, retries, and normal operational load.

## 1. Establish a trustworthy baseline

Inventory every tool before changing anything: public name, parameters, result schema, upstream calls, mutating behavior, authorization requirement, output size, and active route/recipe/function. Resolve the deployed path before editing; stale clones and local exports are not evidence of runtime behavior.

For each target, capture comparable warm trials against the existing version. Also identify one or more representative end-to-end workflows (for example: discover → select → inspect → act). A response-level saving is not a win if it forces extra calls, ambiguity, or lost task capability that costs more across the workflow.

| Measure | Why it matters |
| --- | --- |
| p50/p95 latency and error rate | Avoid optimizing a one-off cold sample. |
| MCP response bytes and token estimate | This is the caller-visible cost. |
| Upstream request/response projection | Detect invisible over-fetch. |
| Number of upstream calls and fan-out width | Exposes serial work and accidental enrichment. |
| Public result shape | Prevents a smaller but less useful contract. |

Use the same fixture, projection, page size, and caller context for before/after trials. Treat queueing in a client wrapper as client behavior, not proof of server concurrency.

## 2. Diagnose the actual cost

Trace the live path from MCP parameter to response. Identify which work dominates:

- Over-fetch: an upstream API returns fields discarded by the recipe/function boundary.
- Over-enrichment: a list tool fetches every detail, body, or attachment before a caller has selected an item.
- Output bloat: optional properties are serialized as empty strings, nulls, or stringified JSON.
- Repeated/serial calls: detail lookups, telemetry, or validation occur more than once or on the critical path.
- Hidden caps: a requested limit is clamped with no applied-limit signal.
- Type erosion: platform mapping turns arrays, booleans, or integers into strings.

Do not assume the published schema and runtime mapping agree. Inspect a live result and the active route after every schema or connector release.

## 3. Choose the narrowest effective optimization

Prefer a small, measurable change that preserves the default contract.

### Preserve task-complete information

Before removing a field, ask whether an LLM or user needs it to identify the correct object, decide what to do next, or safely complete the common task. Preserve minimal decision context—such as identity, status, concise subject/snippet, timestamps, or a next cursor—when it prevents a follow-up call or disambiguates the next action.

Use a compact projection only when it has a first-class path to the omitted detail: stable IDs plus a bounded read, a named `detail` projection, or a clear follow-up tool. Compare the entire standard sequence, not just the first tool call. A rich default remains appropriate where most callers need the richness and splitting it would add more total latency/tokens or reduce usability.

The default should normally be the smallest task-complete projection, not the richest record the upstream API can produce. Remove bloat at all three layers: the provider request, the connector/function mapping, and the serialized MCP response. Then give callers an explicit detail mode or follow-up tool for rich content. This reduces tokens and unnecessary LLM turns while retaining full capability on demand.

### Upstream projection

Use the provider's partial-response, fields, select, or sparse-field mechanism. Request only data that crosses the public boundary or is needed for a documented computation. This often lowers latency and internal payload cost even if a legacy public response must remain unchanged.

### Progressive detail

Make discovery cheap. Offer IDs/compact metadata by default; make bodies, attachment metadata, and deep detail intentional projections or follow-up reads. Carry cursors forward rather than accumulating unbounded lists.

### Bounded, explicit overrides

Use a safe default and hard ceiling. Let a caller explicitly request more only when the tool can state the applied value and the ceiling. A useful pattern is:

- standard: safe default and low ceiling;
- extended: explicit increased read-only ceiling;
- hard maximum: never bypassed;
- response fields: `requested_limit`, `applied_limit`, and `warnings`.

Do not offer unbounded override switches. Keep mutation tools conservative even when read tools gain an extended mode.

### Compact modes with stable types

If a compact mode needs a different result shape, prefer a named field with a stable type (for example, `filter_ids: string[]`) over records padded with irrelevant optional fields. If a heterogeneous response cannot be expressed cleanly by the platform, use a separately named tool rather than corrupting types or silently dropping useful data.

### Remove nonessential work

Skip MIME traversal, attachment inspection, file staging, HTML parsing, or downstream enrichment when the public tool cannot return the result. Keep telemetry asynchronous and metadata-only; it must not sit on the response critical path.

## 4. Treat contract changes deliberately

Before releasing, classify the change:

- **Compatible:** additive fields, new opt-in mode, smaller upstream projection with identical public result.
- **Behavioral:** changed default, cap, ordering, pagination, or error semantics. Document and test it.
- **Breaking:** removed/renamed fields, changed types, or changed response shape for an existing request. Version or introduce a new tool unless the owner explicitly accepts the break.

"Optional" does not mean harmless when a platform serializes it on every record. Measure the actual MCP envelope.

## 5. Verify at four layers

1. **Local/unit:** syntax, validation, and tests for default, clamp, invalid input, and typed results.
2. **Server/schema:** validate code; refresh action/schema bindings after releases; ensure mappings reference current inputs and outputs.
3. **Live functional:** exercise default, compact/extended, over-ceiling, malformed input, and a representative real fixture. Confirm types in the serialized MCP response.
4. **Operational:** repeated warm trials, a bounded concurrency/degradation check, authorization/caller-scope checks, and rollback availability.

For every optimised tool, publish a concise before/after table that separates caller-visible bytes from upstream savings and includes the representative workflow's call count, completion result, and total cost. Do not claim an upstream projection win as a public token win unless the MCP envelope changed.

## 6. Release safely

Use an explicit Development-first sequence:

1. Record the active asset IDs/versions and rollback target.
2. Validate source and schema before external mutation.
3. Update the smallest relevant connector/function/recipe set.
4. If the platform requires stopping an asset to publish, stop only the named assets, publish, restart, and confirm running state.
5. Re-run live tests after restart; platform schema caches frequently outlive source changes.
6. Record the release version, measurements, residual tradeoffs, and rollback point in the project evidence and issue tracker.

Never use a performance task to weaken caller isolation, confirmation policy, artifact TTL/cleanup, mutation idempotency, or log masking. Keep production changes separately authorized.

## Common traps

- Measuring one cold call and calling it a latency result.
- Editing a stopped/archive clone instead of the route served by MCP.
- Adding a schema field but forgetting the recipe/function mapping.
- Mapping an array through string interpolation and returning JSON-looking text instead of an array.
- Returning empty/null properties for every compact record.
- Reducing a list to IDs when callers normally require enough context to choose the right ID, then calling the result an efficiency win.
- Moving useful default detail behind extra calls without measuring the complete user/LLM workflow.
- Exposing a limit override with no hard ceiling or no applied-limit feedback.
- Making a read optimization silently change a write path or authorization boundary.
- Treating client-side request serialization as server-side concurrency evidence.

## Completion checklist

- [ ] Live route, active version, and caller authorization are identified.
- [ ] Before/after warm measurements are comparable and include bytes/tokens.
- [ ] The actual upstream over-fetch or work has been removed or bounded.
- [ ] Default behavior remains useful and predictable.
- [ ] Overrides are explicit, read-only where possible, and hard-capped.
- [ ] Public output preserves types and omits meaningless placeholders.
- [ ] Invalid/over-ceiling requests are truthful and non-mutating.
- [ ] Local, schema, live, and operational checks pass.
- [ ] Rollback target, evidence, and residual tradeoffs are documented.
