# Workato Developer API — dead-end ledger

Standing rule (Josh, 2026-10-13): EVERY 404 or permanent failure on a Workato Developer API
endpoint gets recorded HERE the same session — endpoint + exact error + what was tried — so no
session ever re-probes a known dead end. Check this file BEFORE probing an undocumented
endpoint. Append new dead ends at the bottom; date each line.

## Confirmed 404 / unsupported (do NOT retry)

- 2026-10-13 `GET /api/recipes/:id/snapshots` — HTTP 404 API not found. No snapshot-history
  endpoint on the Developer API; recipe version diffs are not retrievable this way.
- 2026-10-13 `GET /api/custom_adapters/:id` — HTTP 404. Custom-adapter (Connector SDK) objects
  are not addressable here.
- 2026-10-13 `GET /api/custom_adapters/:id/versions` — HTTP 404. No version-history endpoint;
  connector version diffs are only available via the Connector Builder (UI or the AIRO
  connector_builder_* tools: latest code + unreleased diff — no released-to-released diff).
- 2026-10-13 `wt manifests list` — not a command (valid ops: assets, get, create, update,
  delete). No manifest-list operation exists; track manifest IDs in tickets/mirrors.

## Known-behavior (not 404, but a repeated-trap ledger)

- `wt dt create-record` with the NUMERIC table id silently no-ops (returns a wrapper with no
  error, writes nothing). Always pass the table UUID (resolve via
  `GET /api/data_tables?project_id=...`).
- `wt dt query` with the numeric table id → HTTP 400 "failed to parse path ... string_uuid".
  UUID only, same as above.
- `GET /api/data_tables?project_id=` returns max 100 per page; key tables (147343
  workspace_semantic_registry, 147278 workspace_plans, 148725 workspace_plan_authorizations)
  live on page 2-3.
- Data-table `query` raw output shape: `{"data": [[meta_cells, field_cells]]}` — nested arrays,
  columns keyed by field_id; use the `schema` block in the same response to map. Non-raw
  (`wt dt query` without --raw) has `rows`-style output but filters need COLUMN NAMES, and a
  wrong name → HTTP 400 FIELD_NOT_FOUND.
- Jira comment with `commentVisibility` role Administrators → HTTP 400 when the service account
  isn't in that project role; post without visibility instead.
- `GET /api/connections` returns a BARE JSON array (not `{"items": ...}`) and IGNORES
  `per_page`/`page` — one call returns the whole catalog (965 rows, 2026-10-27). Parsers
  expecting an envelope silently see only the first element if they scan for the first `{`.
- `GET /api/recipes` DOES honor `per_page`/`page` AND accepts a server-side `folder_id`
  filter (returns `{"items": [...], "count": N, "page": P}`; list items embed the full
  `code` DSL + `config` connection bindings — no per-recipe fetch needed).

## AIRO MCP data-table row access (2026-10-13, BSYS-29656)
- `data_table_query` on a data table: the query route is NOT deployed — returns `HTTP 404 {"message":"API not found"}` (tool suggests docs_get guides:workspace-query; doc doesn't help).
- `lookup_table_row_list` against a DATA table id: `404 Not found` (lookup-table API only; data tables aren't lookup tables).
- `data_table_query`/`wt dt query` reject NUMERIC table ids ("failed to parse string_uuid: found 6") — must use the table UUID from data_table_get.
- **Winner:** `wt dt query <uuid> --where 'col=val' --select a,b,c` (Workato Toolbox CLI records API) — read AND `create-record`/`update-record` work fine, including `reviewed_at: null` / `""` on date_time fields.
- Note: AIRO `recipe_builder_set_input_field` storing code_input.data mappings as LITERAL f"..." strings when set via whole-object value — set them via individual `code_input.data.<field>` paths so they compile as formulas.

## Export manifests via Developer API (2026-10-13, BSYS-29656)
- No export-manifest endpoints on the Developer API (`/api/v2/export_manifests*` → 404; `/export_manifests/<id>` is the SPA page, not an API). Manage via `wt manifests` CLI or UI (`https://app.workato.com/export_manifests/<id>`).
- `wt manifests update` CANNOT change `folder_id` ("Folder cannot be changed") — delete + recreate.
- **TRAP:** `wt manifests assets <subfolder>` resolves to the PROJECT ROOT folder and lists account properties — do NOT use that resolved id as the manifest `folder_id`. The manifest's source folder must be the folder the ASSETS live in (here: 35404884 Automation); wrong folder = every row "Not found" in the UI.
- 2026-10-29 **RESOLVED PATH (complement to the custom_adapters 404s above):** `GET /api/custom_connectors/:id/code`
  (no .json suffix) returns the FULL saved custom-connector source on both wt profiles (dev + josh-prod).
  Used for the Gmail hotfix port to byte-diff dev v129 vs prod v1 cheaply - no connector_builder session
  transcription needed. `/api/custom_adapters/:id` and `/versions` remain 404.
