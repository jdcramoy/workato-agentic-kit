---
name: airo-mcp-playbook
description: >-
  Gotcha catalog and efficiency guide for the AIRO MCP server (Workato's
  platform MCP, connected as ace2092e-9968-4d19-abaa-54f41c461aff — tools
  prefixed recipe_builder_*, genie_*, data_table_*, blueprint_*, mcp_server_*,
  knowledge_base_*, collaborator_*, job_*, property_list, docs_get,
  asset_url_get). Use whenever calling ANY AIRO MCP tool, not only during a
  full skill build — editing or pushing a recipe, working with data tables,
  writing Ruby formulas, wiring blueprints, using project properties, or
  touching Genie config. Covers general AIRO/Workato platform behavior only
  (no connector-specific quirks): confirmed silent-failure bugs
  (data_table_update wipes rows, dynamic table_id/genie_id drop data or
  break associations, datapill exports showing sample values as if hardcoded,
  session_id collisions between recipe_builder and genie tools, legacy
  workato_genie migration traps, recipe_builder session staleness after
  push) plus efficiency practices (verify via recipe_get not the session
  cache, full clickable Workato URLs, Always Validate). Complements
  workato-skill-builder (the build-to-UAT lifecycle SOP) by covering traps
  in any AIRO interaction, including ad hoc one-off tool calls outside a
  full build.
---

# AIRO MCP Playbook

AIRO exposes ~90 Workato platform tools. Its own instructions say to lead
with `docs_get(id="guides:overview")` when a workflow isn't obvious, and to
verify an asset with its `*_get`/`*_list` tool before mutating it — follow
both. This skill is not about what the tools do (they're self-describing);
it's the traps and efficiency practices that cost real rework when
forgotten. Everything here is general to the AIRO/Workato platform — none
of it is specific to any one connector (Workday, Google, Zoom, etc.).

## Scope boundaries

- ✅ Any direct call to an AIRO MCP tool: recipe edits, data tables, Ruby
  formulas inside a recipe, blueprints, project properties, Genie wiring,
  MCP server config.
- ✅ One-off / ad hoc AIRO operations, not just full skill builds.
- ❌ Does not cover the full planning, build, test, repair, and release-handoff
  lifecycle — see `workato-development-playbook`, plus
  `workato-skill-builder` for recipe, Genie, and MCP construction.
- ❌ Does not cover connector-specific behavior (Workday, Google Drive,
  Zoom, etc.) — those live in their own connector-specific references.
- ❌ Does not cover consuming an already-built Workato MCP tool as an
  end-user client (just call it).

## Non-negotiables — read before touching these tools

These guardrails prevent silent data loss or wrong-identity data resolution. The
tool call looks like it succeeded; the damage surfaces later, elsewhere.

1. **Never call `data_table_update`'s `columns` param on a table that has
   rows.** It silently nulls every cell and regenerates every field_id, even
   on untouched columns — row count survives, data doesn't. Tell the user
   the exact columns needed and have them add it manually in the Workato UI.
2. **Never make `table_id` dynamic on `add_record`/`update_record`.** Workato
   can't resolve the column schema at push time and silently drops the
   entire `parameters` payload. (`get_records`/search filters are unaffected
   — dynamic `table_id` is fine there.)
3. **Never make `genie_id` or other asset-association picklist fields
   dynamic** (e.g. via a project property) — even the correct ID value fails
   to register the platform-level association. Keep these literal.
4. **Verify VUA after identity-sensitive pushes.** The original reset to the
   service/ISU connection was confirmed resolved on 2026-08-05, but later
   personalized-recipe pushes showed intermittent drift. Check the saved
   "End user's connection" mode through the UI or another authoritative
   surface; repair and retest caller scoping only if drift is observed. Do not
   re-select blindly after every push. New environment imports still need
   their intended connection configured.
5. **Don't trust `recipe_builder_pull`'s DSL export for field mappings.** It
   can render a datapill as its resolved sample value (looks hardcoded).
   Verify against the recipe UI or a real `job_get` trace before concluding
   a field is unmapped or hardcoded.

Full detail, root causes, and repro context for each: `references/known-bugs.md`.

## Efficiency checklist

- Lead with `docs_get(id="guides:overview")` when unsure of a workflow.
- Verify before mutating: read the asset first with its `*_get`/`*_list` tool.
- For an MCP server, verify VUA configuration and behavior with the caller
  available to this session. One caller cannot prove cross-user access: record
  that limit and give a teammate concrete identity cases to run from their own
  client before launch. Do not demand a second account for local agent testing
  or claim the team case passed without evidence.
- Preserve IDs/handles/URLs exactly as returned; pass explicit IDs into
  read/update/link calls instead of re-deriving them.
- **Always Validate**: prefer an authoritative runtime lookup over
  persisting a denormalized copy.
- **Full clickable Workato URLs, every time a recipe/flow is named** — not
  only when asking the user to test it, and not only on first mention.
  Resolve with `asset_url_get`: `https://app.workato.com/recipes/<id>` (or
  `/job/<job_id>` for a job run).
- After any push where a filter/mapping/scoping field's correctness
  matters, do an independent `recipe_get`/`recipe_builder_pull` — several
  bugs above only reveal themselves this way, never in the pre-push session.
- No tool creates/sets project properties (`property_list` is read-only) —
  they're manual-UI-only, and lookups are exact-match case-sensitive. Always
  confirm the created name via `property_list` before relying on a binding.

## Data-table rows and other AIRO gaps — use `wt`

- `data_table_query` 404s in this workspace ("API not found" — the WorkAI
  query route is not deployed; `data_table_list`/`data_table_get` work).
  Do not retry it. Query data-table rows with
  `wt dt query <table_uuid> --where 'col=val,...' --order '$created_at'`
  (`~/.local/bin/wt` — reuses the Dev CLI keychain token). Output is
  schema-mapped row objects; date columns need `--timezone-offset`
  (default 0); `--limit` ≤ 200/page, page with `--continuation <token>`.
  This is the ONLY external row-access path — `www.workato.com` API
  endpoints return schema only.
- `wt` also covers Developer-API capabilities AIRO lacks: export manifests
  + package export/import (dev→TEST/prod promotion without the browser),
  recipe delete/copy/force-run/versions/job-counts, job repeat/cancel,
  connections CRUD, lookup-table row writes, project-property upserts,
  folder/project CRUD. `wt api METHOD /api/...` is the raw passthrough.
  Full gap matrix + wire formats: `~/.claude/knowledge/domains/workato-platform.md`.

## On-demand test runs for scheduled recipes — NEVER wait for the next tick

- When a scheduled recipe's run is needed NOW (validation after an edit, or
  forcing a data-pipeline pass), do NOT wait for the schedule to fire and do
  NOT poll: **stop the recipe → click Test (recipe page dropdown/caret, or
  row-select a prior job → "Repeat N job") → review the job trace → start
  the recipe again.** (Josh directive, 2026-10-02.)
- The CLI start/stop silently no-ops on some platform recipes — verify via
  `recipe_get` (Running flag) or the page's Active/Inactive banner, and
  start via the Orca browser "Start recipe" button when the CLI no-ops.
- Editor Test pre-validation blocks on warnings that are runtime-harmless
  (dynamic foreach-item pills on custom-code array sources flag
  `DatapillInvalidPath` in the UI's static check). If the warning class is
  known-harmless, start via the recipe page instead of the editor's
  Test button. If Start itself is blocked, the pills must be made static —
  flatten dynamic foreach loops into single-proposal flows or declared lists.
- Never click the **cloud-icon dropdown** on a recipe page for testing — it
  is the **Deploy-to-TEST environment** wizard (deploy flow with all assets
  pre-selected), not a recipe test.

## Genie MCP tool-picker safety — mandatory

- Treat the Genie **Add tools** picker as a full replacement set, never as an additive control. Do not search for one tool, select it, and save assuming existing tools remain: a filtered one-tool view can persist as `(1 of 1)` and remove every other selected MCP tool from the Genie.
- Before opening the picker, record the Genie’s current selected count and complete intended tool list. Before Save, clear search, verify the full candidate count, verify every intended tool is selected, and explicitly verify intended exclusions. If the UI cannot enumerate prior tools, cancel; never save.
- Snapshot the server tool inventory and Genie selection/configuration before wiring changes. `mcp_server_get` proves server membership only; it does not prove Genie selection.
- If legacy `workato_genie` tools show **Incompatible**, do not repair this through the Genie picker. Use clone-first `workato_skill` replacements from immutable snapshots, structural diffs, VUA verification, and actual MCP tests before attachment; retain originals until cutover is proven.

## Reference files

- `references/known-bugs.md` — full catalog of confirmed AIRO/Workato
  platform bugs beyond the five above: recipe-builder session mechanics
  (stale session after push, step renumbering, declare_variable staging,
  trigger-swap failures, while_condition removal), legacy `workato_genie`
  migration, `session_id` collisions between `recipe_builder_*` and
  `genie_*`, blueprint link ordering, project properties, and
  multi-copy/packaging gotchas (exports missing recipe assets, duplicate
  dev/prod copies). Load when doing recipe-builder session work, migrating
  a legacy skill, wiring blueprints, or importing/inspecting a Workato
  package.
- `references/ruby-dsl.md` — Ruby `ruby()` formula restrictions (no
  `.size`/`.dig`/`||`, no multi-line assignment, no string interpolation).
  Load when writing a `ruby()` formula in any recipe step.
- `references/conventions.md` — Jira/Atlassian MCP formatting notes (`#`
  renders as a heading not a list item; `createJiraIssue` description
  double-escaping) that recur when this work involves filing or updating
  tickets alongside an AIRO build. Load when writing to Jira as part of the
  same task.
- `references/token-efficiency.md` — the detailed Claude-side token-efficiency
  playbook retained from the pre-migration Claude skill. Load for multi-step
  builds, investigations, and push/test/fix loops.
- `references/delegation-and-jira.md` — cost-aware delegation gates, phased
  execution structure, and milestone-only Jira update guidance. Load when
  planning multi-phase AIRO delivery.

## Quick trap table

| Trap | Symptom | Fix |
|---|---|---|
| `data_table_update` columns | Cells nulled, field_ids regenerated | Never on populated tables — manual UI |
| Dynamic `table_id` on add/update_record | Parameters silently dropped | Keep literal; dynamic OK on get_records |
| Dynamic `genie_id`/asset picklists | Platform association breaks | Keep literal, always |
| VUA connection persistence regression | Wrong-identity data | Expect persistence; verify after identity-sensitive pushes and re-select only if drift is observed |
| Datapill sample-value export | Mapped field looks hardcoded | Verify in UI / job_get, not the export |
| Stale session after push | Edits fail | Re-pull before further edits |
| Trigger connector swap | Schema stuck, InputFieldNotInSchema | Delete + rebuild trigger from scratch |
| `declare_variable` schema+data together | DatapillInvalidPath | Schema first, data separately |
| `session_id` reuse across tool families | 414 URI Too Large / Genie not found | Dedicated session_id; seed with a `_get` first |
| Ruby `#{...}` interpolation | Formula rejected | Use `+` concatenation |
| Jira leading `#` | Renders as H1 | Use `1.`/`-`/`**` |
| `createJiraIssue` description | Literal `\n` and punctuation | Create bare, then `editJiraIssue` the real description |
| AIRO push on a VUA/personalized recipe | Intermittent loss of "End user's connection" (base identity used) | Verify saved mode after identity-sensitive pushes; repair only observed drift, then retest caller scoping (seen 2026-09-11) |
| Custom-connector RUC "connections unavailable" | MCP calls fail pre-dispatch, no job created, RUC exists + authorized | Password-type connection fields are stripped from runtime user connections unless the SDK field sets `preserve_in_runtime_connection: true` (client_secret needs it for OAuth token exchange). Existing RUCs keep stripped fields — re-consent after the connector release |
| Recipe `personalization` flag | Recipe runs as base/ISU identity | It's the "End user's connection" UI card; serialized as `personalization: true` on the config entry; not in any public REST endpoint — flip via package export → edit → import (recipes stopped), verified by re-export |
| Inner array in a mapped comprehension | `label_ids` arrives as stringified list | f-string wraps stringify arrays; use `ruby("bindings.v", bindings={'v': item['field']})` passthrough |
| Connector release via connector_builder | — | `connector_builder_*` tools ARE live on the AIRO server (2026-09-11); save creates the new current version. Still verify VUA personalization on recipes after any recipe push |
| `data_table_query` | 404 "API not found" (route not deployed this workspace) | Use `wt dt query <table_uuid>` — schema-mapped rows, one external path to data-table records |

For the fuller narrative version of everything in this skill, plus additional
context and incident history, see `{{HOME}}/Documents/Claude/AIRO-MCP-Reference.md`.
