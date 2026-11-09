# Workato Platform — domain knowledge

Cross-project Workato/AIRO knowledge. Procedural SOPs live in global skills
(airo-mcp-playbook, workato-skill-builder, workato-development-playbook,
workato-recipe-control, verify-recipe, workato-browser-editor, handoff) —
this file holds platform FACTS and model knowledge they don't repeat.

## Ops visibility — local failure dashboard (built 2026-10-08)

Josh's blind-spot closer (grill-gated: auto-derive scope / 15-min pulls +
nightly autopsies / swallowed errors IN v1 per his ruling "graceful-for-UX
errors still mask real defects" / standalone dashboard). Home:
`knowledge/ops-visibility/` (CONTRACT.md = the spec; records-*.jsonl;
diagnoses.jsonl; config.json). Scripts: `scripts/ops-collector.py`
(derive-scope + collect; wt jobs list/get via josh-prod/josh-us; sig =
sha1(env|recipe|normalized-error)[:12]; 24h first-sweep window; max 40
recipes/tick; swallowed = static error-block scan + rotating trace
sampling, max 3 flagged recipes × 3 succeeded jobs/tick, conservative
flag-only-on-error_details) + `scripts/ops-server.py` (127.0.0.1:8771
KeepAlive daemon: serves generated dashboard, POST /api/triage →
knowledge/triage/queue.jsonl finding `ops-<sig>` idempotent-on-open-slug +
marks record sent-to-triage in place, /api/autopsy → autopsy-requests.jsonl,
/api/refresh → out-of-band tick) + `scripts/ops-dashboard.py generate`
(self-contained dark HTML, count tiles, prod-first sort). Fleet: daemon
plist com.josh.fleet.ops-visibility (15-min in-process loop) + ops-autopsy
job 06:07 (top-5 undiagnosed prod → workato-autopsy → diagnoses.jsonl,
diagnosis-only, 40-min bound). First live records 2026-10-08: Extract
Design System 82090477 prod — Google 403 permission (55 lifetime failures)
+ 404 presentation-not-found, both /triage'd via the dashboard API.
Integrates WITH workato-health.py (owned/hypercare semantics stay there;
shared sig-space prevents double cards — health monitors counts, ops-visibility
carries job-level detail).

## Owned-asset health monitoring (built 2026-10-08)

Self-discovering monitoring for everything the harness builds/touches:

- `asset-fingerprint.py` — build-ledger `airo-mutation` rows →
  `workato-health/owned-registry.json` (47 recipes day one). Designations:
  new (first touch ≤7d), **hypercare (prod touch ≤14d)**, warm (≤3d),
  stale (>30d). Rebuilds instantly — build tonight, monitored tonight.
- `workato-health.py` — bounded sweep: ONE `wt recipes get <id> --raw`
  per asset (that endpoint carries running/job_failed_count/last_run_at/
  stop_cause), cap 50/run, hypercare+new first, ~22s for 47. Verdicts:
  ok / stopped (stop_cause set — ALARMS) / new-failures (failed-count
  increase vs state.json — ALARMS) / not-running (silent — usually
  deliberately retired builds) / unverifiable. Alarms → triage queue
  (`recipe-health-*` findings, /triage to verdict) + bus thread
  `recipe-health` + morning-digest. Fleet job `com.josh.fleet.health`,
  hourly, heartbeat job=workato-health.
- Profiles: `--profile josh-us` (dev ws 3535597) / `--profile josh-prod`
  (prod ws 3535598). `wt recipes health` endpoint is a 404 (login-walled
  Performance Copilot surface) — `recipes get` is the working health read.
- Watchdog SOP has ownership priority: owned/hypercare failures slug
  `owned-` prefix, ranked first.

## Platform command: `prod-bypass` (guardrails v1.0.0, 2026-10-07)

The explicit, time-boxed bypass for ALL prod-write gates (hook 13 CLI/WT/
curl/Orca confirms, the push-risk gate, and the permissions.ask layer for
prod MCP writes). Terminal command (not a Claude command):

- `prod-bypass on 30m|2h` — gates off for the window; expires by itself
- `prod-bypass off` — end it early
- `prod-bypass` — status (remaining time)

While active: status band shows "⚠️ PROD BYPASS ACTIVE"; every write is
audit-logged as PROD-WRITE-BYPASSED in ~/.claude/workato-audit/prod-writes.log
(the bypass is a convenience, never an erasure). Hook-side takes effect after
/reload-plugins; the settings.json ask→allow swap takes effect next session.
Verify first use: the audit log must show BYPASSED lines.

## Environment topology

- Two AIRO MCP servers: DEV (default for everything) and PROD (live; every
  call prompts; writes need explicit Josh confirmation + bold warning).
  Ambiguity about workspace = DEV. Never allowlist prod write tools.
- **Two CLI instances (2026-10-07):** `workato` = DEV (profile `josh-us`,
  workspace 3535597); `workato-prod` = PRODUCTION (profile `josh-prod`,
  workspace 3535598 "Environment Production"). The wrapper reads the prod token
  from the keychain and prints a red PROD banner to stderr.
- **Two WT instances:** `wt` = DEV; `wt-prod` = PRODUCTION. `wt-prod` exports
  `WORKATO_PROFILE=josh-prod` so every subcommand targets prod (wt's `--profile`
  flag only exists per-subcommand, so env is the uniform mechanism), and wt
  prints a PROD banner on stderr.
- **Credential store:** macOS keychain, service `workato-platform-cli`,
  account = profile name (`josh-us` = dev, `josh-prod` = prod). The prod token
  is NOT in any shell profile and not in the ambient environment.
- **Guard:** guardrails hook 13 gates EVERY prod write on every surface (CLI,
  WT, raw http carrying the prod credential, Orca on prod urls) with a confirm
  dialog, fail-closed on dismissal. The AIRO prod MCP keeps its own
  permissions.ask gate.
- **Trap:** the workato CLI prefers `WORKATO_API_TOKEN` over keychain, and the
  ambient shell exports the DEV token, so any prod invocation must override the
  env var (the wrappers do). `wt` was patched so an explicitly targeted profile
  wins over the ambient env token — without that, `wt --profile josh-prod ...`
  would silently run as dev.
- Projects are folder trees; "Functions" folders hold callable recipe
  functions; callable functions must be RUNNING to invoke (WRF00409).

## Platform behavior model (learned the hard way)

- Recipe-builder push on a RUNNING recipe fails — stop first (CLI stop;
  CLI start/stop silently no-op on some platform recipes → verify with
  recipe_get Running flag; Orca browser Start button is authoritative).
- Editor (UI) start/test validation is STRICTER than runtime: it hard-blocks
  on (a) dynamic foreach-item pills from custom-code array sources, (b)
  records[0] pills inside ruby() bindings. Runtime resolves both fine.
  Fixes: flatten to static-pill flows (single-item output, declared lists);
  bind the array and index inside the ruby expression.
- code_input.data values set with the plain setter store the ruby(…) text as
  a LITERAL string — silent data poisoning. Always use
  recipe_builder_set_input_field_v4_mode mode="ruby".
- try/catch + if/elsif/else chains are atomic to builder moves; position
  means insert point and can append at the end of the containing block;
  pills auto-update on renumber.
- Data-table schemas are immutable: column evolution = new versioned table +
  migration recipe. Column→field-ID maps come ONLY from data_table_get
  (builder schema views can mislabel/swap columns). data_table_update's
  columns param wipes populated tables (never use).
- data-table REST (query/create/delete) is internal-runtime only — not
  exposed to external API callers; bulk writes go through recipes
  (create_records_batch) driven by Test runs.
- Recipe ruby formulas: restricted subset (no Digest, no Time.now — use
  `now`; no #{} interpolation — use + concat; .length/.present?/.match? OK;
  bindings must be plain pills, no BinaryOperation; no bare return in
  invoke_custom_ruby_code — final-expression or error()).
- Datapills flow forward only (a step cannot reference a later step).
- Workato ruby() bindings values must be plain datapills (no BinaryOperation
  expressions); concatenate inside the expression.
- MCP reconnect (client-side) never re-requests OAuth scopes: scope changes
  require revoking the connection and a true consent screen. Org-level scope
  stripping is fixed in Google Admin Console → API controls (client as
  Trusted; find by OAuth client ID — name search only finds configured apps).
- Generation/coherence UX ruling (Josh, 2026-10-03): "tie goes to the user" —
  a stale caller checksum is a cache hint, never a rejection trigger;
  confirmed-commit generation binding is the only hard staleness check
  (protects what the user confirmed). Never re-tighten coherence equality on
  serving paths.
- On-demand testing of scheduled recipes: NEVER wait for the next tick —
  stop → Test → review → start. The recipe-page cloud-icon menu is the
  Deploy-to-TEST environment wizard, NOT a test affordance.

## Workato UX surfaces (browser)

- Orca browser is the authenticated Workato surface (stays signed in); never
  Playwright for Workato. Real clicks via `orca find --locator text`; JS
  .click() no-ops on React controls; recipe canvas scroll container is
  `.recipe-steps-canvas`.

## Canonical references

- Narrative AIRO reference: ~/Documents/Claude/AIRO-MCP-Reference.md
- Connector releases: ONLY via signed-in browser editor (Upload control =
  icon only; never SDK CLI/package import for release).

## Recipe-function vs Skill calls (confirmed 2026-10-02, BSYS-28312)

- `workato_recipe_function.call_recipe` accepts ONLY true recipe functions
  (recipes whose trigger is `workato_recipe_function.execute`). Recipes with
  a `workato_skill.start_workflow` trigger — including every Genie skill —
  fail start validation: "Recipe function with the id specified doesn't
  exist". To reuse a skill's logic from a recipe, call the underlying
  connector action directly and replicate its normalization/filter/cap.
- On a `call_recipe` step, AIRO resolves only `job_id`/`job_url` pills —
  the callee's result schema is NOT imported design-time. Datapill
  warnings appear but push succeeds; at runtime the result object does
  carry the callee's `workflow_return_result` keys. Reference array
  outputs through `ruby("bindings.x.to_json", bindings={...})` bindings.
- f-string (`f"{...}"`) rendering of an ARRAY pill into code_input.data
  yields Ruby inspect (`{"k"=>"v"}`), not JSON — JSON.parse then fails
  ("434: unexpected token"). Scalars are fine. Always bind arrays with
  `ruby("bindings.x.to_json", ...)` and have the snippet accept both
  native Hash/Array and JSON strings.
- Test Recipe on a skill trigger: the start dropdown toggles the primary
  button to "Test recipe" and opens an "Add trigger data" modal whose
  fields are CodeMirror editors. `orca fill` on the snapshot textbox ref
  does NOT reach CodeMirror; instead click the ref (real click) then
  `orca type` (verify value — it can double-type; when the CodeMirror
  API is exposed after focus, `e.CodeMirror.setValue(...)` is exact).
  Submit via the modal's "Test recipe" button; confirm the run by the
  new `is_test: true` job through the API.
- WQL `businessProcessTransactions` is the proven discovery source for
  COMPLETED business processes (worker-scoped: add `worker IS NOT NULL`).
  Status vocabulary is `Successfully Completed` / `Rescinded` / `Canceled` /
  `Denied` — filtering on `= 'Completed'` silently returns 0 rows (valid
  source, wrong value). `approvedByWorkers` returns JSON
  `[{descriptor,id}]` of actual acting approvers right in the row — use it
  for approval-chain resolution instead of SOAP Get_Event_Detail.
  `dateAndTimeCompleted` is absent until terminal, so its presence = final.
- When a WQL response has ZERO rows, the `total` field is ABSENT — an
  if-condition evaluating `total > N` crashes the whole recipe with
  "missing field value". Guard with `total present AND > N`.
- Recipe functions MUST be in "running" state to be callable
  (`Can't call a stopped recipe`, WRF00409) even though they have no
  trigger. Start FUNCs after creation, not just the calling RECs.
- **Start-refusal ≠ stop (third state):** `recipes start` can fail with
  `config_errors: [... "unconnected" ...]` when a step's connection has no
  OAuth grant, while `recipes get` still reports `running: false` —
  indistinguishable from a deliberate stop. Triage order: (1) running
  flag, (2) if a start attempt returns config_errors, read the connection
  id from the error and check connection state BEFORE any recipe-side
  theory. Start-blocked recipes need the connection owner (OAuth =
  identity work = Josh gate), not a restart loop. (Born 2026-10-23:
  sweeper 83291436 restart refused on pilot Slack connection 22364458.)
- `data_table_update(columns=...)` regenerates EVERY business-column
  field_id (system Record-ID field `11fbe9a6_…` stays stable). Recipes
  referencing old ids keep silent dead mappings — rewire all table steps
  and re-set `table_id` on each step to refresh the cached schema.
- Workato scheduler minimum interval is 5 minutes (`* * * * *` fails
  START validation with "minimum interval ... 5 minutes", not push).
- AIRO `set_foreach_source` has mangled a pill name once
  (`parse_json_v2_4` → `rse_json_v2_`); always read the rendered DSL in
  the set_input_field response.
- Ruby formulas: `pluck('key')` and `.join(', ')` ARE allowlisted (array
  projection without blocks); `JSON.generate` is NOT — use `.to_json`.
  `"\n"` literals inside ruby() values collide with the DSL wrapper's
  quotes — put newlines in f-string values as `\\n` escapes instead.
- `declare_variable` output pill `['value']` only registers after `type`
  is set; set name+type first, then value, or downstream steps get
  DatapillInvalidPath.
- Product pattern (HR Genie): notification loops should skip sole-approver
  events (the actor already knows) — record a `SKIPPED_SINGLE_APPROVER`
  audit row instead of sending; chains of 2+ get the full participant list
  in the message.
- **STANDING ORDER — living manifest on every build (Josh 2026-10-12, NON-NEGOTIABLE).**
  A build/deploy BSYS ticket opens with the build; a living export manifest opens at the
  PROJECT-LEVEL folder in the same session; EVERY asset touched or created (recipe,
  function, table, skill, genie, MCP server, properties) enters the manifest AS IT IS
  TOUCHED, with its UI NAME, via platform-native rows; mirror to
  `<repo>/manifests/<BSYS-id>.manifest.json`; verify visually in the UI + at ZIP level
  before any ticket cites the manifest. Everything eventually promotes dev→prod — the
  manifest is how we never guess what we built. Enforced by the `manifest-guard` Stop
  hook. Full doctrine + gotchas: workato-development-playbook SKILL.md "The living
  manifest — STANDING ORDER" and manifest-hygiene.
- Export manifests (Recipe lifecycle management → Export) are UI-only —
  no AIRO tool or dev-CLI command creates them. Via Orca browser:
  export_manifests → New manifest → source-folder combobox (click chevron,
  type to filter, click the project ROW) → step-2 tree is virtualized:
  locate rows with a TreeWalker text-node search (not querySelector leaf
  filters — row labels have child elements), scrollIntoView, then REAL
  mouse clicks at getBoundingClientRect coords with **0.3 s between
  mouse-down and mouse-up** (down+up back-to-back silently fails to
  toggle checkboxes ~50% of the time). Snapshot element refs go stale
  after every re-render — re-snapshot before each ref click. Checking a
  recipe auto-checks its runtime dependencies (transitively — the Genie
  pulls its anchor/JSM skills and their properties); verify the final
  selection with a full checked-row audit before Create. Data tables
  default to "Include data" and the chip is not editable in the
  manifest view — note schema-only import in the Jira story instead.
- Export-manifest dependency closures are TRANSITIVE and FORCED: any
  selected recipe that calls `FUNC | Send Genie Event` pulls the HR Genie
  genie → every genie-attached skill → each skill's dependencies (JSM
  chain, audit tables). An asset can only be excluded from a package by
  removing it from the source of the chain (e.g. detach a not-ready skill
  from the genie with `genie_update skills_to_remove` BEFORE creating the
  manifest). Manifest selections freeze at creation: `Edit manifest` can
  add assets and uncheck rows, but dependency-included items render
  without checkboxes and `Update manifest` does NOT re-evaluate the
  closure against later platform changes — recreate the manifest instead.
  Workato export manifests cannot be deleted (no UI control); superseded
  ones can only be renamed (the pencil/editable-text rename often fails
  to commit — budget for living with the old name and recording
  supersession in the Jira story).
- Manifest refresh after source changes (e.g. post-build edits): the
  manifest page shows a "Some assets have been added or changed" banner
  with per-asset **"Updated"** badges. Path: **Review manifest changes →
  Edit manifest content dialog** — recipe version bumps clear automatically
  on **Update manifest** (package builds read CURRENT asset content at
  build time), but **newly added assets appear as unchecked "Added" rows
  that must be manually checked** (Watch the "YOUR MANIFEST CONTAINS"
  counts before/after). Update-manifest is sufficient when the dependency
  CLOSURE is unchanged; recreate only when the closure itself changed
  (lesson above). Properties rows: enabled checkbox; dependency-included
  rows: disabled (lesson above).
- In the Create-manifest dialog, native-setter textarea fills do NOT
  reach React state (Next stays disabled); only REAL keyboard events do —
  click into the field with the mouse first, then `orca type`. The
  source-folder tree-select accepts keyboard selection: click the
  control, type the filter, ArrowDown, Enter. Snapshot refs churn on
  every re-render — take a snapshot and use its refs within one step.
- Manifest dependency closure is ENFORCED at the platform level: recipes
  selected in an export manifest force their recipe-function callees
  (call_recipe targets), the callees' tables/properties, and the
  genie-attachment chain (genie → attached skills → KB) to stay selected.
  The dependency checkboxes render enabled but unchecking them does not
  stick — the selection recomputes and re-checks them. Connections are
  the removable class (environment-local). Net: a manifest's floor is
  changed-assets + runtime dependency closure; unchanged dependency
  assets import idempotently over their identical prod counterparts.
  Verified 2026-10-05 (HR Genie batch) after ~15 uncheck attempts across
  create + edit views.

- Project properties: **created only in the UI** — Project page → **Settings** tab → Project properties → "Add new property" (inline edit row; no AIRO tool creates them, `property_list` shows environment properties only, and the recipe-editor pill tree is read-only). UI mechanics (Orca): the two inline inputs accept JS `input`-event fills; the commit button has only `aria-label="Save row"` (no visible text — `orca find text` can't locate it; do a real mouse click at its `getBoundingClientRect`). The recipe **Edit button is disabled while the recipe is running** — stop first (that's also why a "click Edit did nothing" is a running-recipe symptom, not a React-click failure).
- AIRO `recipe_builder_pull`/`recipe_get` report an internal **Project ID** that differs from the UI project `fid` (same project, two identifiers — e.g. HR Genie dev: AIRO 15643451 vs UI fid 30275122). Don't treat the mismatch as two projects; project properties are project-scoped so only the identity matters, and the UI Settings page is reached via the UI fid.

- `set_condition` / condition LHS static validation ("**expression is unsafe**" at CLI start) is stricter than step formulas: **no `||`, no `!(...)` negation, no array literals** in condition expressions — even though the same constructs in step `ruby()` formulas are fine (and `include?` on strings IS fine in both). Don't hand-roll multi-clause Ruby ternaries in conditions; use the tool's own operand vocabulary instead (`equals_to`/`not_equals_to`/`contains`/`not_contains`/`present`/`blank`, multiple ANDed conditions) with plain datapill LHS — the tool normalizes them to safe DSL. Design branches so each condition needs only proven constructs.
- `recipe_builder_add_step` for **logic steps (if/elsif/else/foreach/stop) must NOT carry `connector`/`action`** — passing them attaches `provider`/`name` config the step type rejects; the recipe then fails UI start with "some steps haven't been setup correctly" / CLI start with "provider is not allowed for this step type". Removing and re-adding the step without those params fixes it.
- Workato project properties **cannot have a blank value** (inline editor rejects empty with a validation icon) — to model "unset", store a sentinel (e.g. `not-configured`) and gate the consuming logic on the value containing `@`.
- Recipe-function (trigger `execute`) recipes CAN be started via CLI normally; a "Running" recipe rejects AIRO `recipe_builder_push` with "Cannot edit recipe … because it is running" — stop first (CLI stop can lag/no-op on custom-schedule recipes; retry the stop and verify the Running flag via `recipe_list`/`recipe_get` before re-pushing).
- The Orca browser editor session can go **stale/obsolete** after AIRO pushes ("Your recipe has become obsolete… can no longer be saved or tested") and even hard reloads may keep rendering the stale cached DSL — trust `recipe_get` (authoritative) over the editor canvas, and reload the editor before any UI-side Test run.

## `wt` — Workato Toolbox (Developer API wrapper, built 2026-10-05)

`~/.local/bin/wt` (stdlib Python) closes the AIRO-vs-Developer-API gap. Auth:
`WORKATO_API_TOKEN` env, else reuses the workato-platform-cli macOS keychain
entry (service `workato-platform-cli`, account = profile name, e.g. `josh-us`);
profile/region from `~/.workato/profiles`. Profile resolution order is
`--profile` flag, then `WORKATO_PROFILE` env, then `current_profile`; when a
profile is explicitly targeted its keychain token wins over the ambient env
token. `wt-prod` wraps all of this for production (see Environment topology).
Universal escape hatch: `wt api METHOD /api/... [--query k=v] [--data JSON]`.

Gap matrix (AIRO MCP / dev-CLI v1.0.6 vs Developer API, verified live 2026-10-05):
- **Recipe lifecycle**: AIRO/CLI lack delete, copy, force-run, poll-now,
  reset-trigger, versions (+comment), connect (swap connection in stopped
  recipe), job-counts. `wt recipes <op>` covers all; CLI already does
  start/stop/validate.
- **Jobs**: repeat + cancel are API-only — `wt jobs repeat|cancel <recipe> --ids`.
- **Connections**: full CRUD + disconnect + picklist + runtime-user connections —
  `wt connections ...` (AIRO only lists by provider inside a builder session).
- **Lookup tables**: AIRO is READ-ONLY (list/lookup/row_list). API has full row
  CRUD + table create + batch delete — `wt lookup add-row|update-row|delete-row|create`.
- **Project properties**: API `GET/POST /api/properties` — `wt properties
  upsert` CREATES/UPDATES them. Supersedes the earlier "created only in the
  UI" lesson (that was true before the new CLI/API client era). `prefix` is
  required on GET /api/properties (400 otherwise).
- **Export manifests + packages**: AIRO has NOTHING; CLI has NOTHING; the API
  has full manifest CRUD (`/api/export_manifests*`) + package
  export/import/download — `wt manifests assets <folder>`,
  `wt manifests create --file m.json`, `wt packages export <manifest_id>`,
  `wt packages import file.zip <folder_id> [--restart-recipes]`. This replaces
  the painful Orca-browser manifest dance for the dev→TEST/prod promotion
  flow (manifest asset listing confirmed working with 200 + full dep graph).
  Browser still needed only for the UI's forced-dependency visuals.
- **Folders/projects**: create/update/delete — `wt folders`, `wt projects`.
- **Performance Copilot health** (`/api/recipes/:id/health`): redirects to login
  with this API client — privilege/plan gated; use browser.
- Wire formats: package import = `application/octet-stream` zip body to
  `/api/packages/import/:folder_id` with query `restart_recipes=true`
  (required if running recipes exist); manifest assets payload carries
  `deps`, `zip_name`, `checked` per asset (recipe/connection/lookup_table/
  workato_db_table/account_property/project_property/agentic_genie/...).
- **Data-table ROWS have a public API** (verified 2026-10-05) — supersedes the
  earlier "data-table REST is internal-runtime only" lesson. Record
  manipulation lives on a SEPARATE base URL, `https://data-tables.workato.com`
  (www.workato.com has only schema management: list/get/create/update/delete/
  truncate). Same API-client bearer token works. `POST
  /api/v1/tables/:id/query` body: `select[]`, `where` = `{"col": val}`
  equality shorthand (verified; `{"col":{"$eq":val}}` also parses), `order` =
  plain string field name (`"$created_at"` for system fields; the `-col`
  prefix and `{"col":"desc"}` hash forms are NOT accepted), `limit` ≤200,
  `continuation_token`, and `timezone_offset_secs` REQUIRED when a
  date/date-time column is filtered. Response rows are POSITIONAL arrays:
  `data[i][0]` = [$record_id, $created_at, $updated_at], `data[i][1]` =
  column values; `schema` mirrors both. Also on that host: POST
  `/tables/:id/records` (create), PUT/DELETE `/tables/:id/records/:record_id`,
  file upload/download link endpoints.
- AIRO's `data_table_query` tool 404s in this workspace ("API not found" —
  the WorkAI query route isn't deployed; `data_table_list/get` work fine).
  Don't retry it; use `wt dt query <table_uuid> [--where col=val]
  [--order $created_at]` which returns schema-mapped row objects.
- **AIRO push round-trip corrupts `invoke_custom_ruby_code` steps on EVERY
  push** (verified 2026-10-05, BTSUP-72246 build): each `recipe_builder_push`
  rewrites `payload_asset_type` to the option TITLE ("Define manually") +
  adds `snippet_document_static_asset="<REQUIRED FIELD PLACEHOLDER>"`;
  materializes `get_records` filter placeholders; and rewrites picklist
  VALUES to TITLES ("istrue"→"is true", the full Get_Organizations path→
  "Organizations"). The static check accepts it but the UI Test banner
  blocks. Workflow: build → push → re-pull → fix ALL degradations in one
  pass → push ONCE → test immediately with NO further pushes.
- **Loop-item pills require OBJECT list items**: a foreach over a
  string-list exposes only `foreach_3.foreach_meta` — the item pill is nil
  at runtime and `foreach_3['item']` fails DatapillInvalidPath. Map to
  objects (`[{email: e}]`) and reference `foreach_3['email']`.
- `project_property['Name With Spaces']` inside a `set_foreach_source`
  ruby() binding corrupts the emitted DSL (unterminated binding hash; UI
  flags "Errors in Trigger and step 2"). Route the property through a Ruby
  snippet step and foreach over its array output.
- **API-recipe auth header is `Api-Token: <key>`** — Bearer / X-Api-Key /
  raw Authorization / "Token token=" all 401 "access to this API has been
  disallowed" even with a valid key + assigned policy.
- API-platform provisioning split: collections + endpoints created via the
  UI wizard (or `workato api-collections create` from an OpenAPI spec);
  endpoint enable = `PUT /api/api_endpoints/{id}/enable` and requires the
  underlying recipe RUNNING; API clients + keys are API-creatable
  (`POST /api/v2/api_clients` auth_type ∈ token|jwt|oauth2|oidc; key token
  is returned in the create response). Client needs BOTH the collection in
  `api_collection_ids` AND a policy assigned (collection Clients tab →
  Policy "Not assigned" = every call 401s even with a valid key).
- Custom-cron triggers set via AIRO trigger config ("Custom schedule" +
  trigger_at) fail UI validation ("Trigger at: Invalid time format"; the
  Time unit dropdown resets to empty) — Minutes/N + trigger_at=0 validates
  and runs. Set the real cron in the UI editor at handoff, or leave an
  interval trigger in dev.
- **Data-table row-write payload shape** (found via docs.workato.com/en/workato-api/data-tables after 8 failed guesses): the body wraps fields in a `"document"` key, keys are field names or dollar-escaped field UUIDs:
  `PUT/POST /api/v1/tables/:id/records[/:record_id]` with
  `{"document": {"<field_name_or_: $uuid>": value, ...}}`.
  Everything else ("record"/"values"/"data"/"fields"/"row"/positional arrays,
  with either names or UUIDs) fails with a misleading
  `parse request payload error: Expected input type "CreateRecordRequest"`.
  Response echoes `data.document` as `[{field_id, field_name, value}]`.
  Base host `https://data-tables.workato.com`, Bearer workspace token.

## RULING (Josh, 2026-10-05): end-user credentials NEVER in long-running integrations

Josh explicitly withheld consent: "I do not consent to that... we do it right"
after the Consumer Endpoints roster sync was wired to HIS personal Slack
connection (19051772). Rule: any long-running integration uses a
workspace-owned service identity (Slack app bot / ISU), never an individual's
token — bus-factor + rebuild-on-departure risk. Personal connections are
acceptable ONLY for interactive/personal automations. Production-ready =
net-new bot, its own creds, follow the process. Temporary
poking other colleagues' connections to find one to borrow is ALSO banned
(khambat.dagha's + jorge.pradilla's tokens discovered via auth.test probes —
do not use them). The workspace-owned bot pattern: Slack app created from
manifest (human step — Slack console login), bot invited to the channel,
Workato connection created from its bot token.

## Cross-recipe function result pills (confirmed 2026-10-05, BSYS-28312)

- A synchronous `workato_recipe_function.call_recipe` result is wrapped
  under a `result` key: reference callee outputs as
  `call_recipe_N['result']['field_name']`. Without the `result` level the
  validator says Unknown data field and runtime resolves nil. With it,
  AIRO validation AND runtime AND UI start/test validation all pass.
- NEVER bind a bare whole-step reference (`bindings={"fn": call_recipe_N}`)
  in a ruby() call — design-time cannot compile it, so the runtime binding
  resolves nil silently. Bind sub-paths instead.
- Cross-recipe schema-attachment caveat: after AIRO push, the callee's
  result schema IS resolved by the validators (function registry), so
  `['result']['field']` pills validate fine even though get_input_schema
  shows only flow_id.
- UI Test button on a skill recipe whose params are CodeMirror fields:
  click the modal heading ("Add trigger data"), then Tab twice to reach
  the first field, then type. Verify with `.CodeMirror[i].getValue()`.
- CLI start/stop CAN silently no-op right after a browser-side start —
  always verify with recipe_get Running flag (or the connections/edges
  changing) before trusting either tool.
- Environment discipline (Josh, 2026-10-05, after a prod Slack incident): ANY conversational/agent surface reached through a signed-in session (Slack apps, Genies, agents) must be environment-verified BEFORE use — the signed-in corporate Slack workspace is production. All testing lives in the Workato BT AI workspace unless Josh explicitly declares a smoketest.
- Specifics for HR Genie testing: in the Workato BT AI workspace, the ONLY agent to test HR Genie against is **HR Genie 2** (Josh, 2026-10-05). Any other agent/genie is off-limits for HR Genie tests.

## Adhoc custom actions: schema compile limits + native-action preference (2026-10-05, BSYS-28312)

- AIRO recipe_builder does NOT compile schema-designer output schemas for a NEW
  `__adhoc_http_action` mnemonic. Any pill reference to that step (path or
  whole-step) fails start validation with `Unknown data field "Data"/"Adhoc
  http action <hash>"`, regardless of re-setting output, re-pushing, or
  update-connection repair. Adhoc mnemonics registered by an EARLIER save keep
  compiling fine (their pills resolve normally).
- Fix pattern: when a new HTTP read's pills must be referenced downstream,
  prefer a NATIVE adapter action over a new adhoc action. The workday_rest
  adapter ships `get_business_process_events(worker:, limit:, ...)`,
  `get_event_completed_steps`, etc. — list them with
  `recipe_builder_list_connector_operations` (no session_id arg) and inspect
  schema by placing the step (its input schema + output pills compile fully).
- Push → start may also null connection `account_id` on adhoc steps ("account_id:
  can't be blank"); repair with `workato recipes update-connection <recipe_id>
  --adapter-name workday_rest --connection-id <conn>` after every push.

## Workato test-dialog + trigger-driving mechanics (2026-10-05, BSYS-28312)

- `wt recipes force-run <id>` is scheduler-trigger-only (HTTP 422 for skill or
  any other trigger). To drive a skill recipe test: Orca browser → recipe page
  → JS-click the caret button right after "Start recipe" → real-click "Test
  recipe" → the "Add trigger data" dialog.
- The dialog's CodeMirror wrappers attach their JS instance ONLY after the
  field is focused (click heading label → Tab once → type). Then
  `element.CodeMirror.setValue(v)` propagates to React state; verify all
  fields with `.CodeMirror.getValue()` before submit. Field order maps by
  position, not by the heading you clicked — always read back all values.
- `orca find --locator text --value X --action click` can navigate AWAY
  mid-dialog (landed on custom_oauth_keys/new twice on recipe pages). Re-goto
  the URL and redo the flow; keep find-clicks to a minimum inside modals.
- Audit-trail habit: query the audit data table (by UUID, not numeric id —
  `wt dt query <uuid>`) after each test run; the rows give the
  decision/query-type/status triple that the masked job trace hides.

## Consumer Endpoints build traps (2026-10-05/06 night session)

- **Empty-source mass-mutation hazard:** a "succeeded" job whose Slack
  `conversations.members` call failed (`ok:false, channel_not_found`) fed an
  EMPTY member list into the departed-check, which then deactivated ALL 32
  roster rows. Any diff-based table sync MUST guard the "source returned
  nothing" case: pass the source count into the diff snippet and
  short-circuit with a `skipped_reason` when < 1. Fixed in roster sync
  82823992 step 12 (`member_count < 1` guard); normal path verified live.
- **recipe_builder_push refuses while the recipe is RUNNING** ("Cannot edit
  recipe ... because it is running") — new behavior on this workspace.
  Sequence: `wt recipes stop` → push → verify with recipe_get → start →
  force-run to verify.
- **set_input_field container poisoning:** `set_input_field_v4_mode
  mode:"json"` on a snippet's `code_input` container converts it to a STRING
  (subsequent sub-path sets fail with "Cannot set value in non-container").
  Recovery: `recipe_builder_set_input_field` with `value` as a real dict
  (schema values as JSON-encoded strings, data values as pill expressions)
  restores the container; then set each data sub-path with
  `mode:"datapill"` (v4 validates mode datapill for pill refs; `ruby` mode
  REJECTS bare pill refs). f-string pill refs render as
  `f"{step_x['field']}"`; for ARRAY sources into a string snippet input use
  the `ruby("bindings.x.to_json", bindings={...})` form — an f-string of an
  array datapill stringifies as Ruby inspect, not JSON.
- **Slack api.slack.com Regenerate buttons:** plain Show buttons sometimes
  work with `orca click`, but Regenerate modals need the full synthetic
  mouse dispatch (`['mousedown','mouseup','click'].forEach(dispatch
  MouseEvent {bubbles:true})` via orca eval, matched by
  `textContent.trim()==='Regenerate' && closest('form')` label context);
  orca click on the same button silently no-ops. Confirm modals die on
  focus loss — dispatch click → immediate single snapshot, no eval between.
  Slack now also shows an "Expiring Client Secret" after regeneration
  (separate rotating value; the classic static secret still works).
- **Workato custom OAuth profile secret update:** the profile Edit form's
  two password fields are ordered Client secret → Signing Secret (match by
  DOM order after the labels); native value setter + input event + Save
  works. Rotation does NOT touch the live xoxb token — running integrations
  continue; only future OAuth handshakes use the new values. Verify the
  env switcher says Development before saving (a prod-side save was the
  earlier 45993 accident).
- **Connection picker invisibility:** an authorized-but-new connection may
  not appear in the recipe-step connection picker ("No active connections
  matching") even in the right env — hand the direct URL
  `https://app.workato.com/connections/<id>` and Connect from the
  connection page itself.
- **Slack bot not in directory:** brand-new bot users are invisible to the
  slack-workato `search_users` active directory (even include_bots) — the
  bot's user ID comes free from the recipe job trace (`users.info` on the
  bot's own member ID during a sync run) or the channel join message.
- **Channel-not-invited failure mode is SILENT:** Slack returns
  `channel_not_found` (not a permission error) for a bot missing from a
  private channel; the recipe continues with an empty member list — pair
  with the guard above and check step-2 `ok` in job traces.

## MCP tool bindings are add-time-only — attach skills to their MCP server AT ADD TIME (2026-10-14, Josh rule)

There is NO API (developer API, wt, AIRO) to add a tool binding to an EXISTING
Enterprise MCP server: `POST /web_api/mcp/servers/:handle/tools` 404s, and
`PATCH .../tools/:id` returns 200 while silently ignoring `vua_required` /
`personalization` (title/description-class fields only). `PUT .../tools.json`
is bulk-update on existing bindings and rejects nonexistent ones. Binding is
**creation-time-only**: set when the recipe/skill is ADDED as a tool (UI
"+ Add tools" real-click flow, or package import — imports carrying
`mcp_server` members complete in DEV but fail `T.must` in PROD).

**Operational rule (Josh):** when building a skill intended for an MCP surface
(the default case, vs genie-attached — inferable from use case/project), attach
it to the server and set identity/policy flags (`vua_required`,
personalization) IN THE SAME add-time moment. You cannot retrofit any of it via
API later; a binding added through the UI with default flags then "PATCHed"
into shape silently keeps its defaults. Post-add description edits ALSO do not
track the backing recipe's description — re-save the tool after any
recipe-description edit.

## MCP tool "Incompatible" badge — 2026-10-06 (BSYS-28314 build)

Adding a new `workato_skill` recipe as a tool on an Enterprise MCP server
(AI Hub MCP server → Add tools), the row can show **Incompatible**. Hover the
badge for the reason. Confirmed triggers (all three fixed it / were needed):

1. **"Uses Call ID, Conversation ID or Genie ID datapill"** — the skill's
   telemetry step must hardcode `conversation_id` / `call_id` / `genie_id` to
   `""` (as live HR Genie skills 78626399/78622059 do; `genie_name`,
   `caller_*`, `app_type` pills are fine). Mapping these three from
   `start_workflow_1['context'][...]` makes the tool incompatible.
2. Result schema needs `control_type` on every leaf field.
3. At least one required result field (make the always-present field
   `optional: false`); an all-optional schema with an array whose items have a
   required field fails the step validator ("Missed required field at path
   result.options.state") and blocks Test with "some steps haven't been setup
   correctly — Errors in step N".

Also: empty static list values (`options: []`) are silently dropped from saved
step config — omit the key and make the schema field optional. The Genie-side
tool picker is paginated (A–Z, ~10/page); its checkboxes can't be trusted from
a stale DOM re-read — filter by name, set state, clear the filter, then Save.
Dev CLI creates project properties that AIRO cannot:
`workato properties upsert --project-id N --property "K=V"` (wt wrapper's
`properties upsert --data` 400s "Missing parameter properties" — use the Dev
CLI). `project_property['Name']` on a nonexistent property resolves blank
(nil-tolerant) at runtime — recipes can reference properties before they exist.

## API-hardening pass traps (2026-10-06, ooo-status endpoint v1.1)

- **Dynamic-list response bodies coerce nil→"" silently:** per-key pill
  subscripts inside a list-comprehension are stored as f-strings, and an
  f-string of a nil pill renders as empty STRING in the JSON response, not
  null — even when the response schema declares the key optional boolean.
  Fix that WORKS: per-key `ruby()` with a nil-guard binding, e.g.
  `ruby("bindings.v == nil ? nil : bindings.v", bindings={'v': results_item['isOOO']})`
  — verified null in the live response while real booleans stay booleans.
- **Rails semantics trap in those guards:** `blank?`/`present?` are WRONG
  for boolean guards — `false.blank? == true` in Rails, so a legit `false`
  would null out. Only an explicit `== nil` comparison is safe. Also:
  Workato's formula validator rejects `.nil?` ("unknown_function") but
  accepts `== nil`.
- **recipe_builder_set_condition requires the TOP-LEVEL `operand`**
  ("and"/"or") even with a single condition — "operand: Field required"
  means you forgot it, not the per-condition one. `rhs` for a string
  compare is the BARE literal (`"true"`), not an escaped-quotes form.
- **recipe_builder_add_step takes the DSL action name** (`return_response`),
  not the UI display name ("Respond to API request").
- **A 400 return_response needs the response REGISTERED on the trigger
  first:** set `response.responses` on step 1 with both entries (200 ok +
  400 bad_request with its body_schema), then the new return_response's
  `http_status_code` selects by name/code and the body keys appear in
  schema only after the status is set (set status, re-pull schema, set body).
- **Workato recipes can stop SILENTLY:** the snapshot recipe was found
  stopped with `stop_cause: null`, no failed jobs, no errors — not our
  action. Recommendation for prod: enable Workato's recipe-stopped email
  alert, and treat `stale:true` consumer responses as the canary.
- **Audit attribution:** the API-platform trigger's context pills
  (`context.calling_ip`, `context.client.name`,
  `context.access_profile.name` = key name) turn the per-call audit row
  into pen-test forensics; store them in the JSON summary column (no
  schema change on a populated table). Rejection accounting (`rejected`:
  count or -1) survives on the same row.

## AIRO outage workaround — raw recipe-code surgery via Developer API (2026-10-06)

When AIRO denies ALL folder/project resolution (pull/init/push/job_list
fail with "you do not have access to the target folder or its project")
while the Developer API token still works, recipe edits remain possible:
`GET /api/recipes/<id>` → the `code` field is the NATIVE recipe JSON
(string) — a tree of step nodes linked by `block` ARRAYS (sibling chains;
foreach/if nest children in their own `block` list). Surgery recipe that
worked: clone an existing step node as template (keeps
extended_input/output_schema), new `as`/`uuid`, edit `input` values,
append to the target `block`, `PUT /api/recipes/<id>` with
`{"name": ..., "code": <json-string>}`. HARD RULES learned by breaking it:
- **PUT only while the recipe is STOPPED** (running updates silently fail
  with `{"success": false, "errors": {<job_handle>}}`).
- **Re-fetch the recipe before EVERY PUT** — PUTs layered on a stale dump
  silently revert earlier fixes (clobbered my own patch twice).
- Snippet `code` is a PLAIN Ruby string (no leading `=`); pill values in
  `code_input.data` are strings: `=_dp('{"pill_type":"output",
  "provider":"...","line":"<step as>","path":[...]}').to_json` for
  to_json-string bindings or `"#{_dp('...')}"` for datapill-strings.
  `visible_config_fields` must reference the REAL data keys.
- **NEW steps with new pills fail start-validation** ("can't be blank" —
  no run samples yet). In-place edits of EXISTING steps (whose pills have
  samples) validate fine. For diagnostics, REUSE existing steps: swap a
  step's `report_wql` (formula form `="SELECT ..."`) and its downstream
  snippet's `code`, then revert from the saved original.
- Same incident: the Workato UI 404'd EVERY asset (recipes, tables,
  projects) across workspaces/environments for a signed-in admin while the
  API token worked — whole permission-resolution plane down, not a
  workspace/env/user mistake (verify against `/api/projects` before
  chasing workspace-switcher theories).

## Data-table scan-parse + test-modal mechanics (2026-10-06, audit function build)

- `get_records` DEFAULT output serializes records with FIELD-ID keys
  (`{"30cea496_..."=>"6b8d..."}`) — regexing field NAMES out of the inspect
  string matches nothing and fails SILENTLY (empty result, green job).
  Always set `output_format="field_name_to_value"` when records feed
  scan-parse Ruby (or pill access), and regex the semantic names.
- BUG CLASS (bit audit_conversation_case_file 82855731): never hardcode
  field-ID keys in scan-parse code — data_table_update regenerates ALL field
  IDs, so ID-keyed parsing breaks on any schema edit. Name keys survive.
- Silent-blank guard: when a required param drives a filter, return an
  explicit `invalid_principal`-style status on blank input instead of the
  empty-window result — the editor Test runs with EMPTY params if you submit
  the modal without filling it, and it reports green.
- "Add trigger data" modal fields are CodeMirror-backed pill fields: the
  CodeMirror JS instance attaches only after the field is FOCUSED (dispatch
  mousedown/mouseup/click on `.text-field` inside the `w-form-field`, then
  focus the revealed textarea), then `fieldEl.querySelector('.CodeMirror')
  .CodeMirror.setValue(v)`; verify with getValue(). Native-value-setter +
  input event does NOT register (validation still "required"), and
  `orca keypress` doesn't reach the webview's JS-focused element.
- `orca computer paste-text/type-text` needs an on-screen app window — the
  Orca browser runtime has NO on-screen window (window_not_found), so native
  computer-use typing/paste is unavailable for web content. Use CodeMirror
  setValue or orca find real-clicks only.
- Recipe-function trigger params pill path confirmed (vs production claim fn
  82285042): `execute_1['parameters']['<name>']` — correct; a blank value in
  a test trace means the modal was submitted empty, not a mapping bug.
- REST stop/start for edit+test cycles works fine:
  PUT /api/recipes/<id>/stop|start with Bearer $WORKATO_API_TOKEN.
- `delete_records_by_condition` rejects `op_default: "is"` at RUNTIME
  ("Expected input type ApiQueryOperation") — valid string ops are
  eq / ne / isnull / isnotnull / starts_with (picklist on filters.N.op_default).
  get_records accepts more ('is on or after', 'gte' etc.) — do NOT assume op
  tokens transfer between actions.
- TEST-THE-ALERTING-PATH rule: a monitor whose happy/quiet path is green but
  whose ALERT-FIRING path never ran live is unverified. The 82830607 monitor
  shipped with a latent 'is' op bug because only the silent path was
  smoke-tested; every alert would have posted then FAILED the job and never
  written cooldown (hourly spam loop). Force-fire each alert class once.
- `recipe_get` "Inconsistencies detected" can be STALE (snapshot from a
  connector-release window) — verify against live recipe_builder_get_datapills
  before treating them as real. Media executor 82778049 listed 6 invalid
  manage_media pills that resolve fine live; it started and ran clean.
- **ADAPTER SCHEMA SERVICE STALENESS after a custom-connector release
  (2026-10-14, BSYS-29680):** for 1.5h+ after releasing connector v48, the
  recipe-builder schema service kept serving the PRIOR release's action input
  fields — to NEW action steps too (fresh `recipe_builder_add_step` on a
  throwaway recipe still showed only v47 fields), not just existing steps.
  Save-time validation (both AIRO push AND raw `PUT /api/recipes/:id`)
  SILENTLY STRIPS step input keys not present in the served schema — the PUT
  reports `success:true` while dropping the new field. Trigger-side
  `parameters_schema_json` + `extended_output_schema` + step
  `visible_config_fields` survive; only the action-step INPUT key is eaten.
  **Workaround that beats waiting:** declare the new field in the action
  step's recipe-level `extended_input_schema` — the validator then accepts
  the step input key, and the runtime passes it through to the (already
  released) connector action. Verified live on 73842315/81841004.
  Diagnostic sequence that pinned it: fresh `recipe_builder_pull` in a NEW
  session_id → `get_input_schema` → if the new field is missing, build the
  throwaway-skill probe (`recipe_builder_init_skill` + add the action) to
  distinguish stored-step staleness (probe shows field) from service-wide
  staleness (probe missing field too — it was service-wide).
- `wt recipes force-run <id>` works for SCHEDULER triggers (422 for skill/
  function triggers) — the fastest way to prove a scheduled recipe's running
  schedule without waiting for the tick. (Global rule stands: never wait.)
- INSTRUMENT THE FULL OUTCOME MATRIX: when adding telemetry to a branch,
  cover success + rejection + failure in the same commit. The media branch
  shipped failure-only recording (Oct 4 crash-hardening) and outbound success
  stayed invisible for 4 days — we instrumented the pain we felt. Any new
  early-return path gets its recorder in the same push.
- BEFORE declaring a stopped/errored recipe function matters, grep its
  flow_id in the suspected caller's DSL — the media executor 82778049 was
  "red" but VESTIGIAL (zero refs in the gateway; the media flow is inlined).
  Zero jobs since Oct 2 was the tell. Functions can be dead code too.

## Watchdog + risk scoring (2026-10-06)

- **workato-watchdog agent** (~/.claude/agents/workato-watchdog.md, nightly
  23:13 self-rearming cron): three read-only jobs — exception connections with
  running-recipe blast radius (P1), stalled-scheduler detection (running=true +
  last_run_at > 48h, higher confidence after recent stop/restart churn — the
  HR Genie anomaly class), failure autopsy (failed jobs clustered by error
  class, proposed airo-mcp-playbook trap entries marked unverified). Reports
  to knowledge/garden-reports/watchdog-YYYY-MM-DD.md.
- **CORRECTION (2026-10-09, healer fleet):** the stalled-scheduler heuristic
  above false-positives — `last_run_at` does not track scheduler ticks (recipe
  82888287 showed 28h stale while hourly green scheduler jobs ran through the
  moment; job-trace sweep of all 154 running dev clock recipes found 0 true
  stalls, the 14 >24h candidates were all weekly/monthly/annual and in-window).
  Correct probe: newest job via `GET /api/recipes/<id>/jobs?per_page=1`, stall
  when age > 1.5 × trigger interval. Full evidence in
  ~/harness/watchdog/escalation.md; playbook probe note in
  ~/harness/watchdog/repair-playbook.md.
- **Push risk scorer** (workato-guardrails v0.4.0 hook 9): hooks
  recipe_builder_push, tracks session_id→recipe_id from pull/save, calls the
  dependency tracker via $.mcp.call for live health (running state, fail rate,
  last-run age, never-run), and HOLDS prod pushes scoring medium+/running for
  an explicit $.ui.ask proceed/cancel. Dev pushes get the score annotated.
- **Recipe corpus index** (~/.claude/knowledge/garden-reports/recipes-index.jsonl,
  weekly Monday 06:07 cron, agent-built from AIRO recipe_list across AI
  Dev+Prod): offline "have we built this before" via
  ~/.claude/knowledge/scripts/recipes-search.py (query / --folder /
  --similar-to).

## Build ledger — cross-session/multi-agent build tracking (2026-10-06)

`~/.claude/knowledge/build-ledger.jsonl` (gitignored, operational state not
knowledge). Written by workato-guardrails v0.5.0 hooks:

- **Hook 10 (AIRO mutations, dev+prod):** every successful recipe_builder/
  genie/data_table/blueprint/mcp_server/connector_builder mutation logs
  {tool, server, session_id, recipe_id (args or session-tracked from
  pull/save), folder, ticket}.
- **Hook 11 (CLI/Orca):** Bash commands matching `wt`/workato push/pull/
  start/stop or `orca` log {kind, command excerpt, first numeric ID}.
- **Ticket tracking:** prompt.submit hook remembers the last Jira key seen;
  ledger entries carry it — "which builds belong to which ticket" is answered
  structurally.
- **Commands:** /builds [today|week|all] (per-asset summary), /promotion-ready
  (dev edits newer than last promotion marker), /promoted <ids> (mark).
- **Multi-agent property:** the ledger file is shared across sessions and
  project dirs, so parallel agents see each other's mutations — "what was
  updated" is a query, not a memory test.
- Self-improvement reporting: brain-guard v0.3.0 logs mcp-call bytes AND
  mcp-error events; gardener weekly folds both ledgers into a dev-tools
  report (failure rate per tool, context bytes per server, CLI/browser
  fallback frequency, stale never-promoted builds).

## Wave 3 — self-verifying machine (2026-10-06 evening)

- **Recipe snapshot history** (guardrails v0.6.0 hook 12): after every push,
  the hook re-reads the fresh DSL via $.mcp.call(recipe_get) from the MATCHING
  server (dev push → dev read, prod push → prod read) and commits it to
  `~/.claude/recipe-history/<env>/<id>/<timestamp>.json` (git repo, init'd
  from session.start). "What changed in recipe X" = /snapdiff <recipe_id>
  (renamed from /diff 2026-10-07 — the engine's built-in cc-plugin-diff
  panel owns /diff; a second $.command.register of a taken name is
  refused with a session warning) or git log/diff in that repo.
  Best-effort: snapshot failure never fails a push.
- **Heartbeat + skip detection**: every nightly job appends
  {"ts","job"} to garden-reports/heartbeat.jsonl; the watchdog (23:13, runs
  last) checks for today's brain-gardener/docs-watch entries and opens its
  report with a P0 "the machine itself skipped" line when they're missing —
  the watchdogs now watch the watchdogs.
- **launchd lane**: com.josh.workato-docs-watch (~/Library/LaunchAgents/)
  runs the docs crawler at 22:15 UNATTENDED — no session required. Kickstart
  verified live. MCP-dependent agents still need an idle session (platform
  limit); the heartbeat detects their skips.
- **Cost rollups**: brain-guard v0.4.0 logs turn.complete usage (in/out/cache
  tokens) to the usage ledger — per-project cost reporting becomes a
  gardener aggregation.
- **External-edit detection** (watchdog Job 4): recipes updated_at < 48h with
  no build-ledger entry = non-Claude work (Josh UI, Codex, Orca) — P2 flags
  where the ledger is blind and /promotion-ready under-reports.
- **Ticket reconciliation** (gardener Phase 2.7): ledger tickets vs Jira
  status — closed-ticket-unpromoted and builds-without-story flags.

## Opportunistic claim verification + cockpit (guardrails v0.7.0, 2026-10-06)

- **Decision (Josh 2026-10-06): synthetic probe harness PARKED.** Rank was
  elegance-biased; most verification value comes free from real work.
- **Opportunistic verification hooks** (in guardrails): a push that succeeds
  while the tracker said running → stamps `push-on-running-recipe`; a
  successful `wt/workato start` triggers a recipe_get read-back → stamps
  `cli-start-silent-noop` (confirms OR refutes). Observations append to
  `claims/verifications.jsonl`; the gardener rolls them into claims.jsonl
  `last_verified` (Phase 2.5) and proposes superseding repeatedly-refuted
  claims. Probes return only if a claim bites twice with no natural coverage.
- **/cockpit pane** (terminal/Desktop Code tab): Session tab (prod writes,
  mutation count, current ticket) + Ledger tab (last 8 build-ledger entries),
  live-redrawn via $.ui.invalidate. Falls back to a text reply where nothing
  draws (headless/VS Code) — the fallback is TESTED, not assumed.

## Estate architecture layer (2026-10-07)

Ten enterprise capabilities, built as two agents + scripts + schedules:

- **promotion-orchestrator agent** (~/.claude/agents/promotion-orchestrator.md):
  ledger-driven batches — ONLY touched/needs-promoting assets (never
  bulk-folder), manifest via wt CLI or Orca, BSYS STORY (never Deployment
  Request type) with the VERIFIED field map from BSYS-29283:
  customfield_10494 = manifest URL, customfield_10446 = cascade {target env
  "Workato AHQ | AI Production [3535598]" id 31164 + child = destination
  FOLDER path option (look up per folder, don't hardcode)}, customfield_10588
  = source env (id 31161), customfield_10057 = points, parent = governing
  epic. Staged execution (functions → tables → recipes → MCP servers) with
  VUA verify + smoke per stage, only on Josh's explicit go.
  RULING (Josh, 2026-10-07): the promotion orchestrator is ON-DEMAND ONLY,
  NEVER scheduled — no Thursday cron, no dry-run slot. Batches are
  inventory-driven; run it when Josh asks.
- **estate-architect agent** (~/.claude/agents/estate-architect.md, Mondays
  06:37 AFTER the 06:07 corpus indexer): cost heatmap (runtime tasks per
  folder + dev tokens estate-wide), zombie/hygiene report, config parity
  (property_list dev vs prod, secrets as "(set, hidden)"), lineage v1
  (system/object mermaid maps per folder in knowledge/architecture/;
  field-level only on Josh-named folders, ≤10 recipes, recipe_get not
  tracker get_recipe), security posture (personal-connection heuristics,
  VUA vs service), deprecation radar (docs-watch deltas × corpus).
- **cost-heatmap.py**: couples runtime tasks (corpus index) with dev tokens
  (usage ledger turn-usage events); per-project token attribution needs
  session-id plumbing (noted, honest about it); ROI layer = manual input.
- **Scenario replay**: fixtures in knowledge/replay-fixtures/ (sanitized
  prod-like payloads per recipe); orchestrator Phase 4 uses them pre-promo.
  Capture + replay v1 = manual via Orca test; harness later.
- **Watchdog Job 5**: P1 → postmortem DRAFT (timeline from build ledger +
  job traces, root-cause hypothesis, prevention→playbook proposal); files
  only on Josh's go.

## More recipe-builder / test-dialog findings — 2026-10-06 (BSYS-28314 build 2)

- **`call_recipe` (sync) datapills live under `['result']`, not `['output']`**
  — opposite of every other connector step. `recipe_builder_get_datapills`
  shows the true paths when mappings fail validation.
- **Workato test-dialog fields (w-form-field / w-text-field) render a
  `w-text-field-preview` PRE, not an input** — click the preview (or the
  field), the real textarea attaches, then fill. Angular-based (ng-star):
  React-style input events do NOT bind state — values vanish on submit.
  `document.execCommand('insertText')` after focus inserts text Angular
  hears (worked in the classifier dialog... but still failed to bind on the
  submit-recipe dialog — treat the trigger-data dialog as unreliable for
  scripting; prefer driving the Genie TEST tab conversationally instead,
  which also exercises the real routing).
- **Send-button click can navigate the tab away** (genie list, export
  manifests — the wrong ancestor fallback grabs a nav link): anchor send
  clicks to `button[aria-label=send]` filtered by `offsetParent`, never to a
  `closest()`-derived container. Re-goto and retry on escape.
- **`recipe_builder_add_step` inside a catch block can append AFTER the
  terminal return** (silent dead code) — always `recipe_builder_show` after
  catch-block inserts and `move_step` before the return if needed.
- Recipe functions must be **started** to be callable by `call_recipe`.

## Self-discovering API dictionary + glossary (2026-10-07)

- **wt discover** (+ --refresh): harvests the Developer API endpoint
  reference from docs.workato.com/en/workato-api/resources.md (.md variant,
  302 endpoints / 32 groups) into knowledge/workato-api/api-index.jsonl;
  reports new/removed endpoints since last run + wt coverage gaps (12
  dedicated groups; everything reachable via `wt api` passthrough). The
  gardener (Phase 2.8) folds new endpoints into proposals for new wt
  subcommands — the self-improvement loop.
- **`wt-route <regex>`** (scripts/wt_route.py, symlinked to ~/.local/bin):
  one-command route lookup over api-index.jsonl (method/path/description/
  group; -v adds doc_url). USE THIS BEFORE ANY `wt api` route guess —
  guessing burned 3 turns + 404s deleting an API collection (2026-10-13)
  when the answer (`DELETE /api/api_collections/:id` — NOT /api/collections)
  was one `wt-route 'delete.*collection'` away. If a route 404s anyway,
  `wt discover --refresh` re-harvests the index; the workato-kb
  (`workato-api/resources.md`) is the second lookup, never blind probes.
- **Glossary**: knowledge/workato-terms/terms.jsonl (18 seed terms) via
  glossary.py (lookup/search/add); gardener grows it from platform deltas +
  sessions. Supersede-on-redefine.
- Gotchas fixed live: markdown link rows need `](url)` consumed after the
  path capture; docs .md variants exist for docs pages (NOT /en/developer-api.md);
  regex row assumed `]` came late in the link, it comes right after the path.

## Self-discovering API dictionary + glossary (2026-10-07)

- **wt discover** (+ --refresh): harvests the Developer API endpoint
  reference from docs.workato.com/en/workato-api/resources.md (.md variant,
  302 endpoints / 32 groups) into knowledge/workato-api/api-index.jsonl;
  reports new/removed endpoints since last run + wt coverage gaps (12
  dedicated groups; everything reachable via `wt api` passthrough). The
  gardener (Phase 2.8) folds new endpoints into proposals for new wt
  subcommands — the self-improvement loop.
- **Glossary**: knowledge/workato-terms/terms.jsonl (18 seed terms) via
  glossary.py (lookup/search/add); gardener grows it from platform deltas +
  sessions. Supersede-on-redefine.
- Gotchas fixed live: markdown link rows need `](url)` consumed after the
  path capture; docs .md variants exist for docs pages; the regex originally
  assumed `]` came late in the link, it comes right after the path.

## wt testcases + scope-gap detection (2026-10-07 night)

- **`wt testcases run|status|cases`**: Test Automation API (POST
  /api/test_cases/run_requests with exactly one scope: manifest|project|
  folder|recipe|ids; poll GET run_requests/:id; GET
  /api/recipes/:id/test_cases). Regression harness is now BUILDABLE — the
  earlier "test runs are UI-only" conclusion was wrong; the scope exists on
  the Developer API. (The later "needs scope grants" conclusion was ALSO
  wrong — see RESOLVED below: it was WAF header 302s, not scopes.)
- **`wt discover` scope-gap detection**: probes one endpoint per
  unimplemented API group; login-page or 401 = scope gap, reported with the
  grant instruction. CRITICAL gotcha: wt.request calls die()/sys.exit() on
  401 — SystemExit is BaseException, `except Exception` does NOT catch it;
  the probe loop must catch BaseException or it dies silently mid-loop.
  Also: POST-first groups can't be scope-probed with GET (404 ≠ scope
  signal) — probe limitation to remember.
- 302 endpoints / 32 groups indexed; wt now has 14 dedicated groups.

## RESOLVED (2026-10-07): Agent Studio + Test Automation "scope gaps"

- NOT scopes, NOT domain. Root cause: Workato's WAF 302-redirects requests
  with python-urllib default headers (UA Python-urllib + Accept-Encoding:
  identity + no Accept) to /users/sign_in on NEWER API routes (/api/agentic/*,
  /api/test_cases/*) — even with a VALID bearer token. Legacy routes
  (/api/recipes.json) don't have this behavior, which produced the
  confusing split. www vs app.workato.com both work once headers are fixed.
- Fix: wt's request() now always sends User-Agent "wt/1.0" + Accept:
  application/json. ALL 302 endpoints confirmed callable; discover reports
  zero scope gaps. Postman/curl never saw it — only python-urllib clients.
- Debugging method that cracked it (worth reusing): cross-test headers BOTH
  directions (curl with urllib's headers → broke; urllib with curl's
  headers → fixed) — isolates header-level vs TLS-fingerprint causes in two
  calls. Earlier red herrings: token whitespace (no), UA alone (no),
  protocol HTTP/1.1 vs h2 (no), domain (no).
- Memo for boss updated to RESOLVED: ~/Documents/Claude/workato-api-scope-gaps-memo.md

## Descope recording rule (dream 2026-10-07 proposal #3, Josh-approved)

When Josh descopes a concern ("don't worry about X, build everything else"),
the agent RECORDS the descope in the governing ticket (one status comment:
descoped by Josh on <date>, what was descoped, why) BEFORE continuing other
work. Reason: descoped requirements resurface later as surprises; the ticket
must show they were consciously dropped, not missed. Mirrors the
hard-blocker escalation pattern (Jira comment + continue working).

## Naming rule (Josh, 2026-10-07, hard rule)

Never leave an asset named TEST outside the dev cycle - even dev work
renames TEST| consumers to their permanent REC|/MON| names before calling
them done. Test fixtures that exist only for UAT get deleted once their
evidence is recorded (job IDs in the Jira ticket), not parked with TEST
names. The coverage auditor's TEST| exclusion stays as code (useful for
future scratch fixtures) but no such asset should persist in the estate.

## Nightly regression harness LIVE (2026-10-07)

- regression-nightly.py (~/.claude/knowledge/scripts/): scans dev workspace
  for recipes with test cases (registry-cached; 400 scanned → 3 found:
  82273581, 82794233, 82855731), runs each via Test Automation API, polls to
  completion, writes garden-reports/regression-latest.md with job IDs.
- FIRST RUN caught 2 real regressions: "Untitled test case 1" failing on
  execute_google_workspace_operation (82273581, run cirr-AbrJxcEA-rTJFQB-CD,
  job j-AbrJxcDz-zsYQsb-CD — likely a stale placeholder case) and "Resolver
  V2 - unique caller-owned MCP child" failing on 82794233 (job
  j-AbrJxnRT-6CfDwc-CD — the HR Genie resolver; needs autopsy).
- Cron 00:13 nightly (d9579292), self-rearming, heartbeat-stamped; failures
  relayed to Josh, never self-fixed without a job-trace look.
- wt gotcha fixed en route: cmd_testcases double-encoded the body
  (data=json.dumps(body) into request() which encodes again) → API 400.
  Pass the dict, let request() encode.

## Workato AI gateway (ai.preview.workato.com/anthropic) — token economics, probed 2026-10-07 (v2, corrected same day)

Probes: headless `claude -p` runs + raw curl with cache_control markers +
real session-transcript usage analysis (CLI 2.1.289, glm-5.3-flash/kimi-k3).

- **Prompt caching WORKS and is heavy in interactive sessions.** Provider-side
  automatic prefix caching (Fireworks), no cache_control markers needed
  (cache_creation is never reported; reads are). Real session transcripts:
  83-98% cache_read share of total input across glm + kimi sessions. Within a
  conversation the prefix is stable, so turns 2+ hit.
- **Cold start per new session:** the first turn(s) pay the full prefix
  uncached (~110k on Josh's config), and fresh sessions never hit even with
  token-identical prefixes (runA/runB both 110,425, zero reads) — cache is
  per-conversation scoped, consistent with CC ≥v2.1.181 keeping the prefix
  stable only per conversation behind custom base URLs.
- **METHOD TRAP (burned once):** single-turn `claude -p` headless runs always
  show cache_read=0 because each is a fresh cold conversation — judging
  gateway caching from them produced a wrong "zero caching" claim. Use
  transcript usage aggregation instead. TTFT is also not cache evidence
  (repeat runs got slower on load noise).
- Tool search OFF + unforceable (non-first-party base URL;
  ENABLE_TOOL_SEARCH=true no-op): all MCP defs load upfront — 17 servers =
  89,454 of 110,425 (81%); 2 AIRO servers = 39.8k. deniedMcpServers by exact
  serverName works; serverName "*" wildcard does NOT. Pruning cuts every
  cold-start cost and the uncached share of every turn.
- modelOverrides silences unrecognized_model + swaps capability set (+6.6k
  system prompt); irrelevant to caching (provider auto-caches anyway).
- Thinking: glm-5.3-flash is thinking-only (disable hard-errors;
  budget_tokens=1500 suppressed thinking = gateway mapping bug;
  reasoning_effort passthrough accepted, effect unproven). kimi-k3 accepts
  thinking:disabled (~40% fewer output tokens) but CC only omits the param,
  never sends disabled — no client-side lever. Fast mode first-party-only.
- Gateway gaps for the eng team: /v1/models errors ("model is empty", breaks
  CLAUDE_CODE_ENABLE_GATEWAY_MODEL_DISCOVERY); only provider/name model
  strings accepted (rejects claude-* IDs). OPEN: cache_read chargeback rate
  vs input rate. Community: #ai-pe-coding-agentic-models (C0BJFG4Q0QK),
  usage dashboard aigw.david.sndbx42.net.

## Real-time Slack command path (2026-10-08)

- **agent_command_queue** data table (dev, folder 35733930 "[HARNESS] Agent
  Infrastructure" project 18212633; uuid 88affdf3-e432-4449-9d14-
  bbafbcd9c7db, numeric 157299): fields directive/source_ref/
  author_slack_id/status/result_note.
- **agent-command-watcher.py** (~/.local/bin, launchd
  com.josh.agent-command-watcher, 60s): pending rows → author check
  (U0A3R9AVAMA only) → execute via `claude -p` (prod writes fail there
  naturally) → mark done/rejected. selfcheck = no-op probe. END-TO-END
  PROVEN live (row lifecycle pending→done).
- Data-tables REST API shapes (learned by fire): host = data-tables.workato.com
  (www/app 404 /api/v1); id = UUID not numeric; create/update payload =
  {"document": {field: value}} (no colons); query rows = [system_triple,
  user_values_list] — decode $record_id from row[0][0].
- AIRO data_table_create 404'd "folder not found" but the table got created
  anyway (silent-success family — verify with GET /api/data_tables after).
- REMAINING: the Slack-trigger recipe (writes queue rows from
  #josh-slack-triage; personal connection WAIVED by Josh for this
  automation — lives and dies with him). Needs an in-workspace Slack
  connection check; build via AIRO recipe_builder next session.

## slack-command-bridge LIVE (2026-10-08) — the full loop

- **Recipe 82891787** (~/.local/bin/wt-built via AIRO builder + API surgery):
  Slack new_event trigger (connection 19051772 "Josh's Slack Account",
  webhook_suffix joshcommands) → if (channel==C0C7JHJKHRU AND user==U0A3R9AVAMA)
  → add_record to queue 157299. RUNNING.
- **Builder gotchas that bit**: (1) session_id collision denied folder access
  3× (unique session fixed it — parallel-session era is real); (2) start
  validation rejects `name` on IF-steps (builder writes them; strip via API
  code surgery: GET recipe → decode code once → del name from keyword==if
  steps → PUT code string); (3) data-table picklist uses NUMERIC ids
  (157299), records API uses UUID — both work, never mix hosts
  (data-tables.workato.com for /api/v1 records/query).
- **E2E verified**: Slack post "selfcheck" (VUA = Josh author) → queue row →
  watcher → done. Command path latency: ≤60s once the event subscription
  delivers; the fleet crons ALSO sweep the room each pass (polling fallback,
  last-sweep.txt marker) so commands work even without the subscription.
- **Pending (Josh UI)**: the connection's Slack event subscription isn't
  wired — the recipe took 0 jobs from a real post; the sweep covers it at
  pass cadence until the reconnect/event-config happens.

## Function-schema re-registration (2026-10-08, BSYS-29330 counter build)

AIRO push of a recipe function does NOT re-register its parameter schema in
the platform function registry; downstream call_recipe sites keep validating
against the stale schema (set_input_field rejects the new param; update_step
and fresh caller pulls don't help). KNOWN-GOOD WAY: stop function → AIRO
pull/edit/push → **editor open+Save of the function (re-registers the
schema)** → fresh-pull callers → set the param per call site → push callers
→ hot-path verify. Full procedure in airo-mcp-playbook
references/known-bugs.md. Josh standing rule (2026-10-08): never build
around a stale cache; fix the cache and finish the direct fix. The strict
re-validation after re-registration can surface latent blank-return bugs
(fixed one on the gateway's media-compile path) — fix them, don't silence.

## Slack app governance (2026-10-07)

Slack app scope/subscription changes in the workato.slack.com workspace are
NOT self-serve: saving Event Subscriptions on our own app (Slack by Workato
M... A0BK96D967K) requires an ADMIN APPROVAL cycle for the app reinstall
before the new scopes take effect. Lead time = admin responsiveness —
factor into any Slack-event wiring (don't promise same-minute delivery
until the reinstall is approved + tokens refreshed).

## Clock scheduler gotchas — time_unit CASE-SENSITIVE + copy clones trigger UUID (2026-10-08, three dead recipes)

- A clock `scheduled_event` trigger with `time_unit: "Minutes"` (capitalized)
  lands on an anchor-bearing path: `trigger_at` required at start validation,
  and every scheduled fire silently errors WITHOUT creating a job record →
  invisible error accumulation → `trigger_errors_limit` auto-stop. Symptom
  reads as "schedule never registered" (job list never grows). LOWERCASE
  `"minutes"`/`"hours"` is the proven path (no `trigger_at` needed; fires on
  start + on cadence). Full write-up:
  `~/.claude/skills/airo-mcp-playbook/references/known-bugs.md`.
- `wt recipes copy` CLONES the trigger UUID — a "fresh-scheduler copy" keeps
  the same schedule identity. Rebuild with `recipe_builder_init` instead.
- Stall diagnosis: check `stop_cause=trigger_errors_limit` on the recipe
  object BEFORE concluding scheduler misregistration. `reset-trigger` does
  not fix this class; anchor/interval value changes do not either.
- `wt recipes force-run` 422s on a stopped recipe — any external force-run
  loop needs a start-first guard. (Used only as a temporary stopgap during
  the 2026-10-08 investigation; the durable fix is platform-native.)

## Command-loop root cause + fix (2026-10-08, "selfcheck did nothing")

- **Defect 1 — no feedback leg (design gap, now closed):** the watcher marked
  rows done with zero visible output; result_note lived in a data-table cell.
  Watcher now acks AS THE BOT in #josh-slack-triage after every directive.
- **Defect 2 — event ingestion of own-user messages is unreliable:** Josh
  posted selfcheck 6x (00:23-04:42Z); exactly 1 became a queue row (and 14
  min late). The recipe WAS receiving other-channel events near-real-time
  the whole time (17,246 jobs, ~all firehose noise). The "fleet-cron sweep +
  last-sweep.txt fallback" in this file NEVER EXISTED — documented before
  built. Lesson: this file must not pre-document unbuilt mechanisms.
- **Fix (Josh chose: dedicated bot + stop the bridge):**
  - Reused the EXISTING `josh-triage-bridge` app (A0C7F7LK9MH, created for
    this room by an earlier session, token never captured). Added bot scopes
    groups:history/groups:read/groups:write/chat:write.public via the
    OAuth-page scope picker (native-value-setter + input event filters the
    virtualized dropdown; orca type does NOT land — confirmed again).
  - Scope change requires admin re-approval: request FILED ("Allow and
    Request Permissions", success=1); pending Josh's admin approve.
  - Bot user: joshtriagebridge U0C76D82LAK, invited to C0C7JHJKHRU.
  - Current bot token (pre-upgrade) in keychain svc
    `slack-harness-command-bot` acct `watcher`; swap after reinstall.
  - Watcher patched: poll_room() ingests directives from room history
    (dedupe: last_ts float + seen_ts ring, oldest first), writes queue rows
    (source_ref slack-poll:<ts>) for the audit trail, executes inline, acks
    via chat.postMessage. Missing scopes/tokens = quiet skip (proven live).
    `execute()` shared by both paths; bridge table path kept as legacy.
  - **Bridge recipe 82891787 STOPPED** (live-verified running: False) —
    ~17k junk jobs/day gone; restartable anytime.
- **Remaining to go live:** (1) Josh approves the pending scope request
  (Slackbot/admin notification), (2) reinstall → capture NEW xoxb → swap
  keychain, (3) Josh posts selfcheck → bot acks. Ingestion test note: 60s
  launchd cadence unchanged.

## Command loop UPDATE (2026-10-08 06:15Z) — LOOP CLOSED AND LIVE

- E2E selftest PASSED: queue row (selfcheck) → watcher → done → **bot ack
  observed in-channel** (U0C76D82LAK: "selfcheck ok at 2026-10-08T06:13:44Z").
  Josh can SEE the loop answer now. Acks work TODAY on chat:write alone (bot
  is a channel member; only HISTORY needs the pending groups:history).
- Ingestion TODAY: `room-sweep` fleet job (com.josh.fleet.room-sweep,
  StartInterval 300): headless claude reads the room via slack-workato MCP
  → `knowledge/scripts/room-sweep.py` queues rows via the watcher's own
  api() → watcher executes + acks. Command latency ≤ ~6 min.
- Sweep hardening (both bugs hit live, both fixed): (1) create-row success =
  HTTP 201 + data.created_at (no record id in response); (2) directive
  grammar check MUST be word-boundary exact on the first token — the
  substring check "elfcheck in directive" rejected every valid selfcheck.
- After the admin approves the scope re-request: reinstall in Orca →
  capture NEW xoxb → swap keychain svc slack-harness-command-bot → the
  watcher's poll_room() (60s) becomes primary; the sweep job can then be
  bootout-ed (kept as fallback until then).
- 8 backlogged selfcheck rows were wrongly rejected during the cleanup bug
  (no-ops, no impact) + 1 duplicate selftest row rejected deliberately.
- Escalation on record: BSYS-29315 comment 1132284 (admin approval ask).

## REAL-TIME LOOP PROVEN (2026-10-08 02:14 PT)

Josh typed selfcheck in #josh-slack-triage → event → recipe 82891787 →
queue row → watcher → done, within the first 20s wave. Full chain LIVE:
dedicated app (A0C7F7LK9MH) subscription + connection + recipe + queue +
watcher. ALSO proven: MCP-posted messages are BOT-authored (event.user =
bot id ≠ Josh) — the author filter correctly eats them; real user-typed
messages are the directive path. Backlog flush + invite event produced 14
rows; the fleet's room-sweep rejected junk rows in-band.
REMAINING (Josh): disable Event Subscriptions on the OLD app (A0BK96D967K)
— it was still flooding ~4k tasks/hr at last check (23,412 jobs).

## Trigger-guard on bridge recipe (2026-10-08 morning)

Recipe 82891787 was found STOPPED (job count frozen 23,412, last job 22:57
PT, all old-app A0BK96D967K). Before restarting, added a trigger-level
condition on the Slack event trigger: channel == C0C7JHJKHRU AND user ==
U0A3R9AVAMA. Non-matching events are dropped before job creation, so the
old-app flood cannot burn tasks even while the recipe runs. Verified: start
→ 2min soak → job_scope_count flat at 23,412. Recipe Running: True (AIRO
read-back). The if-step filter stays as a second layer.
TRAP: AIRO set_condition rhs must be passed BARE (C0C7JHJKHRU). Passing it
quoted ("C0C7JHJKHRU") renders as an escaped literal
== "\"C0C7JHJKHRU\"" which never matches. Inspect the step preview in the
tool result before pushing.
Josh's old-app toggle is now hygiene, not urgent: deliveries cost nothing
(200 responses, no jobs). Still recommended so the old app stops receiving
workspace-wide traffic.

## HR Genie resolver "flaky failures" = two stacked defects (BSYS-29396, 2026-10-08)

Symptom: 6/45 failed jobs on recipe function 82794233 (VUA tools-listing step,
`Output check failed: data wasn't equal to expected value`, error type "Test
Automation error"). Root causes and fixes, both replay-relevant:

- **Test Automation output checks are snapshot comparisons, not schema
  checks.** The runner compares a step's live output against recorded literal
  expected values ("Count equals 23"). Never record literals for steps that
  return volatile live data (counts, inventory listings, timestamps) — assert
  the behavioral result step (the RETURN) instead; keep only stable checks
  (page/per_page). Monitor/error-handling retries do NOT catch this error
  class (comparison happens outside the monitored action). Checks are edited/
  deleted per-step in the test case builder; `wt testcases run/status --ids
  citc-...` runs them on demand (run id cirr-...).
- **Tool `vua_required` on an MCP server tracks the source skill recipe's
  "End user's connection" flag** (`personalization: true` on the connection
  config entry). A skill pushed without it (the AIRO push-drift trap, seen
  live) yields a non-VUA tool, which makes the resolver's deliberate
  `count == tools_count` guard (VUA-filtered vs total) fail closed for ALL
  callers — here the OAuth-recovery chain (82210315) was silently down.
  Fix: recipe page → Connections tab → "End user's connection" card (recipe
  stopped; persists immediately, verified in config). Probe: VUA-filtered
  listing `count` vs server GET `tools_count` — the gap = number of non-VUA
  tools. All 25 tools on mcps-AYbrRaxY-dhF-CD verified VUA after fix.
- **Test fixtures get consumed by their own harness.** The 82210315 test
  runs queued real deletion of the TEST_MCP_OWNER runtime child. Recreate:
  `wt api POST /api/connections --data '{"application":"mcp","provider":"mcp",
  "name":...,"external_id":"TEST_MCP_OWNER","parent_id":21060311,
  "project_id":15643451,"folder_id":32985204}'` — provider is required even
  for mcp children, and root-folder assignment is rejected (pass the project
  folder). Created fixture: connection 22268746.
- Unmasking (`mask_data=False`) on the failing step was the decisive move —
  the masked payload type-checked clean, which is what proved the snapshot
  mechanism. Unmask when a failure cannot be diagnosed from metadata alone
  (payload here: tool inventory, no secrets/PII).
- Proof at the end: suite run cirr-AbrmbzTP-dAxTMH-CD 4/4 pass; positive job
  j-AbrmbzTG-AGQcN3-CD shows step-11 condition true + step-12 return
  (match_found=true), not just a green job.

## Connections CRUD wire format + CLI bug (2026-10-13)
- UPDATE (2026-10-16, connector v53 id 474791): the token input is now **`user_token`
  ("User token" label)**, NOT `api_token` — `input: {api_token: ...}` creates the connection
  silently credential-less and the async test reports 401 Unauthorized. UI fill via Orca browser
  works (real keystrokes into the password-type field). Old v-api_token note below may predate v53.

- `wt connections create` crashes (`AttributeError: 'Namespace' object has no attribute 'data'`,
  line 1011-1013 pre-check) even with --data — bypass with raw `wt api POST /api/connections`.
- Connection params go under **`input`**, NOT `fields` — `{"fields": ...}` is silently
  ignored (200 OK, connection left credential-less/inactive). Docs:
  https://docs.workato.com/en/workato-api/connections.md. POST body needs `application`,
  `provider`, `name`, `folder_id` (project folder, root rejected), `input`.
- Workato API custom connector (`workato_api_connector_*`) token field = **`api_token`**;
  wrong field name or bad token => authorization_status flips to exception/401 only after
  the async test runs — re-read the connection rather than trusting the PUT response.
- select_connections refuses inactive connections ("1 inactive") — authorize first, retry.

## Command-loop ops lessons (2026-10-08 morning)

- EVERY app reinstall rotates the bot token: the keychain copy goes stale
  with confusing `missing_scope` errors (scopes were fine on the app, the
  TOKEN predates them). Fix: re-read xoxb- from
  api.slack.com/apps/<id>/install-on-team (page HTML contains it), verify
  with conversations.history, `security add-generic-password ... -U`.
- Watcher crash mode: a non-selfcheck directive (typo "elfcheck", Josh's
  own join notice) goes to `claude -p` — launchd PATH can't resolve bare
  `claude` (FileNotFoundError). Line 44's CLAUDE absolute path already
  fixed the spawn, but the backlog drain runs one claude -p per junk-ish
  directive: slow, not stuck.
- Event path vs poll path: after reinstall, poll leg (conversations.history
  every 60s) is the reliable ingest; event path needs a fresh real message
  to test. Multiple concurrent watchers (launchd + manual) are protected by
  the last_ts/seen_ts guards but can double-run slow directives.
- Autotriage autopsies 2026-10-08: both persistent regression failures are
  TEST-CASE ARTIFACTS (unconfigured accidental case 82273581; brittle
  whole-catalog snapshot assertion 82794233 — the MCP tool-description
  snapshot trap in test form). Verdicts pending Josh via /triage.
- Atlassian MCP 403 "app not installed" persisted 3+ attempts — all Jira
  lanes dark until the app is re-granted on the instance (Josh/admin).

## Command loop UPDATE 2 (2026-10-08 15:20Z) — scopes landed; three defects fixed

- **Scope upgrade CONFIRMED live**: same xoxb token string now carries
  groups/channels history (conversations.history ok: True — Slack updates
  scopes in place on reinstall; no keychain token swap needed).
- **Root cause of "selfcheck doesn't fire" after the scopes landed:** the
  watcher's own room-poll woke up with last_ts=0, ingested the room-join
  message as a directive, and `subprocess.run(['claude',...])` died under
  launchd — **launchd PATH cannot resolve bare 'claude'** (~/.local/bin).
  6 FileNotFoundError crashes; the pending poison row crash-looped every
  60s tick; nothing newer was ever processed. Manual runs always worked
  (interactive PATH) — the classic launchd-only failure.
- **Fixes:** (1) CLAUDE = shutil.which('claude') or ~/.local/bin/claude,
  used for subprocess; (2) per-row try/except — a poison row gets marked
  rejected + acked, never crash-loops the tick; (3) state last_ts seeded to
  the pre-scope high-water mark so history replays don't re-ingest;
  (4) room-sweep fleet job BOOTED OUT (superseded by the watcher's own
  working poll at 60s; its headless-claude-to-JSON pipe was also broken
  under launchd — JSONDecodeError + python3.9); (5) fcntl flock
  single-flight (added by the daytime session) verified: 2 quiet exits.
- **Observed residual:** one selfcheck ack pair duplicated (poll-path and
  table-path acked the same message across racing instances pre-fix). With
  the flock held for the whole drain this should not recur — watch it.
- Real directive drained: "Triage pass 2026-10-08 (daytime): Jira lanes
  dark..." (slack-poll:1791472084) executing via claude -p (jira-autotriage
  matrix) — long-running by design.
- **Lesson for ALL fleet/launchd jobs:** never subprocess a bare binary
  name; resolve absolute paths at module load. The room-sweep approach
  (claude -p reads room → pipe JSON to python) is BOTH flaky (LLM
  transcription: "elfcheck") and environment-fragile — direct bot-token
  API polling is the durable pattern.

## Watcher hardening (2026-10-08 ~15:35Z)

Two bugs found and fixed live in agent-command-watcher.py:
1. SELF-INGESTION: slack-workato VUA posts carry Josh's user id, so the
   poll leg's author filter ingested our own triage digest as a directive
   (one wasted claude -p, row 97e34274, rejected by hand). Fix:
   our_post_ts() reads knowledge/slack-posts.jsonl and skips our tracked
   message_ts values in the room. RULE: every post we make as Josh MUST be
   recorded there (the presence rule already requires it) — the watcher
   depends on that ledger now.
2. CONCURRENCY: launchd ticks every 60s but a drain runs minutes — three
   watchers piled up, double-processing with separate states. Fix: flock
   single-flight guard at main(); later ticks exit quietly.
Also: subtype filter (channel_join notices), docstring updated (bridge
recipe is RUNNING with trigger guard; poll leg is the reliability backstop).
Verified: backlog drained, 3 selfchecks processed + acked at 15:33Z.

## Command loop FINAL (2026-10-08 15:35Z) — everything verified live

- **selfcheck/command loop: LIVE.** Watcher polls the room at 60s with the
  upgraded bot token, executes directives (absolute claude path works under
  launchd), acks AS THE BOT in-room. Multiple selfchecks drained + acked.
- **jira-triage fleet loop: HEALTHY.** Manual run 36s + launchd kickstart
  ~45s both queried Jira successfully; queue legitimately empty (0 tickets
  with labels=agent-triage AND status != Done); heartbeats fresh. The
  morning digest's "Jira lanes dark (Atlassian MCP 403, 3rd strike)" is
  STALE — Jira reads work again under launchd.
- The 08:28Z "Triage pass (daytime)..." room post was correctly REJECTED as
  the harness's own digest echo (own-post filter from the daytime session);
  filter verdict confirmed correct by the digest-format text.
- run-job.sh now logs "done validated" (daytime session upgraded it).
- Full loop is now: Josh posts directive → watcher 60s poll → queue row →
  execute (claude -p, jira-autotriage matrix) → bot ack in-room → row
  done/rejected. No dependency on Slack event subscriptions anywhere.

## Test-case UI automation results (2026-10-08 afternoon)

- DELETE of a test case: WORKS via tag-and-trusted-click (set data-testid on
  the trash w-svg-icon button → `orca find --locator testid --value X
  --action click` → confirm modal → tag its Delete button → same trusted
  click). Synthetic dispatched events and JS .click() NEVER fire the Angular
  handler; snapshot-ref clicks only hover. Recipe 82273581's accidental
  "Untitled test case 1" deleted + API-verified (0 cases).
- DEEP LINKS 404 IN THE WRONG ENVIRONMENT: after a session restart the
  env switcher resets to Production; every /recipes/<id> URL 404s. Fix:
  click env dropdown → Development. Env state is session-persistent.
- Test Case Builder canvas: panel pins the view, scrollIntoView/scrollBy
  are no-ops against it, zoom control isn't a plain button. Assertion edits
  inside the builder defeated automation this session — 82794233's brittle
  catalog-snapshot check (citc-Abo3G9Ew-sTkNQt-CD) still needs the
  re-author, and the economical split is Josh's 60-second UI edit:
  open the case → Edit test case → click the GET .../mcp_servers/.../tools
  step → output check → replace whole-catalog equality with stable facts
  (HTTP success + tools present), or re-snapshot from a fresh successful
  job via "Select data from a job". Failure is benign noise until then.
- Test Automation API exposes ONLY run/list — no create/update/delete
  test-case endpoints (docs.workato.com/en/workato-api/test-automation.md).

## Regression-noise closure (2026-10-08 evening)

Josh deleted ALL test cases on 82794233 in the UI (API-verified: 0 cases on
both 82273581 and 82794233). Both 3-night persistent failures are closed by
deletion, not re-authoring. Tradeoff on record: Resolver V2 now has no
test-case coverage; its 57/65 real-caller success rate is the residual
signal. Re-author via the testcase-authoring skill if coverage is wanted.
Expect tonight's regression run: clean (3 testable cases remain estate-wide:
2 on 82794233's siblings? no — 4 passing from earlier runs included these;
fresh count will show).

## Decoupled-boolean hotfix + prod lifecycle path (2026-10-08)

- **Same-day dev→prod fix flow that works:** fix in dev via AIRO (pull/edit/
  push, stop→push→start), verify live, then mirror to prod: AIRO-prod pull/
  edit/push works, but STOP/START have no AIRO tool on either server — wt is
  dev-workspace-only. Prod lifecycle = Orca browser: env switcher →
  Production → recipe page → Stop/Start buttons. Env-switch click needs the
  ref-based click (e24-style Header menu item) and a fresh snapshot after
  the menu opens; eval-dispatch on the option does not register.
- **Merge-boolean decoupling rule (generalizable):** when a recipe emits a
  "today" flag and a "next N days" flag from the same date list, the window
  test MUST exclude today (`d > today`) or the flags are nested (today∈range
  makes within-Nd always true). LOA/open-ended branches need an explicit
  end-date guard (`est_end empty || est_end > today`) — an unconditional
  on_leave ⇒ in_window keeps leavers flagged forever, even on their last day.
- **Prod cron change (2026-10-08) DONE:** snapshot 82917290 now `7 * * * *`
  (America/Los_Angeles) via AIRO-prod trigger edit (time_unit=custom_schedule
  → REMOVE the stale trigger_at/trigger_every fields or the push complains
  InputFieldNotInSchema). Env-switcher refs go STALE between shell commands
  (menu closes on focus loss) — resolve the option ref and click it within
  ONE `&&`-chained command, and always re-verify the active env afterwards;
  page navigations reset it to Development.

## wt fixture: browser-free recipe testing (BUILT 2026-10-08 evening, Josh-driven)

Josh: "can we build some fixture in workato we can call to test a recipe? I
can't deal with the slow pace of test cases." Built `wt fixture`:
- `wt fixture init --recipe <id> --kind webhook|force-run|api` scaffolds
  knowledge/fixtures/<id>.json (input payload + expect list)
- `wt fixture run --recipe <id> [--input json] [--expect path=op:value]`
  captures newest job id → invokes (webhook POST unauthenticated / force_run
  / api endpoint) → polls for the NEW job (3s interval, --timeout) → pulls
  job detail → asserts on output (fallback: last step's output for
  non-function recipes) → verdict pass/fail/timeout, exit code mirrors it.
- VERIFIED LIVE: echo target [fixture] echo target (82921718, [HARNESS]
  folder 35733930, webhook suffix fixturedemo) — pass verdict, 3/3 checks.
- Constraints discovered live: Slack-event webhooks validate Slack's
  envelope and IGNORE synthetic payloads (flood can't be spoofed);
  force_run only works on Workato Scheduler triggers (422 documented);
  code_input datapills ALWAYS arrive as strings (f-string render, even with
  object schema) — snippets get inspect-format text, never the object.
- Scheduled-recipe pattern: force-run fires the real poller (real data);
  deterministic fixture testing needs the body lifted into a recipe
  function, the schedule as a thin shell, and a callable driver recipe.
- Fixtures are version-controlled JSON: the recipe's test coverage lives in
  the repo, not the UI. Kit repo synced + pushed (fd02fc9).

## BSYS-29418 fix (2026-10-08 night): skill-recipe error envelopes

Dev fix on Extract Design System 78677477: BOTH get_presentation_revision_
guarded_v19 calls (steps 2+25) wrapped in AIRO error_handling monitors
(WorkatoMonitor try/catch). Catch returns the skill envelope with inline
ternary classification on catch_N['message']: SOURCE_ACCESS_DENIED/403,
SOURCE_NOT_FOUND/404, else SOURCE_ACCESS_FAILED/502; retryable false,
request_id = job_context['job_id']. Fail-closed preserved: catch returns
BEFORE registry activation; idempotency/registry/cache flows untouched.
MECHANICS LEARNED:
- AIRO error_handling: add_step(type=error_handling) creates try+catch
  child blocks; move the call into try via move_step; catch children are
  normal steps; catch pills = catch_N['message'/'type'/'line_number'...].
- add_step position is advisory for blocks: blocks may append at the END
  (unreachable after a return step) — ALWAYS move the block to position
  and verify via recipe_builder_show before pushing.
- move_step renumbers datapill references automatically (verified: step
  36's hash binding followed the probe to its new variable).
- set_input_field can reject with 'schema not loaded' right after adding
  the step — call get_input_schema then retry the same call.
- Workato SKILL recipes have NO API invocation path (no /api/skills/*,
  testcases run/list only): acceptance evidence for skill fixes arrives
  via real callers (MCP probes), not via anything callable. This is now
  the third documentation of that platform gap.
Ticket: comment 1133449 (render-verified), Backlog → In Progress.

## SKILL-RECIPE TESTING SOLVED (2026-10-09, Josh insight)

"Add the dev server to the MCP and I will auth it" — THE answer to the
no-skill-invocation-API gap: the MCP server IS the invocation path. Add the
workspace's MCP server to Claude (`claude mcp add --transport http --scope
user <name> <endpoint>`), Josh auths the VUA popup once, then MCP tool calls
ARE real-caller test invocations (they even carry the mcp_mock_genie_id
context, matching prod probe semantics).
BSYS-29418 FULL UAT via this path (78677477 envelope fix):
- 403: real prod-owned deck ID (from prod job traces) → SOURCE_ACCESS_DENIED
  envelope, job SUCCEEDED (j-AbsDCNEp) — trace: catch line 3, envelope line 4.
- 404: bogus ID → SOURCE_NOT_FOUND/404, job succeeded (j-AbsDA3Qk).
- cache-hit: ok true/200/cache_hit true (j-AbsDCskz); fresh: full extraction
  cache_hit false (j-AbsDDDGK).
Evidence comment 1133599. Remaining: promotion → prod failure count flat.
PATTERN for all future skill fixes: dev edit → MCP-tool invoke (403/404/happy)
→ job_get trace → ticket comment. No browser anywhere.

## MANIFEST FOLDER-TREE RULE (Josh correction, 2026-10-09)

A manifest whose dependency assets carry BLANK folder/absolute_path imports
as a blob (everything dumped into the import folder). Every asset entry
needs its REAL folder + absolute_path. Discovery chain that works:
1. flows: wt api GET /api/recipes/<id> → folder_id
2. tables: /api/data_tables is paginated at 100 — paginate (offset or
   page param) and match numeric_id; tables carry folder_id directly
3. folders: wt api GET /api/folders/<id> → name + parent_id, walk to root
For the GSlides project: Skills/ + Automation/ + Data Tables/ under
"Enhanced Google Slides by Workato MCP" under project "MCP | BT Managed MCP".
Rebuild → wt manifests update <id> --file → re-export → fresh zip (pkg
42183921 supersedes 42183874).

## SNOWFLAKE-BACKED MCP TOOL TIMEOUTS — CURSOR PAGINATION FIX (2026-10-09)

Recipe-function MCP tools have a ~4:00 CALLER-side timeout (the whole tool
call must finish inside it); the Snowflake connector's own timeout is a
separate ~4:00 per request. A heavy monolithic query dies at the caller
cliff even when chunked. Symptom signature: failures at almost exactly
4:00, error `{"error": "The connector's server isn't responding..."}`.
- Snowflake RESULT CACHE explains intermittent ~6s successes: a timed-out
  call keeps computing server-side, caches the result, and the identical
  retry (same connection user, within 24h, unchanged data) returns
  instantly. That's why the error says "You can try again."
- THE FIX (Josh's design, proven): cursor pagination at the MCP layer.
  Each tool call = ONE month-partition-pruned Snowflake query
  (`DATE_TRUNC('month', DATEADD('month', -{cursor_pill}, CURRENT_DATE))`
  bounds on both CTEs) + returns `next_cursor`; caller iterates to null.
  Month chunk ran 1.9s cold vs 4:00+ monolithic. Do NOT add a
  `Run long query` async action — the caller window still kills it.
- TRAP: Snowflake `Select rows using custom SQL` silently defaults to
  100 rows when `limit` is unset — a page-heavy tool truncates without
  any warning (rows_count: 100 in the trace exposes it). Set limit.
- recipe_builder DSL: f-string interpolation accepts ONLY plain pill refs
  (`{pill['value']}`), not `ruby(...)` calls (error: "Invalid formatted
  string expression type: Call"); embedded quotes inside f-strings must
  be single-quoted; pill paths for function params are
  `execute_1['parameters']['x']`; the simple declare_variable variant
  (name/type/value) exposes its pill as `['value']`, not by var name.
- Condition breaks auto-generated as STRING compares
  (`f"{x}" < "24"` lexes wrong: "3" > "2") — force numeric via ruby() on
  both lhs and rhs (`ruby("24", bindings={})`, not `ruby("24")`).
- Function-recipe job RERUNS work but start minutes late (they sat
  "pending" 25-30 min before executing); editor Test is the reliable
  invocation. Repeat-runs use the LATEST recipe version.
- Function schema changes (parameters/result schema) need the editor
  open + Save after AIRO push to re-register; confirmed the new param
  appeared in the Test modal and the served inputSchema after.
- MCP tool description edit (Enterprise MCP server page): row-level
  aria-label="Edit tool description" button (13 present, NOT inside the
  w-mcp-server-tool-link element — find via ancestor walk or row-rect
  match); dialog title "Edit tool details"; description editor is a
  MARKDOWN TEXTAREA (`markdown-editor__editor` class) — native setter +
  input event; verify served result via workato-registry list_tools.
- Orca eval trap: top-level `const` PERSISTS across evals in the same
  page ("Identifier 'el' has already been declared") — always wrap in
  an IIFE.
- wt has josh-us (dev ws 3535597) and josh-prod (ws 3535598) profiles;
  `wt recipes --profile josh-prod ...` for prod lifecycle (flag goes
  after the `recipes` subcommand).
Case: BSYS-29443 (prod hotfix on 71768712, editor test 2.3s,
next_cursor=1, served schema verified). Dev backfill pending.

## MCP PAYLOAD-SIZE CLIFF (follow-up to cursor fix, 2026-10-09)

Beating the 4:00 caller timeout is only half the battle: a cursor page can
still exceed MCP CLIENT result limits. Month-0 page = 466 rows / 432,226
chars (~108K tokens) → Claude client overflows and saves to a tool-results
file instead of showing data. mcp_tool_description fields were 65% of the
payload (avg row 912 chars, max 4,253).
- Fix that held: SUBSTR(description,1,200) in SQL + row-chunked cursor
  (cursor = month*100 + chunk; ORDER BY mcp_id, recipe_id for stable
  OFFSET paging; full page → cursor+1, short page → roll month, month 23
  done → nil). ~100 rows ≈ 35K chars ≈ 9K tokens per call. Snowflake step
  ~22-24s with ORDER BY (vs 1.9s without) — still far under 4:00.
- Editor Test with trigger data: the "Add trigger data" modal field is
  hidden until clicked — orca snapshot exposes it as textbox ref after
  clicking the field widget button; orca fill --element <ref> works.
  Verify the job's trigger inputs after (a stale fill silently submits
  cursor=''). The modal a11y tree does NOT show the textbox until the
  field widget is clicked.
- "Edit tool description" ancestor-walk targeting can open the WRONG
  tool's dialog (rows bleed text) — cancel, then match the edit button
  by the target row's bounding rect instead. Always verify the dialog
  Title input before filling.
Case: BSYS-29443 v7 (cursor='' 24.7s/100 rows/next=1; cursor=1 22.5s/next=2).

## MANIFEST CLOSURE RULE (Josh import failure, 2026-10-09)

Import failed on "Unresolved 'Knowledge Base' reference" — the recipe's
folder_assets deps list only lists DIRECT deps; included flows bring their
OWN deps (KB 43160 via Append Guidance; Idempotency Ledger 134639 via
claim/finalize; Release Telemetry 157628). CLOSURE PROCEDURE: for every
flow included in a manifest, GET /api/export_manifests/folder_assets on
the FLOW's folder and union the deps — one level of transitivity is usually
enough for these helper flows, but verify each new asset type's deps too
(agentic_knowledge_base carried none). pkg 42184048 = full closure (18
files). LESSON: never build a manifest from the top recipe's dep list
alone; walk the included assets' own deps.

## KB-REFERENCE RESOLUTION (import failure #2, 2026-10-09)

Second import failure, SAME error after adding the KB: recipes reference
knowledge bases by ZIP PATH inside the flow JSON —
"knowledge_base_id": {"zip_name": "<full path>", "name": ..., "folder": ...}.
The import resolver matches the reference against the ZIP's internal file
paths. The KB asset's manifest entry must therefore carry zip_name = the
EXACT path string the referencing flow stores (folder = same path minus the
filename, no 'All projects/' prefix), or the file lands at the wrong zip
path and resolution fails even though the tree preview shows it as Add.
FIX: set zip_name+folder from the referencing flow's stored reference
(extract with regex over the recipe JSON inside the old zip). pkg
42184065 = KB at the referenced path, verified in the archive.

## MCP TOOL-DETAILS DIALOG TRAPS (2026-10-09, v8 round)

- "Edit tool details" Save button stays DISABLED when the description was
  set via native-setter/input events (Angular form never marks dirty) or
  even via orca fill (a11y) — the text RENDERS but the form model doesn't
  register. Working sequence: focus textarea → select() →
  document.execCommand('insertText', false, text) → Save enables → click.
- Even with Save enabled, synthetic + a11y + semantic clicks may all no-op
  on this dialog; pressing Enter with focus in the Title input submits the
  form (navigates away after saving).
- workato-registry list_tools serves a CACHED tools/list snapshot — after
  editing a tool description, verify on the Workato server PAGE (rendered
  row text), not the registry. Josh also re-saved the description manually
  (2026-10-09) to force it through.
- Verify description-scope reads: tool name and description live in
  SEPARATE containers on the server page — reading the row's ancestor may
  miss the description entirely and report "says200: false" wrongly.
- Real-caller job ordering: mcp_handle values in EDW_DB.WORKATO_USAGE can
  churn between runs (same recipe_id under different mcps handles minutes
  apart) — OFFSET paging over a living warehouse can shift row identity
  mid-iteration. ORDER BY keeps page order stable per call; cross-call row
  drift is inherent to the data layer, not the recipe.

## CURSOR-PAGINATED MCP TOOL — SMOKE-TEST DECODE + DEV SQL PROBE (2026-10-09)

Smoke testers misread cursor-jump pagination as bugs: after a short page,
next_cursor JUMPS (e.g. 2 -> 100) to roll to the next bucket; sequential
"pages 3 and 4" past the data are empty BY DESIGN and the tester reads
them as "the tool only has one month". Fix = guidance ("follow
next_cursor verbatim; stop only at null"), not code. Jump encoding used:
cursor = month*100 + chunk (0-99 = current month, 100-199 = previous...).
- BROWSER-FREE SQL PROBE (invaluable when wt CLI stop/start cycles keep
  killing the Orca browser session — they do, "session expired because
  you switched workspaces in another tab"): build a SCRATCH recipe in the
  DEV workspace with a clock.scheduled_event trigger (connector module is
  `clock`, trigger action `scheduled_event`; force-run is scheduler-only),
  paste the SQL to verify (hardcoded constants, no pills), attach the dev
  "Snowflake | PROD | Recipe Usage | Schema: ALL (integration@...)"
  connection (16206277, same EDW_DB.WORKATO_USAGE as prod), push, START
  then `wt recipes force-run <id>` (the enqueued handle differs from the
  job that runs; list jobs to get the real one), then dev job_get reads
  the step output = ground truth for SQL semantics.
- Note: dev connection ran the same query in 80s vs prod's 24s (different
  warehouse/user) — perf conclusions need the prod connection.

## MONTH-PARAM PATTERN (v9, final form of BSYS-29443)

For cursor-paginated MCP tools: add an explicit `month` (or date-range)
param NEXT TO the cursor so humans/can address buckets directly — cursor
jumps (2 -> 100 at a month roll) read as bugs in transcripts and clients
with stale schemas can't follow the chain at all. Rule of thumb: cursor =
continuation within a bucket (agents handle natively), month/range param
= bucket addressing (humans handle natively). month_index =
cursor.blank ? month.to_i : cursor/100; next_cursor = mi*100 + c%100 + 1.
September (full month, 17K-call tools) ran 79s vs October's 24s — budget
~3-4x the current month for older full months; still far under 4:00.

## CACHE-ARCHITECTURE FINAL FORM + DATA-TABLE BRIDGE SPEED (2026-10-09)

Hot path for Snowflake-backed MCP tools: recipe loop pre-aggregates into a
WORKATO DATA TABLE on a schedule; the MCP tool = keygen query (ms) +
get_records(limit 1000, output_format field_name_to_value) = WHOLE month
per call, ~2s, next_cursor always null. Clients never paginate.
- create_records_batch on this workspace's data-table bridge runs ~1
  row/sec: a 475-record month slice takes ~10-20 min. 24-month backfill =
  HOURS (background is fine; interactive is not). Data-table reads stay
  fast (~0.15s/1000) even under write load, though concurrent wt dt query
  with limit 1000 can time out while the filler writes.
- CRITICAL TZ RULE: never derive month keys from ruby slices of Workato-
  rendered timestamps ('2026-08-31T17:00-07:00'[0,7]='2026-08' but the
  same instant is '2026-09' in Snowflake session TZ). Both writer and
  reader must compute the key in SNOWFLAKE: TO_VARCHAR(DATE_TRUNC(
  'month', DATEADD('month', -N, CURRENT_DATE)), 'YYYY-MM').
- wt dt query --where filter is BROKEN (returns 0 rows for every value,
  even visibly-present ones) — page unfiltered with --continuation.
- Dynamic-list batch mappings in recipe_builder: use a python list
  comprehension ('[{...} for item in source]') — item pills render as
  records_item['key']; ruby() slices work INSIDE the mapping; [0,7]
  slices on raw pills do NOT (compile to bogus current_item refs).
- list_tool batch suffix keys (mcp_id_2cee2d89 etc.) are connector-output
  dedup hashes — get pills via get_datapills, never guess names.
Case: BSYS-29443 v10 (cache table 158060, filler 82929351, hot path
2.0s verified). REMAINING: overnight backfill; dev backfill.

## CLIENT-CAP PHYSICS + FINAL CONTRACT (BSYS-29443 v11, 2026-10-09)

Claude Desktop's MCP tool-result cap observed at ~32K tokens (~127K chars);
a whole-month fat response (466 rows x ~274 chars = 127K) overflows and the
harness dumps to a tool-results file. Final shape per Josh: keep FULL row
shape, cap pages at 250 rows (~68K chars ~ 17K tokens), cursor walks
pages within the month (month*100+chunk encoding, next_cursor full->+1,
short->next month, month 23 -> null). Cache read = 1.5-2.3s; whole call
~4s. DON'T rename/slim row keys unless asked — Josh prefers full field
names and more calls over terse keys.

## /triage 2026-10-09 build round — harness deposits

- **workato-health sweep noise floor**: ONE sweep found 65 mcp_mock probe
  failed-jobs across the estate — the probe class is estate-wide, not
  82090477-specific. The filter counts probes only when fail-count grows
  (bounded one jobs-list call per flagged asset) and downgrades all-probe
  verdicts to "ok" with "(N probe jobs excluded)" visibility.
- **VUA-No ≠ connection mode**: the server Connections accordion (61 of 62
  tools) lists List_Design_Systems among end-user-connection tools even
  though its VUA flag is No — the flag is consent-gating, routing is
  separate. No UI surface edits the flag; package route is the only path.
- **wt manifests API regressed/broken 2026-10-09**: create → 400 "Missing
  parameter name" (also 500 on file form), list → 404. The package
  export→edit→import route (needed for VUA personalization flips) is
  blocked on this. Debug the manifests wire format before next use.
- **runtime line N = DSL step N+1** (trigger is runtime line 0) when mapping
  job traces to pulled DSL; a pill mapped to a nonexistent output key
  renders as "" at runtime — invisible in succeeded-job noise, visible in
  job_get inputs.
- **cortex --add-dir residual**: --add-dir grants access but the harness
  ~/.claude self-modification guard still denies Writes under ~/.claude
  from headless dispatches. Findings write-back needs either a target
  outside ~/.claude or a scoped allow rule — Josh's call.

**Data-tables record API + wt trap (2026-10-09, from BSYS-29477 UAT):** record writes live on the
DEDICATED host `https://data-tables.workato.com` (path `/api/v1/tables/{table_uuid}/records/{record_id}`,
PUT=update, POST=create; table UUID required — numeric workspace IDs 404 on this host). Body shape
is the `document` envelope: `{"document": {"<column_name or field_uuid>": value}}` — keyed by
COLUMN NAME or field UUID, not the `data:` wrapper. **wt trap FIXED 2026-10-09:** the old
`wt dt create-record/update-record --data '<json>'` double-encode (cmd_dt passed the --data STRING
to request() which json.dumps'd it again) is patched in `~/.local/bin/wt` — request() now parses
string bodies once, and cmd_dt adds the `{"document": ...}` envelope automatically. Live-verified
round-trip on dev ws 3535597. Same patch fixed `wt manifests create/update` (auto `export_manifest`
wrapper), removed the phantom `manifests list` route, and corrected the docstring. Kit copy
`~/Documents/agentic-workato-kit/bin/wt` synced. GET single-record is still 405 on this API
(use the query endpoint with --where). Companion trap already on file: data_table_update (AIRO)
wipes rows — schema edits only. OpenAPI spec for the full surface:
`https://data-tables.workato.com/api/v1/openapi.json` (UpdateRecordRequest documented there).

## DEV BACKFILL NOTES (2026-10-09)
- Recipe IDs are WORKSPACE-scoped (dev ws 3535597 vs prod 3535598): the
  dev twin of prod 71768712 = dev 71099839. AIRO pull on a prod ID via the
  dev server = "permission denied" (misleading); find the dev twin by
  listing the same-named FOLDER (`wt folders list` + grep, or
  wt api GET "/api/recipes?folder_id=<dev-folder>").
- A Snowflake cache table in EDW_DB is ORG-WIDE: dev + prod hot paths read
  ONE table; only ONE filler needed. Dev twin needs only its own
  connection (dev 13690893 = same integration user).
- Edits to a dev twin replay exactly; re-register via editor Save after
  schema changes, then test, then start (same SOP as prod).
- CLOSED 2026-10-09: BSYS-29443 (Closed/Fixed). Final estate: prod 71768712
  + dev 71099839 (both running, cache-read) + filler 82929351 (6h, one
  CREATE OR REPLACE statement) + Snowflake cache table
  EDW_DB.WORKATO_USAGE.MCP_TOOL_CALL_STATS. Data table 158060 DELETED
  (superseded). Scratch probe 82928794 still in dev harness folder.

## LEGACY-TREE MINING (2026-10-10) — platform lessons recovered from ~/Documents/ChatGPT + ~/Documents/Claude

Dedup pass against the whole legacy tool trees. Everything below was in
plan/evidence docs that pre-date or escaped the knowledge tree. Seismic and
Google Calendar project state went to their own project files; VUA/MCP-client
ops went to domains/mcp-operations.md; Workday/WQL went to domains/workday-platform.md.

**VUA / connection model**
- VUA runtime connections PIN a connector revision: releasing a new custom-connector version does NOT refresh existing caller RUCs — end user must re-connect (no in-place version refresh exists, no registry/recipe workaround). (GW asset ledger)
- VUA classification is not inferred from using a VUA-capable connection: the skill attachment metadata must say `VUA Required: Yes`. A direct-array attachment stayed classified non-VUA even after remove/re-add (recipe 82763715 permanently detached). (Seismic)
- Password-type connector fields (e.g. client_secret) are STRIPPED from runtime user connections unless the field sets `preserve_in_runtime_connection: true` → "connections currently unavailable" with no job created. Re-consent (not recreation) picks up the fix; tradeoff: secret copied into every RUC. (Gmail v3 evidence log)
- Every AIRO push to a VUA-backed recipe can wipe `personalization: true` from connection config — re-check after every push (targeted single-recipe package re-import was the fix). Confirms the known VUA-revert trap. (Gmail v3 evidence log)

**AIRO / builder traps**
- `recipe_builder_save` ALWAYS creates a NEW recipe id — save once, then push on the session; never save repeatedly. (GW handoff §13)
- `remove_input_field` fails "Field not found" when the field's current value is literal `None` — workaround: `set_input_field` the whole parent object keeping only wanted keys, or remove/re-add the step. (BSYS-27874 dump)
- Workato editor saves rewrite recipe-function `flow_id` from numeric to label, then start-validation rejects it as blank — after ANY editor save, repair `flow_id` via set_input_field and push before starting. (GW asset ledger)
- Genie→skill trigger conversion is IMPOSSIBLE in place (trigger type locked, "cannot be replaced") — the 20 genie-trigger clones had to be rebuilt as new `workato_skill` recipes; plan one rebuild pass. (Gmail evidence log)
- Custom-connector SDK: Ruby thread fan-out REJECTED by hosted runtime (sanctioned pattern = registry-declared multiplexed HTTP-batch transport, bounded companions, fail-closed per member); `retry_on_response`/`retry_on_request`/`max_retries` are NOT valid action keys (hand-build bounded retry); reusable `call(...)` helpers invoked from design-time `input_fields` can fail semantic validation (inline date windows); numeric controls often arrive as STRINGS — normalize before bounds checks. (Seismic/GW ledgers)
- Recipe-side remedy for array type erosion: `ruby()` passthrough in RETURN mappings keeps inner arrays real (typed Ruby binding beats string interpolation; 698B vs 2,171B padded). (Gmail v3)

**Ruby snippet sandbox traps (GW asset ledger)**
- `lambda` is mangled by the platform and silently returns wrong values; `#{...}` interpolation is mangled by the pill preprocessor (use string concatenation); bare top-level `return` raises "unexpected return"; avoid top-level constant assignment. Array datapills arrive as Ruby-inspect text with raw Time objects — parse by scanning `{...}` blocks with per-field regexes, never JSON.parse.

**Data semantics / correctness patterns**
- First-1000 starvation: capped UNFILTERED `get_records` returns insertion order and silently drops rows that sort late (hex UUIDs) — filtered reads are sort-independent, capped unfiltered reads are not; always `order_direction=desc` on recency reads. Miners re-created existing candidates as NEW because of this. (GW)
- Data-tables query API accepts a `sort` key but SILENTLY IGNORES it (insertion order always) — walk pages for newest-write facts. Record writes: `PUT /tables/{uuid}/records/{id}` with full document under `document`. (GW)
- Duplicate-write bug class: an unconditional write AFTER an if/else inside a loop executes every iteration — verify by trace, exactly one write per candidate. (GW architecture doc)
- Delta-accumulation double counting: incrementing stored counters with per-run deltas anchored on a window end double-counts post-window events — use an idempotent window RECOUNT (recompute each run, skip when unchanged). (GW)
- Published schema default vs action fallback drift: schema-aware clients bypass a recipe's action fallback because the published trigger schema still declared the old default — keep them in agreement, audit both after any default change. (Calendar optimization log)
- MCP isError gap: `workato_genie`/`workato_skill` recipes expose `workflow_return_result` but NO per-invocation MCP isError — clients see success even from catch branches. Compensate: mandatory structured envelope `{success:false, error, errorCode, retryable:false}` + per-class retryability policy + per-item fail-open for batch partials. (Calendar error-handling contract)
- Connection-lost blocks recipe START with no API/CLI bypass (only owner reauthorization repairs); Marketo quota signature `Daily quota '100000' reached` kills the OAuth connection validation too while the parent job stays Successful under catch. Scheduler minimum accepted interval = 5 minutes. (Event360 — details in that project file)
- Registry/contract fix class-sweep rule: a projection fix on one intent-key tuple left 4 sibling variants broken (each carries its own input_contract enum) — contract fixes sweep EVERY tuple AND its enums, then verify one per variant. Registry checksums are PER-SERVICE (one global checksum goes stale for mutations). (GW)
- Import stop-prerequisite: prod package import can report "Recipes require action: stop" — record the exact restart set BEFORE stopping (29 recipes here); verify environment auth before lifecycle ops (CLI profile lacked prod auth; browser is the fallback). (Gmail package 41859252)

**Techniques (reusable)**
- Empty-string padding tax: 69% of scalars in a default Calendar list_events response were empty strings — apply `skip` semantics to optional scalar mappings (keep booleans/arrays/IDs directly mapped so valid `false` survives) + compact default projection = 10.24× cut, smaller than native Google's response. (Calendar optimization log)
- Forced-pagination proof: temporarily shrink page size (1,000→400) to force loop iteration across the old boundary, then restore — proves continuation-token behavior without fabricating a 5,000-row fixture. (Org Chart)
- While-loop scalability pattern: seeded-first-page + repeat-while-continuation-token loops asserting each token advances (non-advancing token fails at the execution boundary) — removes fixed row ceilings while keeping snapshot-version pinning per page. (Org Chart)
- Stress-test methodology: three escalating profiles — standard (ramp + sustained waves + mixed functional/security), validated ceiling (zero-error concurrency), extreme overload probe (first timeout boundary) — each ending with a recovery probe, all on one pinned snapshot version, total requested/completed/valid accounting. (Org Chart stress report)
- Latency attribution gate: attribute end-to-end across routing/backend/serialization/transport/rendering BEFORE optimizing. Repeated tool calls → fix instructions; direct-MCP p95 >10s → backend; direct fast but chat slow → payload/instructions/rendering. Merge an internal function into the public skill only when the function/wrapper boundary consumes ≥20% of backend latency. Add only the smallest proven-necessary index. (Org Chart latency plan)
- Snapshot architecture (generalizable): versioned snapshot + derived search index + denormalized closure index, built under an unpublished version, validated (counts/refs/cycles/hash parity), atomically promoted via one shared pointer, previous version retained for rollback, older versions batch-deleted; never expose partially built indexes or mix versions. (Org Chart)
- Benchmark discipline: a run contaminated by a concurrent session on the same mailbox produced false regressions — rerun only when the target is quiet; measure `tools/list` catalog cost separately (39 tools ≈ 9,989 tokens); `ceil(chars/4)` labeled as estimate. (Gmail MCP)
- Red-team false-success pattern: `create_filter` returned `success:true` with an EMPTY filter ID (nothing created — proven by before/after list_filters inventory) — verify mutations against INDEPENDENT state, never the tool's own success flag; connector converts empty returned ID to `UPSTREAM_INVALID_RESPONSE`, same guard stops update_filter deleting the original when replacement creation fails. 8-phase campaign: surface/identity, contract fuzzing, inert prompt injection, access boundaries, mutation durability/replay, attachment lifecycle, pressure, regression. (Gmail v3 red-team)
- `workato recipes list` CLI fails on pydantic `code=None` (project-property-driven telemetry env must flip to `production` at promotion); reconciler overwrote `tool_generation` historically; Gmail MCP catalog has NO delete-draft tool. (Gmail v2/v3)
- "Normalize at the proposer, gate hard at the reviewer" — seeder strips punctuation/collapses whitespace; promotion gate stays strict as defense in depth. Honest-evidence rule: a masked 403 `USER_NOT_ALLOWED` probe proves the entitlement BOUNDARY, never positive tenant data; fixture-backed mutation tests are contract proof, not tenant proof; never convert absence of fixtures into a fake happy path. (GW/Seismic)
- Folder taxonomy convention (Seismic + GW): `MCP Server` / `MCP Skills` / `Functions` (shared functions + infra tables) / `Automation` (schedules, purge, TTL) / `Connections` / `zArchive`; moving an asset to a folder named `zArchive` auto-removes it from dynamic RecipeOps monitoring scope (retirement, NOT a staging area — unreleased assets stay monitor-visible in an active folder); never delete platform-created empty folders (unrecreatable).
- RecipeOps dynamic-discovery monitoring design: project-scoped discovery (no hard-coded allowlist, no workspace-wide scan), alert evaluator materializes deduped state for recipe_not_running / latest_job_failed / connection_not_authorized, every bounded get_records source checks its continuation token — second page emits ONE capacity alert and stops (fail-closed, never partial-scope evaluation). (Multi-Genie)
- Workato CLI project pull is blocked by unsupported `agentic_card` asset types — fallback: raw Workato export API scoped to the single Genie asset. (Multi-Genie)
- Jira connector traps: never copy custom-field IDs across tenants; select-type fields need internal option IDs (never the display label — preserve unresolved values in description); control characters in Slack-copied text make raw Jira JSON invalid — sanitize at the outbound boundary and fail closed, no auto-retry. (Multi-Genie BT specialist)
- Genie platform facts: API Platform endpoints have independent activation state (starting the recipe is NOT enough — ingestion silently fails until the endpoint is activated); `send_business_event` gives the model NO trustworthy business-event flag (callback markers are display-only); no truly reply-silent Genie Slack response exists (empty output renders literal "(no response)" — supported clean pattern = one compact root notification + one exact preformatted reply, then stop); Decision Models do NO NL intent extraction (ordered rules on structured input only — safe as shadow evaluator, never dispatcher); after editing/restarting an attached skill recipe, wait for Agent Studio skill re-registration and ALWAYS test in a NEW source conversation (existing ones retain prior state, failures, and the tool catalog they started with); wrapper-Genie job description must MIRROR the source MCP contract (capability scope, preferred sequence, deprecated labels, auth semantics, bounded call shape); Slack does not render Markdown pipe tables (convert to compact bullets without changing values). (Multi-Genie)

**Workato AI gateway — hard ~60s first-byte deadline (WKTO CLI diagnostics, harness-reproducible)**
- Non-streaming calls to `https://ai.preview.workato.com/anthropic/v1/messages` hit HTML 504 at ~60s: Kimi K3 fails at ~18.4K-char generated tool arguments, GLM 5.3-flash survives to ~36.5K. Two signatures: Kimi premature `end_turn` (model decision, not transport) vs large-session 504 (cold prefill approaching the proxy deadline even while streaming — fresh sessions worked simultaneously). Mitigations: compact/fresh long sessions before prefill nears the deadline, pass references/hashes instead of regenerating large blobs in one tool call, keep SSE streaming, prefer GLM for large tool arguments. Repro harness: `~/Documents/ChatGPT/WKTO CLI/diagnostics/gateway-agent-loop.mjs`.



## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Workato GO](../../kb-corpus/docs/en/agentic/workato-go.md)
- [The Workato KB: RAG++ over all documentation, and the dreaming team](../../kb-corpus/confluence/extbt/2938929237-the-workato-kb-rag-over-all-documentation-and-the-dreaming-team.md)
- [Product Scoop &#8211; May 2025](../../kb-corpus/changelog/product-scoop-may-2025.md)
- [Workato ONE : The WoW Release](../../kb-corpus/blog/workato-one-wow.md)
<!-- kb-bridges:end -->

### STANDING RULE (Josh, 2026-10-11): dev connections NEVER travel with manifests

What burned the last deployment: a dev connection promoted with a manifest
overwrote a prod connection. Rule: manifests carry recipes/tables/functions
ONLY — zero connection assets, always. Connections referenced by batch
recipes must pre-exist healthy in prod (untouched) or be provisioned
separately in prod + re-pointed post-import. Verify the package ZIP has zero
.connection.json files pre-import and diff the prod connection inventory
before/after import as an AC. Orchestrator Phase 0 rewritten accordingly
(the earlier "include missing connections in the manifest" guidance was
WRONG and is superseded). BSYS-29498 is in Final Tech Review under this rule
(package 42196483 verified zero connection assets; component Workato AHQ |
AI id 11024 required by the Submit-for-Tech-Review screen — component names
cannot be created via API, pass the existing id).

- CORRECTION (Josh, 2026-10-11, same day): all referenced prod connections
  (RecipeOps 14390516, Workato API 16521378, Workday REST 19234290) already
  exist — the "provision separately" framing was wrong. The post-deployment
  JOB = re-point imported recipes to the EXISTING prod connections where the
  import doesn't map them (wt recipes update-connection), then verify green
  jobs. Root of the false positive: dev connection names embed the dev
  workspace id ("RecipeOps (Current workspace: 3535597)"), prod names don't
  ("RecipeOps") — connection name-joins must strip workspace-id suffixes
  before flagging missing-in-prod. Comment 1134905 on BSYS-29498 carries the
  re-point map.

## ⛔ POST-IMPORT LINKAGE LAW (Josh 2026-10-11 — standing rule, enforcement built)

**Rule:** dev connections and dev env-scoped linkage ids must NEVER survive an
import into Production when a documented prod linkage exists. Connections are
never packaged (zero .connection.json in any manifest/ZIP). Imported recipes
are re-pointed to the documented prod connections, and every env-scoped
handle is re-verified against the target-env picklist, BEFORE the promotion
stage counts complete. Exceptions only when Josh explicitly states them in
the batch story.

**Why:** two incidents, same class. BSYS-29283 (2026-10-10 02:56 import):
16 live recipes bound to import-created stub connections → mass stop;
and the 2026-10-10 P2: the same import overwrote the HR Genie messenger's
`chat_trigger_handle` with the DEV option id (ginct-AbbxJxmX-gchtnT-CD) →
EVERY send_business_event failed "Genie is not found or has not been
started" for ~15 h while jobs stayed green (the step monitor caught all) and
the monitor deduped the outage to "10 occurrences". Trigger handles are
env-scoped `genies_and_triggers_flat` picklist ids — the import's RLM remap
rewrites genie_id but NEVER the handle; "the ids look right" is not a
verification.

**Enforcement (built 2026-10-11):**
- Registry: `~/.claude/knowledge/registries/prod-linkages.json` — documented
  prod connections per stable app (HR Genie, Workday MCP/Workday) + the full
  prod genie trigger-id map + the handled-error table id. Refresh after any
  genie/connection add or remove.
- Script: `~/.claude/knowledge/scripts/import-remap.py` — per recipe:
  connection account_id scan vs registry (stub/mismatch = fail), genie-step
  detection with exact fix commands, and `--canary` (fresh-job trace must be
  catch-free + zero new handled-error rows since the import ts; `--induce`
  force-runs schedulers; `--fix` executes rebinds — still Josh-gated).
- Gates: post-deploy-smoke checklist steps 3 (linkage remap) + 5 (live
  canary) — MANDATORY; manifest-hygiene checks 6 (zero connection assets) +
  7 (env-scoped linkage scan → named remap targets in the story);
  promotion-orchestrator Phase 4b (a stage isn't done until remap + canary
  are green; verdicts recorded in the story comment).
- Repair recipes: `wt-prod recipes connect <rid> --data '{"<provider>":
  <prod_account_id>}'` for connections; AIRO
  `recipe_builder_set_input_field_v4_mode` (mode=plaintext) on every send
  step for trigger handles (plain set_input_field JSON-stringifies values —
  deposited trap). Verify a start took a fresh tick (starts can silently
  no-op).

## Data-table TTL sweeps: delete_records_by_condition caps at ~200 rows per run (2026-10-11, BSYS-29504)

A nightly TTL sweep whose delete "does nothing" may actually be doing 200
rows/night against a faster inflow. Symptom: expired rows survive many
cleanups while every nightly job shows `succeeded` and the visible run
deletes exactly 200. Fix: wrap the delete in a `repeat` block whose
while_condition keeps looping while `deleted_count > 199`, draining the
backlog to zero (verified live: 1051 expired plan rows -> 0 in one forced
run, exit batch 51). Same action: date-time compare filters pass either
`op_date_time: "lt"` with a runtime-evaluated `=now.utc` formula string or a
clock.get_time datapill — both evaluate correctly; the operand/pill format is
NOT the failure mode to chase first, the batch cap is.

## recipe_builder value-setting: plain set_input_field wraps strings in quotes; use v4 mode (2026-10-11, BSYS-29504)

`recipe_builder_set_input_field` with `value="some string"` stores the value
WITH embedded quotes (path/mnemonic/text all confirmed) — the stored literal
then contains `"..."` characters and breaks URLs/expressions. The reliable
contract: `recipe_builder_set_input_field_v4_mode` with explicit `mode` —
`plaintext` for literals (NOT json; json stringifies hash-shaped fields),
`datapill` for step['path'] references (a plain set_input_field stores the
pill expression as a literal string instead of a mapping). Condition rhs
values passed through set_condition also need the bare literal (`"true"`, not
`"\"true\""`).

## New-recipe start fails "account_id can't be blank" = unbound connection (2026-10-11, BSYS-29504)

Start validation reports per-step `account_id: null, can't be blank` when a
step's connector has no bound connection — even for connectors that usually
need none. Bind BEFORE start via `recipe_builder_select_connections` mapping
provider -> account id (slack_bot 22250688 and the gateway runtime connector
22117414 in dev); re-push after selection, then start. connectionless
providers (clock, workato_db_table, workato_variable, workato_custom_code,
workato_recipe_function) stay null and validate fine.

## Daily mutation-chain drill pattern (BSYS-29504, drill 82964017)

Scheduled exercise of the full compile -> prepare_confirmable_mutation ->
prepare-plan fn (82284937) -> claim fn (82285042) -> commit_confirmed_mutation
chain without touching the gateway: read the reviewed tuple row straight from
workspace_semantic_registry (147343, filter index_key eq), feed all 12
contract columns + semantic_facts_json into compile_reviewed_operation, gate
on compiler_status READY, prepare under actor_scope_key canary:sandbox, call
the two functions (confirmation_policy/confirmation = intent_scoped), commit.
BatchUpdate typed ops take a facts `operations` array: `[{"op":
"create_slide", "object_id": "drillslHHMMSS"}]` — a deterministic object_id
makes the undo chain (delete_object on the same id) trivially assertable from
`replies.createSlide.objectId` in the commit receipt.

### Manifest closure audit (BSYS-29498, 2026-10-11 — the other half of the same lesson)

- **A manifest holding only the batch's recipes is always wrong.** The Oct-2026
  batch manifest had 11 recipes / 0 tables / 0 functions while the batch called
  4 functions (Record Pipeline Heartbeat 82959725, Emit App Event 82862028,
  sanitizer 82915212, Record Handled Error 76419393) and 7 data tables
  (156841 Schema Registry, 156842 App Event Ledger, 156843 Coverage State,
  156849 Collector State, 156850 Topic Taxonomy, 157686 Source Event Facts v2,
  158559 Pipeline Heartbeats) — all missing in prod.
- **Assemble FROM THE BUILD LEDGER** (it knows every asset per folder/ticket),
  then closure-audit the code: per recipe `fetch('/recipes/<id>/code.json')`
  in-page, extract flow_id/table_id/project_property pills (strip backslashes),
  recurse through discovered functions to fixed point. One command:
  `import-remap.py`'s `closure_audit(rids)` helper.
- **Truth = the content endpoint** `/export_manifests/<id>.json` (signed-in
  tab): typed+named asset list. `wt manifests get` shows NO assets; the
  creation payload is not the truth; **an API update can be re-expanded by the
  platform closure** (a 10-recipe update ballooned to a 340-asset project
  closure incl. 14 dev connections) — re-read after EVERY update.
- **Deploy bot's ZIP listing (`asset_0.recipe.json…`) is anonymous** — CLI
  manifests name assets generically; the listing proves nothing about
  completeness. Its one signal: file-type counts (no data_table files for a
  table-heavy batch = this bug).
- **Manifest asset type strings:** recipe, workato_db_table, project_property,
  account_property, connection, agentic_genie, agentic_skill, mcp_server,
  api_endpoint, api_group, topic, canvas_page.
- **Properties policy:** env-specific/secret-valued properties NEVER travel
  (dev salts, "Environment=Development"); missing-in-prod properties are
  pre-created THERE with prod values before import (this batch: 4 telemetry
  properties). Connections: never (standing rule above).

### Manifest edit-view badges + prod folder prep (2026-10-11, BSYS-29498 staging)

- **Badge semantics in the manifest edit view:** "Added" = asset does not
  exist in the TARGET env (will be created). "Updated location" = the
  asset's FOLDER in dev differs from what the manifest recorded — it is
  dev-side folder drift, NOT "exists in prod" (verified: all 14 recipes and
  all 7 tables showed "moved"/"Updated location" while direct prod reads
  proved NONE of them exist there — dev ids 404 in prod, prod table census
  289 with zero matches). ⚠ "dependent assets not selected" = real graph
  deps left unchecked; ⚠ "dependent asset not found" = a dep that cannot be
  resolved at all (e.g. the UNREACHABLE "Workato API" connection
  13685697 — connections never travel; resolve post-import by re-pointing).
- **Prod folder prep:** a destination project root alone is not enough —
  create the dev-side subfolders in prod BEFORE import so imported assets
  land organized (done for BSYS-29498: Operational Monitoring 34162651
  [existed], Intelligence Platform 35774483 + Pipeline Watchdog 35774484
  [created] under prod root 30489368).
- **Folder API traps:** `wt-prod api GET /api/folders?page=N` misses whole
  subtrees (returned 121 folders, omitted 34162651 entirely — never use it
  for existence checks; GET /api/folders/<id> by id is the reliable read).
  POST /api/folders `{"name","parent_id"}` is name-idempotent (returns the
  existing folder on name match — safe to retry).

### Full-pipeline ruling (Josh 2026-10-11) + BSYS-29498 final composition

- **One wave, not two (Josh ruling):** "why would we do 2 waves if everything is
  ready" — the intelligence layer promotes as a UNIT so real prod data flows
  end-to-end from day one. Sparse dev test data was the only thing the
  wave-split was protecting; that's not a reason. Batch = 38 assets: 22 recipes
  (10 batch + heartbeat/emitter/sanitizer/handled-error recorder + rollup,
  correlator-2, gap miner, quality judge, weekly digest, retention sweeper,
  feedback consumer, coverage auditor) + 10 tables + topic 74141 + Analyst
  genie (38860) + MCP server (30188) + 3 skills. Package 42197872 supersedes
  all prior.
- **Exclusions are RULE-based, recorded on BSYS-29498:** Eval Harness + Judge
  Pass (would drive the PROD genie with eval prompts — prod-genie testing
  rule), TEST scaffolding, one-time migrations, the unwired Agent-Studio
  capture stack, Pipeline Watchdog recipe (dedicated Slack app resume item)
  while its heartbeat func + table travel.
- **Execution blockers (close quickly):** 6 telemetry properties pre-created in
  prod (Environment/Pseudonym Salt/Salt Epoch/Transcript Key/Judge Spend Cap/
  Retention Days — new prod-distinct secrets); post-import re-points (Workato
  API 13685697→22284446, RecipeOps 18143979→14390516); feedback-consumer
  subscription re-wired to the imported topic's new prod id; Analyst MCP
  server renamed (drop "(Dev)") + editor-save re-registration.
- **Post-import analyst surface:** the Analyst MCP is how the pipeline gets
  queried — rename + re-register immediately or the prod server serves a
  "(Dev)" name.

## 2026-10-11 — queue reversion root-caused: gardener git-checkout; triage recorder hardened

- **The reversion**: the brain-gardener's git subagent ran `git checkout -q -f main` (23:03 Oct 10) over a DIRTY tree, discarding the day's uncommitted triage decisions + outcome rows. Its safety-net `git apply` of the saved diff failed twice ("patch does not apply") and the run verified only INDEX/domains — the queue stayed reverted for 8 hours until the 23:33 backup captured it. Lesson: **`git checkout -f` discards uncommitted work silently; any agent doing branch gymnastics over the live knowledge tree must use stash-based flows or abort on dirty tree, and MUST verify the safety-net patch applied before moving on.**
- **Recorder hardened** (queue-append.py + triage-decide.py, snapshots /tmp/*.bak-20261011): append-dedupe now skips TERMINAL slugs (was open-only — re-filed 49 decided findings overnight when the checkout reverted them); record fan-out is per-row (skips already-final rows with a no-op instead of atomic-exit, so duplicate rows are collapsible); re-recording the same final state = idempotent no-op.
- **Parity guard live** (harness-health.py `check_queue_outcome_parity`): every final queue row must have a matching outcome action and vice versa; family-matching for truncated slugs (outcomes `bsys-29457` vs queue `bsys-29457-health-sweep-hygiene`), filed→built progression allowed, duplicate-seed mixed history tolerated. Verified synthetic + live; reversion alarms the same night now.
- **Latent (filed, unfixed)**: workato-health.py `triage_append()` does a whole-file atomic_write per dedupe hit — read-modify-write race vs triage-decide's save() and silently restamps ts (observed 03:09:59 Oct 11). Harden to per-row append.
- **Recovery pattern**: the outcomes log (garden-reports/triage-outcomes.jsonl) is append-only and authoritative — but it was ON THE SAME DISCARD PATH as the queue this time; recovery came from the session's own decision record. Backups (~/Documents/josh-orca, 23:33 nightly) capture damage as readily as health — a parity check, not a backup, is the real tripwire.

## BSYS-29503 observability build: four hard traps (2026-10-11)

Built 10 items across the six GW-Semantic observability recipes (monitor 82830607, computer 82888287, rollup 82889357, stall-watch 82893591, weekly 82888690, daily 82803096). Four lessons:

- **repeat-loop keyset pagination is BROKEN on this runtime — do not retry casually.** A repeat block (read 1000 desc → ruby process page → update_variables cursor → while more&bound) ran reads at ~80-130s per call where the IDENTICAL read at top level takes 40-150ms (two runs: 199s and 331s in-loop; a 2-page fixture job hung 3+ min on a 1,173-row table). The designed 60-read/50k-day loop was abandoned for a **static 8x3h slice cascade per day** (16 top-level reads, ~40-150ms each, 8k/day capacity, capped=backstop alert). Fixture proof: 1,135 rows in one day aggregated across 8 slices in a 0.85s job (job j-AbtJDskW-N4ATRn-CD / j-AbtJFJzX-QBP3cp-CD, throwaway recipe since deleted). If someone revisits loops: verify read latency inside the loop body FIRST with a 2-iteration fixture before building anything on it.
- **AIRO push can silently persist a STALE snapshot** (second confirmation): a pushed snippet change passed recipe_builder_push "successfully" while the platform kept running the old code (fixture job output had no new output fields; REST GET of the stored recipe lacked the new strings). Recovery: stop → push → **verify the stored code via REST** (`GET /api/recipes/<id>` grep for the new token) → start. recipe_builder_push alone is not evidence.
- **`output_format: field_name_to_value` on get_records RENAMES the dump keys** from underscored field IDs (`37d69c45_2470...`) to human names (`event_id`). Any snippet that chunks/splits on the field-ID prefix sees ZERO records (silent undercount to 0, job still green). The two formats coexist in one recipe fine — match the snippet's regex to whichever format the read emits. The original computer/rollup slices use the DEFAULT (field-hash) format on purpose.
- **`delete_records_by_condition` returns `deleted_count`** — usable directly for retention logging in digests (BSYS-29503 item 8: usage table pruned 200 defect-era rows >90d on first run; the rows had ancient `day` values from the v1 rollup defect). Also: `wt dt create-record` takes COLUMN NAMES (not field IDs) in the body; date columns accept ISO strings; first-run `op_date lt` prune of 200 rows was correct — verify with a full page-through for nil/out-of-range day values before assuming corruption.

## LIVING MANIFEST HOUSE STYLE (Josh, 2026-10-10)
Every build opens an export manifest at kickoff and updates it as assets
land; deploy-time assembly reads it instead of researching. wt manifests
create/update are FIXED (parse-once --data + auto export_manifest wrapper;
the cortex autopsy's "NOT applied" header is stale — fixes ARE live).
VERIFIED SHAPES: create `{"name","folder_id","assets":[]}` (assets REQUIRED,
empty ok); update REPLACES the asset list — read-modify-write via a git-
committed mirror `<repo>/manifests/<BSYS-id>.manifest.json`; asset entries
{"id","type"} suffice (server fills name/zip); `wt manifests get` shows
METADATA ONLY (no assets) and the .json route returns none either — the
update RESPONSE is the only asset-list source via CLI, so save it to the
mirror. Drift check: manifest-hygiene/scripts/manifest_drift_check.py.
HR Genie lesson (BSYS-29498): 11 recipes shipped, zero of the 4 functions +
7 tables they called, because the manifest was reconstructed at deploy time.

## Guard-branch / skip-with-log pattern (2026-10-11, gw_fleet_liveness_sentinel 82951201 v9→v10)
- **Skip-with-log guard on a blank resolution pill, live-proven end-to-end:** insert `if` (native `set_condition` operand `blank` on the pill) → structured ruby log step → `stop` (stop_with_error=false) INSIDE the if, happy path untouched below. Runtime semantics proven via a throwaway probe recipe (82964163, built+deleted): an adhoc HTTP 200 whose body LACKS the mapped key renders the optional integer pill as blank, the native `blank` operand fires (condition True), the structured log lands in the trace, and the `stop` ends the job **status=succeeded** with every later top-level step skipped — a clean no-op, never a failure. (Distinguishes from the line-551 trap: that one is ruby-formula `blank?` on booleans; this is the native condition operand on an absent pill — safe.)
- **Stop-with-log jobs are SUCCEEDED, not stopped/failed** — fleet monitors reading job status alone will not see guard-branch skips; read the trace marker (`sentinel_parent_id_empty`).
- **AIRO-built fresh recipes start-fail `account_id can't be blank`** even when the schema shows no account field: recipe_builder never assigns connector connections on a new recipe. Fix via raw `PUT /api/recipes/:id` with `config` as a **JSON STRING** (array form 400s "Must be a String"), each entry `{"keyword":"application","name":<provider>,"provider":<provider>,"account_id":<id>,"skip_validation":false}`; then start.
- **Structural diff trick for hot-swap proofs:** diff stored `code` fields of pre/post snapshots with step numbers and step-named variables normalized to neutral names (regex `# step: \d+` → N + rename map); the only surviving hunks are the real change plus pure renumbering — proves "exactly the guard, nothing else" in one pass.

## Test-case re-record via web_api: the browser-free path + the snippet `log` injection (2026-10-11, BSYS-29455 guard case on 82862205)
- **Full test-case re-record is possible WITHOUT the builder canvas.** The editor's own
  same-origin APIs, called in-page via `orca eval fetch(...)`: `GET/PUT
  /web_api/recipes/<id>/test_cases/<caseId>.json` (case definition: mocks + assertions),
  `GET /web_api/recipes/<id>/test_cases/mockable_lines.json` (EVERY step's stable
  `as` identifier `<dsl_name>_<uuid4>` + `mockability` (must_be_mocked / can_be_mocked /
  can_not_be_mocked) + allowed_checks). Step uuids survive recipe edits, so a rebuild
  orphans a mock only when the step was deleted or converted (async→sync keeps the uuid
  suffix: `call_recipe_async_4f4b` → `call_recipe_4f4b`).
- **CSRF: in-page fetch writes need the `X-CSRF-TOKEN` header from the `XSRF-TOKEN-V2`
  cookie** (meta-tag lookup finds nothing; no csrf meta exists). Missing header returns
  **HTTP 500 "Server error: <uuid>"**, NOT 403 — a 500 on a well-formed PUT is the
  tell. Always send `X-Requested-With: XMLHttpRequest` too.
- **PUT the FULL envelope** (the whole GET object with mocks/assertions modified) —
  atomic; a 500 applies nothing. The UI's own Save drops orphaned mocks from its payload
  (builder state normalizes to current steps) but does NOT add the must_be_mocked steps
  the rebuild introduced — those still fail the run with "must be mocked".
- **THE BIG ONE — test-run runtime injects `log` into EVERY Ruby-snippet output.**
  Neither the AIRO DSL nor the editor's `code.json` shows it, but a snippet whose code
  returns `{batch, batch_size, max_created_iso, fresh_count}` yields
  `{"output": {..., "log": ""}}` under a test run (proven on an UNMASKED cursor-guard
  step: `{'output': {'next_cursor_out': '', 'log': ''}}` while its declared schema has
  one key). So a strict object-equality (`equals`) assertion on a snippet output fails
  forever with `Extra keys: log` unless the expectation includes `log`. This IS the
  canon entry `collector-extra-keys-log-close` — the "extra-keys" failure class it
  names. Diagnostic signature: flip the expectation and the reported extra key flips
  (expect fresh_count → "Extra keys: log"; expect log → "Extra keys: fresh_count") =
  data has BOTH, expectation had one.
- **BSYS-29396 refinement:** "assert the RETURN step" + strict equals, but for SNIPPET
  steps the strict expectation must be `expected_keys + log` (value `""` is stable when
  the real output is deterministic). Volatile steps (checkpoint compute with live
  watermark/counters) must never get whole-object equals — pick the terminal static
  step instead.
- **Run evidence path:** `wt testcases run --recipe <id>` (public API POST
  run_requests) → `wt testcases status --run-id cirr-...` → job trace via AIRO
  `job_get` (public jobs API omits step traces). A passed run's `last_run_result` on
  the case JSON carries `executed_assertions: [{status: succeeded}]`.
- **CASE CREATE is browser-free too (2026-10-20, BSYS-29585 on 82272892) — the
  "UI-only" belief is obsolete.** `POST /web_api/recipes/<id>/test_cases.json`
  (in-page fetch, CSRF headers) scaffolds a BLANK case (`Untitled test case 1`,
  payload IGNORED — this is also where the fleet's scaffold noise comes from);
  then `PUT /web_api/recipes/<id>/test_cases/<caseId>.json` fills it. PUT
  contract learned by probe: params are FLAT (`{name, description, mocks,
  assertions}` — the `{test_case: {...}}` wrapper 422s "At least one parameter
  has to be present"); each assertion REQUIRES a client-generated `id` (uuid4)
  or the whole assertions array is SILENTLY DROPPED (200 + assertions_count 0);
  snippet-step mocks wrap the mock output as `{output: {...}}` while
  db-table/rest mocks stay bare. Build mocks from the CURRENT
  `mockable_lines.json` (every step's `as` id + mockability), never from an
  old case.
- **Recipe edits rot case mocks in three stages (all seen 2026-10-20, same
  recipe):** (1) orphaned mock identifier → job fails pre-execution
  "Some steps with mocks or checks were deleted from the recipe" (trace-less,
  ~0.15s, error_parts.error_type "Test Automation error"); (2) mock SHAPE
  drift — v114's materialize_semantic_retrieval_index emits
  `selection_partitions` which v109 mocks lack → the downstream plans snippet
  raises `SELECTION_PARTITIONS_INVALID` (error_type "Eval custom ruby code
  error" — the raise lives in RECIPE code, not the runner); (3) successor-step
  drift — a mock dropped as "orphaned" must be re-pointed at the edited step's
  NEW identifier, not deleted (missing upsert_record_529f mock → real
  upsert → "required field not set: 'updated_at'"). Repair method: GET
  case JSON, diff mock identifiers against fresh mockable_lines.json, PUT flat
  envelope. Verify persistence by re-GET (PUTs can silently drop params).

- **Test runs CANNOT hit ANY connector step live — "Missing connection" is swallowed by
  try/catch and 0-assertion cases pass VACUOUSLY (2026-10-25, GSlides Layout Quality
  Toolkit DR pass, 11 recipes).** In a test run, Google Slides connector steps (get_slide,
  batch update, transform — even on a shared non-personalized connection) fail with
  `Missing connection. Please establish connection manually` — same class as the WRF00400
  warning. If the recipe wraps its body in try/catch (skill-tool standard), the error is
  caught, the error-path release permit fires, and the job closes SUCCEEDED: a "happy
  path" case with mocks only on trigger+functions and 0 assertions proves nothing.
  Diagnosis: job trace shows the catch line with the error, try line `{'error': True}`.
  Fix: MOCK the connector steps too, feeding recorded fixture shapes (real element arrays
  captured via the mounted MCP Get_Slide/Get_Presentation; get_slide mock =
  `{elements, slide_id, speaker_notes}`, get_presentation mock = `{slides, slide_count}`);
  keep the custom-code (logic) steps REAL — they are the thing under test. To make a case
  BITE, add a `data` assertion (`{id: uuid4, step_identifier, source:
  {assertion_source_type: "step_output"}, operator: "equals", expectation: {output:
  {...}}, type: "data"}`) pinning the custom-code step's exact output — snippet outputs
  include the injected `log: ""` key, and dynamic fields (request_id, Time.now) must stay
  out of the pinned step. Proof of a non-vacuous run: `executed_assertions:
  [{status: "succeeded"}]` on the case's last_run_result, or a trace where the try line
  reads `{'error': False}` and the happy terminal return executed.

- **Quota-recovery residue (NEW, 2026-10-11, BSYS-28296):** after the
  Marketo daily-quota outage ends, the connection stays flagged
  `Not authorized` / `authorization_error: Daily quota '100000' reached`
  indefinitely. The underlying OAuth credential works again immediately —
  provable with `workato connections pick-list --id <conn> --pick-list-name
  my_lists`, which makes a real adapter call and returns live data (its
  pydantic "List should have at least 4 items" ValidationError is a CLI
  parsing bug, ignore it). But recipe START still fails
  `account_id: unconnected` because start trusts the persisted flag; the
  successful call does NOT clear it, and no CLI/API revalidate exists. Cure
  is the UI **Check connection** in the connection's own workspace. Watch
  the workspace: the Orca browser can be signed into a different workspace
  than the CLI profile (`workato workspace` shows the CLI's), so
  `/connections/<id>` 404s; the workspace switcher lives in the mobile
  sidebar drawer, and a cross-workspace switch forces a fresh Okta SSO.
  (Details in event-process-mcp.md.)

- **Loop-pagination idioms on skill recipes (2026-10-11, BSYS-28296, get_lead_activities 72856618) — hard-won set, all runtime-proven:**
  - **List items are WRAPPER OBJECTS.** A `declare_list` with item schema `{page_json}` + `insert_to_list` yields list_items as `[{page_json: "<json string>"}]` — consumers must unwrap `item["page_json"]` then `JSON.parse`. Reading items as raw strings silently yields nil fields (`last["more"]` → nil) inside a "succeeded" job.
  - **Post-loop list reads ARE live** (aggregate from list contents after the foreach works — re-confirmed; run j-AbtdFPYk). The 2026-10-10 "reads as declared initial value" trap applies to `declare_variable`/`update_variables`, NOT to list reads. Don't build return-inside-loop contortions over a stale-read fear — an in-loop `workflow_return_result` (else branch) left a skill job hanging "pending" 8+ min (never terminated); prefer the flat post-loop aggregate + return.
  - **AIRO push authors step-level `"provider"` on `foreach` blocks** → start-validation "provider is not allowed for this step type". The cure is a raw `PUT /api/recipes/:id` (code as JSON string) popping `provider` off the foreach step — `declare_list`/`insert_to_list` NEED their `provider: workato_variable` kept. Re-check after EVERY AIRO push of a recipe containing a foreach.
  - **Raw-PUT hazards:** (a) steps must stay INSIDE the try block and BEFORE the catch — anything after the catch (try-level or trigger-level) start-fails "no line expected after catch"; (b) renumber ALL steps depth-first after any structural edit or the validator IndexErrors; (c) scalar result pills must use the `=_dp('…')` assignment form — `#{…}` interpolation form on a whole value evaluates nil at runtime; (d) aliasing: `steps = steps[:i] + …` rebinds the local — mutate `try_b['block']` in place or the reorder silently no-ops; (e) rebuilding from a stale fetched JSON reverts earlier fixes — re-fetch immediately before EVERY PUT cycle.
  - **Dynamic-list per-key mapping drops its LAST key at runtime** (proven twice: mapping ordered […, attributes, activityTypeName] returned activities without activityTypeName). Keep the critical keys first and verify the returned key set in the trace, not just the job status.
  - **Test-run sandbox quirks (test-case runs):** snippet outputs gain a `log` key (canon), and the skill response's `cursor`/`has_more` fields evaluated nil even with correct `=_dp` pills and non-nil aggregate outputs — verify caller-facing scalar fields on a REAL call before trusting the test harness for them.
  - **Test-case web_api writes:** UI Save works; API PUT of the full GET envelope still 422s "At least one parameter has to be present" (unexplained — capture the UI's own PUT body before attempting API-authored assertions). Trigger-mock JSON: the editor is CodeMirror 5 — `document.querySelector('.CodeMirror').CodeMirror.setValue(JSON.stringify(obj))` (setValue needs a STRING; object form throws). Case rename works via `document.execCommand` on the title's contenteditable span.
- **Stale Not-authorized after quota recovery (2026-10-11):** once headroom returns, the connection page's **Connect** button (fires `POST /connections/test_async.json`) clears the flag immediately — no re-auth needed. Recipe then starts normally.

- **Estate Monitor evaluator builds (2026-10-11, BSYS-29511, agent EVAL; recipes 82966988/82966998/82967004, ledger docs/estate-monitor/BUILD_LEDGER.md):**
  - **Scheduler trigger module is `clock`** ("Scheduler by Workato") — `recipe_builder_list_connector_operations` on `workato_scheduler` returns nothing. Trigger action: `scheduled_event`. Daily cadence (`time_unit: "days"`) REQUIRES `trigger_at` (e.g. "03:00", control_type time); minute-level repeating (`"minutes"`) must NOT have it (reconfirms lowercase time_unit law).
  - **JS snippet plumbing (`js_eval.invoke_custom_js_code`):** input values go at `code_input.data.<field>` (NOT `code_input.<field>` — rejected as not-in-schema); declare them first via `code_input.schema` as a JSON schema string; output pills are NESTED: `invoke_custom_js_code_N['output']['field']` — bare `N['field']` fails DatapillInvalidPath even though code_output_schema_json names the fields flat.
  - **Account properties compile as `account_property('Environment')`** — method-call form. Bracket form `account_property['Environment']` fails formula validation ("wrong number of arguments (given 0, expected 1)").
  - **No `>=` set_condition operand** — express `count >= thr` as lhs=count pill, operand=greater_than, rhs=`ruby("bindings.thr.to_i - 1", bindings={"thr": <threshold pill>})` (ruby in rhs is legal).
  - **Connection-health proof for connection| incident recovery:** RecipeOps (`workato_app`) `search_connections(name=...)` exposes ONLY `authorization_status` / `authorization_error` / authorized_at — NO connection_lost_at/lost_reason. Resolve-on-recovery only when connection found AND authorization_status=success AND authorization_error blank; otherwise leave open + log (never resolve on a guess).
  - **Cross-iteration counters:** don't thread stale/resolved counts through variables (update_variables staleness) — recompute at cycle end in one JS snippet from bound `.to_json` snapshots (before/after open-incident diff for resolved; registry recompute for stale). Backward-only refs keep it legal without mid-recipe inserts (which would renumber and orphan ruby() bindings).
  - **Push guardrail false positive:** `recipe_builder_push` prints "[workato-guardrails] Push risk: no recipe tracked for this session" even when the push SUCCEEDED ("Recipe updated successfully", target platform) — verify via fresh `recipe_get` instead of retrying.

## Polling triggers on external content are LOSSY on updates (2026-10-11, BTSUP-76729)

Confluence collector 71498060 (HR Genie Confluence) missed two page-update
events on the same page. Evidence from a full 764-job walk: (1) edits made
while the recipe is STOPPED are lost permanently, restart does NOT backfill
reliably, a Jul 21 restart rescan skipped a page mid-walk (delivered both ID
neighbors, skipped the middle page); (2) Confluence-side enumeration was
clean, so the skip is inside the trigger's poll walk (working theory:
pagination seam, pages shifting between limit-250 cursor batches, unprovable
from outside); (3) duplicate deliveries within minutes are normal and
harmless for doc_id-keyed upserts. ID-cursor position does NOT block update
delivery generally (232/235 deliveries were below-cursor pages). Rule: any
KB/content mirror on a polling trigger needs a scheduled version-compare
sweep against the source as the trust boundary, plus a backfill check after
any stop/restart. Full writeup: projects/hr-genie/btsup-76729-collector-miss-mechanism-2026-10-11.md

- 2026-10-11 (watchdog live verification, corroboration): `wt recipes get`
  last_run_at reported 15+ HR Genie schedulers 48-128h stale; live
  `wt jobs list` disproved every one (all ticking <15h, most <1h; e.g.
  82872626 Feedback Poll Consumer: wt says Oct 8, live newest job Oct 11
  20:08). Confirms the existing note below - use job_list for stall checks,
  never recipe_get.last_run_at. (bus thread: wt-last-run-at-stale)

- **CLI-created export manifests — four gotchas (2026-10-12, BSYS-28296):**
  (1) Source folder SCOPE: a manifest created at a subfolder (e.g. MCP
  Skills) cannot resolve assets in sibling folders (Functions) — the UI
  shows "asset_N Not found / we cannot locate some assets in the source
  folder". Create the manifest at the PROJECT-level folder so all asset
  folders resolve. (2) Update with hand-shortened zip/folder paths
  silently DROPS rows that fail re-resolution (the UI tree loses the
  asset; API echoes it fine) — always update with the platform's OWN
  rows verbatim from `wt manifests assets <folder>` (project-name-prefixed
  paths; they resolve in-place when source and destination projects share
  the same name). (3) The content endpoint (in-page GET
  /export_manifests/<id>.json, key `result.assets`) is the truth; the CLI
  GET returns metadata without assets. The FORCED transitive closure
  expands updates to the full app closure (skills ← server ← recipes).
  (4) VERIFY VISUALLY in the UI (screenshot the manifest content page)
  before filing the story — API checks alone miss Not-found rows; and
  verify the EXPORTED ZIP's member paths + the shipped recipe JSON
  actually contains the fix (download_url on the package object).
  Skill-tree checkboxes: real-mouse click at the
  `.manifest-tree-item__checkbox` coords (custom checkbox, no visible
  input change on JS click; two clicks toggle twice — verify state after
  each click).

### KB anti-rot: vendor source audit + additions (Josh ask, 2026-10-13)
Josh asked for a weekly sync guarantee on Workato docs + developer API docs + developer blog. Audit result: ALREADY DAILY (stronger than weekly) — docs.workato.com llms.txt ETag sync covers the whole developer surface (sections: API platform 62p, Developer API 40p, Embedded API 39p, Connector SDK 93p, CLI, Workbot 50p); The Connector blog + changelog + Automation Inspiration daily via wp_source; kb-audit 3x daily (9 checks incl. live retrieval probe) + sync source-count floor = the anti-rot teeth (floor proved itself catching the 2026-10-12 sync failure). developer.workato.com does NOT exist (www.workato.com/developers is marketing); docs sections are the developer canon. ADDED (commit 5541f53): community.workato.com Q&A crawler (server-rendered threads ~140KB each; members excluded as PII; 47 threads first crawl, cap 400) + github.com/workato/workato-connector-sdk (MIT) + custom_connector_docs — the KB had zero Workato-owned repos before. Both proven with scoped syncs before commit. LAW: check manifest section counts (manifest/docs.jsonl carries a `section` field) rather than path greps when auditing coverage — path patterns miss the section naming.

### Estate-monitor squad build lessons (em-builder-A, bus 2026-10-12/13 — canonized by harness-dreamer)
Six platform lessons from the BSYS-29565/29566/29589/29595/29600 squad build, verified live in that build; NONE covered by the KB docs (kb_search 2026-10-13: zero hits on the notify delivery contract):
1. **webhooks.workato.com notify delivery contract (OBSERVED, 2026-10-12, small sample):** every confirmed delivery carried Slack-native `event_id` + `event_time`; absence correlated with silent drops (9/10 drops in one window; positive confirmations n=2 — field presence was confounded with endpoint health, so treat as a delivery requirement to test, not proven platform law). The 15-min em-delivery-canary live-tests this route, so a wrong contract falsifies itself. This retroactively explained the 2026-10-12 "endpoint dead since 17:20 PT" incident (bus thread squad-estate-monitor-phase2, em-builder-A notify-delivery-key-found). Verify the JOB, never the 200.
2. **In-platform genie tool binding:** genie tools for in-platform genies MUST be recipe-backed skills (workato_skill trigger); external MCP servers (AIRO) cannot bind. Read-only toolset = skills over RecipeOps get_recipe/list_jobs + data-table get_records + Confluence search.
3. **KB ingestion path:** Enterprise context by Workato `upsert_documents` (doc-ID-keyed idempotent upsert, no WFS needed); KB create source_type recipe, recipe-fed. Idempotency proven: 9 docs sent 2x still 9.
4. **ruby() formula tokenizer:** expression string must CLOSE before `, bindings=` (silent 'unterminated string'); no `.map`/`.empty?`; bindings cannot hold whole-step output pills (DatapillInvalidPath path '') — bind leaf fields.
5. Emoji in f-string DSL values serialize as \uXXXX escapes (harmless, matches v1).
6. **recipe_builder step semantics:** `update_step` CAN swap triggers (webhooks->workato_webhooks); `remove_step` CANNOT remove triggers.
Skill-side (proposal 2026-10-13-em-build-lessons-skill-canon): these belong in airo-mcp-playbook (4,6) and a webhook-delivery note — skills are never_auto, awaiting Josh. Dissent note: lesson 1 is an observed contract (n small), not a verified MUST.

## Slack MCP blocks build — lessons (2026-10-14, BSYS-29680/29686 hotfix)

- **Prod adapter compile flapping:** package imports report `completed` while the
  prod custom-adapter RUNTIME serves older compiled artifacts — observed marker
  code from v52 persisting 20+ min across two later completed imports (v53/v54),
  and once a brief REGRESSION (v53 diag seen, then v52 marker again). Bisect
  results taken during a flap window are unreliable — re-run the cheapest
  payload after each import and treat early failures as suspect until a settle
  (~5-10 min) passes. Same family as the dev schema-service staleness.
- **MCP skill trigger array params arrive at connector actions STRINGIFIED** —
  the runtime renders the connector input pill to a String regardless of the
  adapter field's array type (diag: `arrived=String`). Connector actions taking
  structured input MUST accept both: `JSON.parse(value) if value.is_a?(String)`
  then validate `is_a?(Array)`. (The invite recipe's js_eval path got real
  arrays — js_eval `code_input` deserializes; connector action inputs don't.)
- **Slack `chat.postMessage` rejects `rich_text_list` without `"border": 1`**
  (invalid_blocks). Docs mark border optional; the API disagrees. Connector now
  auto-normalizes border=1 — and the tool hint documents it (hint edits reach
  the served MCP schema via recipe import within minutes; adapter code changes
  lag per the flapping above).
- **Slack `drafts.create` rejects `rich_text_list` entirely** (`invalid_message`)
  while rich_text sections (bold/italic) draft fine. Agents composing drafts
  with lists should use section blocks with "• " prefixes until Slack changes
  this.
- **Cascading Jira field gotcha:** the DR Source/Destination child option ids
  are JIRA customFieldOption ids, NOT Workato folder ids — resolve the real
  prod folder via the prod recipe's own `folder_id`, and grep each field's OWN
  editmeta tree (per-field option ids differ).
- `wt-prod packages import` crashes its own JSON printer on the binary response
  (TypeError: bytes) AFTER firing the request — read the import id from the
  traceback log (`grep -o '42229[0-9]*'`) and poll `wt-prod packages get`.

## HR Genie / recipe-function ops (BSYS-29783, 2026-10-19)

- **401-in-`call_recipe` diagnosis fast path:** check the CALLED connection's `connection_lost_at`/`connection_lost_reason` FIRST (`wt connections list <id>`). A connection that authed then died shows `authorization_status: success` (stale) while `connection_lost_reason` carries the real 401. Born: 96 silent HR Genie delivery failures Oct 12–18 from `Token invalid` on `CON | Workato API HR Genie`.
- **Env-twin trap:** re-authing a connection in the WRONG workspace fixes nothing and shows zero symptoms in the target env — always re-GET the prod connection's `authorized_at` before declaring a reconnect done.
- **Recipe-FUNCTION test cases can't run standalone:** Test Automation run on a `workato_recipe_function` recipe fails with `Test Automation error: Step can't be executed, it requires sample data` and a ZERO-line trace (`title: Processed event`) — that's a case-config error, not a recipe regression. Functions are proven via a real call site only.
- **Live-firing a function's normal path without UI:** create a tiny TEST webhook probe recipe (manifest-exempt if TEST-named; state the exemption verbatim), trigger = `workato_webhooks`/`new_event` with `webhook_suffix`, code = the trigger NODE itself with `"block"` children (NOT a `{"as":"root"}` wrapper — start fails `unexpected line` at step 0), one `call_recipe` step, start via REST, POST to `webhook_url`, read the child job off the target's job list (`calling_recipe_id` = probe id). Stop the probe after proof.
- **Empty catches in fleet functions:** the HR Genie pattern for observability inside a catch is `call_recipe_async` → `FUNC | HR Genie | Record Handled Error` (82120578) with static sanitized strings + `job_context` pills — async child failure never propagates into the catch, so the FAILED-return contract holds. Never put the raw catch message in the payload (it can carry user emails).

## BSYS-29515 build lessons (2026-10-20)

- **create_manifest.py verify vs Orca browser workspace**: the script's in-page read-back
  (/export_manifests/<id>.json) 404s when the Orca browser session is signed into a DIFFERENT
  workspace than the wt CLI profile — the manifest index in-browser won't show CLI-created
  manifests either (maxid lag is the tell, not a cache). Control-test with a KNOWN-OLD manifest id
  before concluding anything. Fallback verify path that PASSES the standing order: `wt manifests
  update <id> --file payload` → `wt packages export <id>` → `wt packages get <export_op_id>` →
  curl the download_url RAW (wt's own download sends an Authorization header to S3 alongside the
  signed URL → S3 400 "Only one auth mechanism allowed"; plain curl works) → `unzip -l` proves
  rows at ZIP level.
- **Failed create_manifest.py runs can still have created the manifest**: the script dies in
  verify AFTER `wt manifests create` returns the id — always `wt manifests get <id±few>` for a
  stray duplicate before re-running, and delete your own just-created stray (kept 368187, deleted
  stray 368185).
- **AIRO connector module names that matter**: Scheduler trigger = `clock.scheduled_event`
  (scheduled_event_v2 NOT found), data tables = `workato_db_table` (upsert_record,
  get_records, update_record, add_record), Salesforce SOQL = `salesforce.search_sobjects_soql_v2`
  (query WITHOUT LIMIT + `limit` field; LIMIT appears in the runtime query).
- **Boolean + now() into data-table parameters**: pass `ruby("false", bindings={})` /
  `ruby("now.utc", bindings={})` — plain `false` gets stored as string "false".
- **Upsert-by-primary-key proven**: set table_id (numeric) + primary_field_id (column UUID) →
  sticky parameter paths materialize; run 1 created=true, run 2 created=false, row UUIDs stable.
- **Stale-flag idiom without ruby list algebra**: capture nothing — compare each row's
  last_seen (set to now.utc on every upsert) against the trigger's scheduled_time in a plain
  if/less_than; absent accounts keep yesterday's last_seen and get flagged is_stale=true.
- **Push requires stopped recipe**: "can't modify running recipe" — stop → push → start in the
  same turn; scheduler recipes run fine via `wt recipes force-run` while running (no need to stop
  for tests, only for pushes).

## MCP server token-auth clone — the vua_required chain (BSYS-29822, 2026-10-20)

**JOSH CORRECTION (2026-10-20): the 29 recipe copies were NOT necessary — the
same skills can bind to multiple MCP servers; a second server = new server +
attach the SAME tools. Copies make the fleet impossible to maintain. Never
clone a fleet to serve it from a second server; if a binding flag (vua_required)
seems to force duplication, surface the tradeoff to Josh first.** The notes
below document the vua mechanics (still true) but the copy pipeline was the
wrong call.

- Tool-binding `vua_required` is COMPUTED from the backing recipe's connection
  `personalization` flag ("End user's connection"). Not writable anywhere:
  PATCH tools/<id>.json 200s but ignores it; bulk PUT rejects; assign_tools and
  the TF provider's assign carry no field. Only write surface = recipe-level
  package export → edit (`config[n].personalization: false`) → import.
- Bindings SNAPSHOT the flag at creation — flipping the recipe post-binding
  does nothing until the binding is deleted and re-assigned.
- `wt recipes copy` PRESERVES personalization; copies need the flip per copy.
- Copied skill recipes are not valid `workato_skill` assign targets until
  registered: convert via AIRO (`recipe_builder_pull` to seed the session, then
  `convert_to_skill` WITHOUT recipe_id — direct convert with recipe_id on a
  fresh session misparses the session as a recipe id). Conversion of a
  recipe-copied skill CAN 500/502 transiently; retry once.
- Workato RLM package zips carry paths relative to the manifest's SOURCE
  folder; import expects them relative to the import target. Cross-folder
  imports must patch every internal reference (agentic_skill recipe refs,
  recipe→data-table refs) to full paths from zip root, else "Unresolved
  reference" / duplicate-placement failures.
- Fresh MCP server create-defaults to token-based access. Do NOT set
  auth_type via the TF provider — its post-create auth UPDATE is rejected
  ("Auth type is not included in the list") and rolls back the whole create.
- Token-auth server serves ONLY tools whose binding vua_required=false;
  all-VUA fleet ⇒ "tools not supported" (empty surface). Per-tool vua=true
  tools are simply excluded from token clients (Jira API Token server runs
  18 true + 4 false).
- TF mcp_server `tools` is an ORDERED list — mismatched order = perpetual
  "1 to change" drift, and an apply would recreate bindings and RESET
  hand-PUT tool names (binding name is editable via PUT tools/<id>
  {name, description} but NOT in TF schema — keep order aligned).

## Slack drafts family — TOKEN-TYPE WALL (2026-10-20, BSYS-29820, definitive)

- `drafts.create` accepts the VUA OAuth user token (live-proven); **`drafts.update`
  and `drafts.delete` reject it** — `not_allowed_token_type` with create-identical
  transport (form-encoded + is_from_composer) AND with the JSON-body shape. They
  require Slack web-session tokens (xoxc/xoxd, "browser auth") — same wall the
  native Slack MCP hits (slackapi/slack-skills-plugin#93). `drafts.list` also
  rejects OAuth (`not_allowed_token_type`).
- **Do NOT build update/delete draft skills on the VUA connection model** — they
  are permanently-dead surfaces. The only unlock is a session-token connection
  (Josh's browser tokens in a shared connection: expires, rotates, security-
  sensitive — recommended against). A partial alternative: `chat.postMessage`
  accepts `draft_id` (observed in karbassi's write capture) — a "send/flush
  draft" skill may be possible with OAuth (unverified).
- Wire shapes (for the future): `drafts.update` = JSON body, blocks/destinations/
  file_ids as nested JSON strings, client_msg_id, NO is_from_composer;
  `drafts.delete` = form-encoded, `client_last_updated_ts` padded to exactly 7
  decimals (`frac.ljust(7,'0')`); `drafts.list` = POST, no params needed.
- The `client_last_updated_ts` flows from the create/update response draft object
  (`draft["last_updated_ts"]`) — state carries forward through the agent
  conversation; no list call needed. create_message_draft (v62+) returns it.
- Connector actions for update/delete remain in Slack (Custom) v64 — fail-closed
  (`draft_api_unavailable`), unbound to any MCP tool.
- Also: the "lists need border:1" and "lists rejected in drafts" claims from
  2026-10-14 were BOTH compile-flap artifacts — lists work border-less everywhere
  (posts and drafts). The border normalization was REMOVED in v56 (it would have
  forced visible border boxes on caller lists).

## ⛔ NO HARDCODED IDS IN RECIPE LOGIC (Josh standing directive 2026-10-21, BSYS-29498 FTR)
Never hardcode recipe ids, folder ids, or env-specific ids in recipe code — not in URL strings, Ruby snippets, or properties-carrying-ids. Import remaps STRUCTURAL refs only, never string literals → silent prod breakage behind green jobs. Resolve dynamically: skills by `trigger_application == workato_skill` (recipes API listing carries it; server-side trigger filter does NOT exist), projects/folders by stable NAME (names identical across envs; fail-loud resolver), behavior by emission EVIDENCE (never code-string detection — the include?("recipe-id") detector class is dead). Paginated runtime listings get a fail-loud truncation guard (count PARSED items, never raw-string `"id"` occurrences — each recipe row carries many). API caps: recipes/folders per_page=100 (250 silently returns 100); /api/folders = direct children only (with_subfolders=true on /api/recipes DOES recurse); no DELETE /api/properties route. Promotion gate: scan the export ZIP for `folder_id=\d+` in URLs, bare 7-8-digit ids in Ruby strings, gin-/ginct-/mcps-/skl- handles — all must read CLEAN. Full incident: projects/hr-genie.md 2026-10-21 sections.

## Command loop UPDATE (2026-10-22) — digest re-ingestion loop found + fixed

- **Bug (Oct 8–22):** every fleet digest posted to the command room as the VUA was re-ingested
  by the watcher as a Josh directive. Root cause chain: (1) VUA posts carry Josh's user id, so
  author checks cannot tell fleet posts from Josh; (2) the only exclusion (slack-posts.jsonl
  ledger) never fired — rows use key `channel`, watcher read `channel_id` (silent key mismatch);
  (3) poll_room had no directive-grammar gate. Result: each digest spawned 1–2 duplicate headless
  "Execute this directive" triage passes (cwd=/ transcripts under ~/.claude/projects/-/) and
  double-acked "done: <digest>" from the bridge — the triple-post signature in the room.
- **Fix (2026-10-22):** agent-command-watcher.py — ledger key fix (accept channel/channel_id +
  message_ts/ts, verified against the day's digest ts) + is_directive grammar gate
  (selfcheck/go/skip/plan/work, same contract as room-sweep.py) in poll_room. 9/9 grammar tests.
- **Lesson:** any surface where the fleet posts AS Josh must never use author identity as its
  only signal; pair the ledger exclusion with a command-grammar gate on the consumer side.

## Collaborator groups + project grants (2026-10-23, BTSUP-78586, live-verified)

- **Collaborator groups are ORG-LEVEL objects** shared across the dev/prod workspaces of one org
  (`ug-...` IDs resolve from both). The "prod twin group" concept does NOT exist — create the group
  ONCE; environment scoping happens at the PROJECT GRANT level. Group-name uniqueness is org-wide
  (prod create of a name taken in dev 400s "Name has already been taken").
- Reads: `wt api get /api/user_groups` (paginated 100/page; NO `q` filter — param silently ignored),
  `wt api get /api/user_groups/<id>/project_grants`, `wt api get /api/project_roles` (system roles:
  Project admin / Advanced builder / Builder / Project operator / Operator / Test Operator /
  Project Read Only).
- Grant CREATE has no Developer API route (`/api/user_groups/:id/project_grants` POST 404s; PUT with
  grant payload returns 200 and changes NOTHING — verify by re-GET). The working write surface:
  in-page fetch `POST /web_api/projects/<project_id>/add_project_grants.json` with CSRF
  (XSRF-TOKEN-V2 cookie → X-CSRF-TOKEN) + X-Requested-With, body
  `{"project_grants":[{"assignment_id":"<ug-id>","assignment_type":"UserGroup","project_role_id":"<prjrl-id>"}]}`.
  Found by capturing the UI's own XHR (`orca network`), not by guessing. A guessed
  `remove_project_grants.json` route 404s — no known API route for grant REMOVAL/role-change.
- **Projects created via the Developer API get ACL "Everyone else: No access"** — they vanish from
  the projects list for everyone until access control is set. Expected; grant the group via the
  project's Access control tab (still reachable by direct `recipes?fid=<id>` URL).
- **Environment switch via REAL KEYSTROKES when synthetic dispatch fails**: find-click the env
  switcher, then `orca keypress ArrowDown` × n (verify `document.activeElement.textContent` per
  step) + `Enter`. Full synthetic pointer sequences silently no-op on env menu items even with
  clientX/Y. Browser session must BE in an environment for in-page fetches to hit it — project IDs
  are env-scoped, a dev-session fetch of a prod project 404s.
- Angular hotkeys overlay red herring: hidden `.cfp-hotkeys-container` (visibility:hidden,
  z-index:-1024) makes `document.activeElement.innerText`/body-text reads START with "Keyboard
  Shortcuts:×" — it is NOT intercepting clicks; don't chase it.
- Role dropdowns on the Access-control page: synthetic AND real coordinate clicks on options do not
  register (no XHR fired). Opening the dropdown works via dispatch on `.select__value`, but OPTION
  selection doesn't take. Role edits = manual UI click or wait for a discovered update endpoint.
- Workato session death: "Session ended because you switched workspaces in another tab" — Reload
  button restores the session (click via snapshot ref); env resets to default.

## AIRO recipe_builder: three build-time lessons from the nine-box skill (2026-10-23, builder-D, recipe 83296507)

- **update_variables staleness extends BEYOND loops (BSYS-25527 follow-up, live-proven):** a
  variable updated in a top-level `if`/`elsif` branch (not in any loop) still reads back as the
  STALE initial value in later steps via the `declare_variable_N['value']` pill — first run of the
  nine-box skill computed viewer_role='manager' in a branch and the downstream snippet + return
  step read `''`. This is security-relevant when the variable carries an authz role (sharing gate
  silently never fires). Fix: pass RAW ids into a Ruby snippet and derive the role inside it.
- **Literal `""` on a REQUIRED result_schema field fails recipe START** ("can't be blank" per
  field, start-validation code_errors) — the builder's MissingRequiredField advisory is real at
  start. Workaround: map blank with `ruby("''", bindings={})`; empty static lists (`[]`) on
  required array-of-object fields fail the same way — mark the field optional and omit it on
  error-path return steps.
- **Return-step list-of-objects mapping:** a set_input_field plaintext value of
  `[{...: "f\"{item['x']}\""} for item in list]` stores the inner f-string as LITERAL TEXT
  (renders `f"{...}"` in the payload). The inner value must be authored as the bare f-string form
  (`[{"id": f"{item['x']}"} for item in ...]`) so it parses as an interpolation node.
- **Test-case browser-free creation re-verified end-to-end** (POST scaffold → PUT flat envelope
  with mocks → wt testcases run/status → AIRO job_get trace proof) on 83296507; snippets left
  unmocked run REAL, which makes pure-logic snippets (config parsing, exact-match lookup, grid
  rendering) directly testable under mocked connector steps. CSRF header + X-Requested-With as
  documented 2026-10-11.

## Skill-trigger schemas are ARRAYS of field objects, not JSON-Schema (builder-J, BSYS-29730, 2026-10-24, recipe 83326123)

- **`parameters_schema_json` / `result_schema_json` / `code_output_schema_json` on a `workato_skill` trigger (and Ruby-snippet output schema) must be an ARRAY of field objects** (`[{"control_type":"text","label":"team","name":"team","type":"string","optional":false}, ...]`, arrays as `{"name":"x","type":"array","of":"string"}`). The JSON-Schema object form (`{"type":"object","properties":{...}}`) SILENTLY breaks AIRO's extended-schema retrieval — every `set_input_field` on the step then ends with `API error: TypeError: no implicit conversion of String into Integer`, the parameter pills never materialize, and every downstream pill reference shows `DatapillInvalidPath ... doesn't exist in output schema of 'start_workflow_xxxx'`. Symptom chain: trigger pills missing from `get_datapills` → filter values "invalid" though stored. Fix the schema FORMAT and the pills materialize instantly (runtime pill path: `start_workflow_1['parameters']['<name>']`).
- **Data-table `get_records` filter `equals` (`eq`) is actually case-insensitive CONTAINS, not equality** (live-proven: Team eq "Executive Business" matched "Executive Business Partner"; `starts_with` "Customer" also returned contains-style rows). `starts_with` behaved as prefix. Consequence: any exact-match contract MUST be enforced downstream (verify returned rows with case-insensitive full-value equality in a snippet) — never trust the filter op for exactness.
- **Skill-trigger test cases, browser-free end-to-end re-verified on a `workato_skill` recipe** (POST scaffold → PUT flat `{name, description, mocks, assertions}` → `wt testcases run --ids <caseId>` → AIRO `job_get` trace). Trigger mock: `{"step_identifier": "start_workflow_<uuid4>", "type": "stub_output", "step_output": {"parameters": {...}, "context": {}}}`. Leave the data-table steps UNMOCKED to test against the live table; the snippet runs real and gains the injected `log: ""` key (include it in strict equals). Multiple assertion operators: only `equals` proven; when the expected array content is unknown (e.g. nearest_teams from live row order), first run with a placeholder, read the ACTUAL from the failed job's `job_get` output block, PUT the corrected expectation, rerun — two runs to green.
- Test-case artifact row (BSYS-29730 builder-J): recipe 83326123 `lookup_career_framework`, table 164711 Career Framework, 4 cases (exact / case-insensitive / team-resolved / not-found), all green on run `cirr-Ac8CF9cp-X39sEJ-CD`.

## RLM package export: "empty or invalid reference to a Genie" (2026-10-25)

- `POST /api/packages/export/:manifest_id` fails per-recipe: "Recipe X has an empty
  or invalid reference to a Genie at line N". Cause: `assign_task_to_genie` step's
  `genie_handle` stores a LABEL string ("BT Genie 2.0") with a stale
  `dynamicPickListSelection` (the pre-fork genie) instead of the workspace picklist
  option ID. Forked genies/recipes inherit this.
- Fix: AIRO `recipe_builder_pull` → `recipe_builder_get_picklist(step=<builder step#>,
  field_path="genie_handle")` → `recipe_builder_set_input_field` with the option ID
  (`gin-...`, e.g. `gin-AbzEtfoT-LgXXem-CD` for BT Genie 2.0) → push → read-back grep.
  Builder step numbers differ from raw recipe step numbers (monitor blocks shift them).
- Export validation walks recipes ONE at a time — one fix per failed export cycle;
  re-export after each fix. A manifest wedged `status: "working"` forever is the same
  root cause surfacing in the UI.
- Also: `wt connections update <id> --folder <fid>` SILENTLY IGNORES the folder field
  (200, folder unchanged). Raw `PUT /api/connections/<id>` with `{"folder_id": ...}` works.
- Agentic assets (genie, agentic KB) CANNOT be folder-moved: platform refuses with 422
  "Folder ID is not allowed to be updated" on both AIRO metadata and raw agentic PATCH.

## Genies-as-MCP-tools: workato_genie attach is API-BROKEN for Agent Studio genies (builder-K, BSYS-29730, 2026-10-24)

- Goal: attach two Agent Studio genies (gin- handles) as tools on one new MCP server
  (`mcp_server_create` / `POST /api/mcp/mcp_servers/:handle/assign_tools`, `trigger_application:
  "workato_genie"`). The API docs say `id` is "a string handle when used with workato_genie tools".
- LIVE RESULT (dev, 2026-10-24): EVERY workato_genie attach 400s
  `Tools contains invalid asset(s): workato_genie ID 'gin-...'` — on all three surfaces
  (AIRO create-time tools, REST create-time tools, REST assign_tools), for FOUR different genies
  (fresh active, fresh stopped, established active with chat_interface "api" + active trigger,
  same-project stopped twin) and handle-format variants (bare handle, no-prefix). Unknown app names
  get a DIFFERENT error ("invalid trigger application"), so workato_genie resolves but its asset
  lookup contains no Agent Studio genies in this deployment — docs ahead of backend.
- CONTROL: the identical assign_tools call with `workato_skill` + a same-folder/same-project skill
  handle SUCCEEDS. So the route, auth, and the hidden project rule are fine; it is the
  workato_genie asset class that validates nothing.
- Corollary: the only workato_genie bindings that exist estate-wide are LEGACY (flow_id = numeric
  genie-trigger recipe). No Agent Studio genie has ever been attached via API here.
- Workaround NOT taken (would need lead/Josh sign-off — changes architecture): wrap each genie in a
  recipe (Assign Task to Genie / send_business_event) and expose the recipes as
  workato_recipe_function tools. Clean path: UI attach via the Agent Studio/Enterprise MCP picker,
  or a platform ticket.
- Side lessons: new Agent Studio genies are created `state: stopped`; start via
  `POST /api/agentic/genies/:id/start` (no body needed) — GET /start 404s. AIRO `genie_get` can
  return bare "Genie retrieved successfully" with NO content in this deployment — verify via
  `wt api GET /api/agentic/genies/:gin-id` instead. Full skill listing for handle discovery:
  `GET /api/agentic/skills?per_page=50&page=N` (per_page CAPS at 50 regardless of request;
  2822 skills = 57 pages).


<!-- demoted from INDEX.md 2026-10-25, librarian pass, branch librarian/2026-10-25. Content preserved verbatim; the INDEX line is now a routing hook. -->

## INDEX line history (demoted 2026-10-25)

- - [Workato platform](domains/workato-platform.md) — incl. **BSYS-29503 observability hardening LIVE (2026-10-11): monitor DST-pure-Ruby Pacific offset + 24/7 silence arm (3h biz-hours / 6h off-hours) + volume-scaled burst threshold max(10, 2% events); computer+rollup = 8x3h slice reads (8k/day, was 3k) + capped_read_alert to #gw-semantic-alerts w/ 6h cooldown (156399); computer responder rows delete-split (today-only wipe, yesterday preserved, probe-verified); daily digest 90d/180d retention compaction w/ deleted_count logged; weekly digest partial-week labeling (deltas vs prior FULL weeks only); REPEAT-LOOP PAGINATION BROKEN on runtime (reads 80-130s in-loop vs 40ms top-level, fixture-hung 2x) = static slices instead; AIRO push STALE-SNAPSHOT reconfirmed (verify stored code via REST after every push); output_format=field_name_to_value renames dump keys and zeroes field-ID-scanning snippets**; **BSYS-29504 ops coverage (2026-10-11): TTL delete 200-row/run cap = drain loop (repeat while deleted_count>199, 1051→0 verified), set_input_field quote-wrap trap (use v4 plaintext/datapill modes), start "account_id blank" = unbound connection (recipe_builder_select_connections pre-start), mutation-chain drill pattern (registry row → compile → prepare → 82284937/82285042 → commit, deterministic object_id for undo)**; **owned-asset health monitoring (2026-10-08): asset-fingerprint.py (ledger→registry, hypercare=prod ≤14d) + workato-health.py (hourly launchd sweep, `wt recipes get` per asset, alarms→triage queue/bus/digest)**; **ops-visibility dashboard (2026-10-08): local 127.0.0.1:8771 web UI over failed+swallowed-error jobs (15-min collector, error-signature dedup, /api/triage→queue, nightly 06:07 pre-autopsy fleet job, first records = Extract Design System prod 403/404 — autopsied 2026-10-08: mock-probe noise + missing envelope, fix = BSYS-29418 under epic BSYS-29417; 2026-10-09 re-scope: dev 78677477 already hardened, remaining = test cases + promotion; + 2026-10-09 harness round: workato-health mock-filter+dedupe LIVE (65 probe jobs excluded estate-wide), regression-nightly re-verifies case lists live, proposal file-gate fixed, dreamer heartbeat name aligned, cortex --add-dir probed (residual: ~/.claude guard), drift-fix project 10593549 inventoried (BSYS-29462), clm-001 vua-persistence CONFIRMED by live probe — full round under epic BSYS-29454)**; watchdog agent (nightly 23:13), push risk scorer, build ledger (/builds, /promotion-ready, /promoted — cross-session multi-agent tracking), recipe corpus index; **platform command `prod-bypass` (on 30m|2h / off / status): time-boxed, audited stand-down of all prod-write gates; guardrails v1.0.0**; **DEV+PROD CLI and WT instances (2026-10-07): `workato`/`wt` = dev ws 3535597, `workato-prod`/`wt-prod` = prod ws 3535598, prod token keychain-only**; — AIRO/Workato platform behavior, traps, asset conventions; `wt` (~/.local/bin/wt) Developer-API wrapper for AIRO/CLI gaps (manifests, packages, lifecycle, jobs, lookup rows, connections, properties); **AI gateway token economics probed 2026-10-07 (in file): provider prefix-caching WORKS in-session (83-98% reads), cold start per new session pays full prefix, tool search unforceable, deniedMcpServers cuts cold-start cost, method trap: never judge caching from single-turn headless runs**; **snowflake-backed MCP tool timeout fix (2026-10-09): ~4:00 caller window on recipe-function MCP tools + result-cache false-successes; fix = cursor pagination per month-partition-pruned query (BSYS-29443), connector limit defaults to 100 silently, f-string pills accept plain refs only**; canonical narrative in ~/Documents/Claude/AIRO-MCP-Reference.md; **CHANGE-TRACKING LAYER LIVE 2026-10-10 (spec: specs/env-diff-promotion-tracking.md): changelog.py (per-project ledger changelog, join on project_id not folder_id, no-ledger-entry section) + env-diff.py (dev↔prod name-join diff w/ NORMALIZED hashing — raw hashes differ for every promoted recipe from env-ID churn; validation gate proven; 7 classes; full-estate first run: 5,773 missing / 757 differ / 486 orphaned / 631 conn-missing / 1 conn-reauth / 51 prop-divergence) + promotion-orchestrator patch (batch = ledger UNION env-diff; connections ARE packageable, credentials-only gap — RE-AUTH lines) + estate-architect Monday drift pass**; **function-schema re-registration rule (2026-10-08): AIRO push doesn't re-register a recipe function's schema — editor open+Save does; do it before touching downstream call sites (never build around the stale cache)**; ; **BSYS-29396 (2026-10-08): test-automation output checks are snapshot comparisons (never record literals for volatile steps — assert the RETURN step); tool vua_required tracks the recipe personalization flag ("End user's connection") — its loss fails the resolver count==tools_count guard closed for ALL callers; wt api POST /api/connections recreates the TEST_MCP_OWNER fixture (provider required, folder_id not root)**; **data-tables record API (2026-10-09): dedicated host data-tables.workato.com + `{"document": {...}}` envelope + wt dt --data double-encode trap (in file)**; procedural SOPs are global skills (airo-mcp-playbook, workato-skill-builder, workato-development-playbook, workato-recipe-control, verify-recipe, handoff); **LEGACY-TREE MINING 2026-10-10 (in file, big section): VUA RUCs pin connector revisions + `preserve_in_runtime_connection` + push-wipes-personalization, recipe_builder_save always new id, editor-save flow_id rewrite, genie→skill trigger locked, SDK traps (retry keys invalid/threads rejected/call-in-input_fields/numeric-strings), Ruby sandbox traps (lambda/#{}-interp/top-level return/Time-inspect parsing), first-1000 starvation + sort-key-ignored, duplicate-write + delta-double-count classes, schema-default-vs-fallback drift, MCP isError gap→structured envelope, connection-lost blocks start (no bypass), scheduler min 5 min, class-sweep + per-service checksums, import stop-prerequisites, techniques (empty-string padding tax 10.24×, forced-pagination, while-loop continuation, 3-profile stress method, latency-attribution ≥20% gate, snapshot architecture), red-team false-success pattern, zArchive/RecipeOps/folder-taxonomy conventions, AI gateway ~60s first-byte deadline + large-arg 504s (Kimi ~18K/GLM ~36K), Genie platform facts (endpoint activation independent, send_business_event no authority, no reply-silent, Decision Models no NL, re-register + fresh conversations, wrapper-JD mirroring, Slack no pipe tables)**; **2026-10-10 /triage day: wt --profile is subcommand-level (no global flag), perl-alarm timeouts (no macOS timeout), prod rate-limit backoff ≥75s under swarm load, zArchive-connection DELETE ruling (Josh: unreferenced prod zArchive conns = artifacts, delete + reimport; trigger watch-list refs survive), BTSUP In-Triage two-hop close (41→111→Resolved), HR Genie reauth playbook (tools.json VUA read + runtime-child connection_lost_at + delete=backend reset + 11-step guide 1107512), prod write gate restored (49 rules allow→ask after allowlist drift)**; **2026-10-11 queue-reversion RCA: gardener git checkout -f over dirty tree discarded 49 decisions (patch-apply failure unverified) — recorder hardened (terminal-slug dedupe, per-row fan-out), harness-health parity guard live (family matching, filed→built, duplicate-seed tolerance), recovery from session record; latent: workato-health triage_append whole-file write race (filed)**; **⛔ 2026-10-10 PROD DESTRUCTIVE-ACTION CONTRACT (BSYS-29283 incident, HARD RULE): never probe-write in prod (exploratory POST = mutation); mid-turn chat fragments ≠ per-action confirmation — bold-warning + exact action list + one explicit yes before ANY prod repair batch; connection reference checks scan recipe config account_id blocks workspace-wide (the cleanup's zero-refs check missed 2 identity funcs); post-import sweep for account_id:null + stub rewires + job-history-truth running state — full contract in this file + playbook skill**; **⛔ POST-IMPORT LINKAGE LAW (Josh 2026-10-11): dev connections + dev env-scoped ids (genie chat_trigger_handle ginct-*) never survive a prod import when a documented prod linkage exists — import-remap.py (registry registries/prod-linkages.json, connection account_id scan + genie picklist diff + --canary: fresh-job trace catch-free + zero new handled-error rows) is a MANDATORY promotion stage gate (post-deploy-smoke steps 3/5, manifest-hygiene checks 6/7, orchestrator Phase 4b); born from the 2026-10-10 P2: import overwrote messenger trigger with dev id → 15 h of failed sends behind green jobs**; **BSYS-29498 batch v5 (2026-10-11): PAGE-COMMIT CUTOVER BUILT+PROVEN in dev (Josh: "don't promote something that sucks") — collector 82862205 v40 commits pages via registry-guarded async Commit Collector Page 82936791 (owner-serialized, replay-safe, mode-gated PAGE_COMMIT kill switch; dual-lane parity + gate-off + 0 handled errors proven); LAW: start async-callee BEFORE caller; FULL intelligence platform promotes as ONE wave — 44 assets (23 recipes + 15 tables + topic + Analyst genie/MCP/3 skills), closure-audited, exclusions rule-based (eval harness = prod-genie testing rule); prod folders created (folder-list API misses subtrees — GET by id); package 42198163; spec+dashboards-docs in project file; open Qs self-ruled (coverage-first UNKNOWN-scope=YES, wait timeout=minutes→raised to 5 both lanes, guard test case KEPT—passes on v40, digest conversion panes DROPPED from prod recreation until BSYS-29499 wires recorders)**
- - [Jira autotriage loop](domains/workato-platform.md) — skill `jira-autotriage`: the identify-triage-plan-fix loop with the constitutional decision matrix (BSYS Stories = research+plan, Josh authorizes kickoff; BTSUP = immediate triage + customer-tone replies in Josh's voice; Josh's bugs = investigate + dev-scoped remediation; hotfixes NEVER auto-remediated; everything else read-only); fleet job jira-triage (2h); work products group under knowledge/projects/<epic>
## Scheduler liveness lessons (2026-10-27 jira-triage pass, BSYS-29982)

- Daily-trigger anchor myth BUSTED (dissenter-verified): a Workato daily trigger does NOT "anchor to the next day after a restart" in general; it fires the next FUTURE instance of the scheduled time. A restart at 06:30 still gets a same-day 07:00 tick. BSYS-29982 saw no 10-26 tick because the recipe was STOPPED 06:43, before 07:00. Diagnose "missed tick" from the stop/start timeline against the tick time, never from an anchor rule.
- Scheduler lag is real: same recipe, a run scheduled 06:21:26 executed 06:43:10 (22-min lag). "Next fire registered" means registered, not punctual; judge liveness by job recency (job counts not moving + registered next-fire in the future = healthy registration).
- running:true + zero new jobs + registered future next-fire = healthy idle scheduler; do NOT force-run on that shape alone.


## Patricia review fix pass (BSYS-29592, 2026-10-27)

- **Raw PUT DOES persist `code` on a STOPPED recipe** — contradicts the wt-cookbook
  "code silently ignored on PUT" note (that canary likely hit a running/blocked recipe).
  4/4 surgical PUTs (schema declarations, step-node replacement, config rebind) persisted
  and read back clean. Recipe MUST be stopped ("can't modify running recipe" otherwise;
  AIRO push also refuses while running). Still: GET-verify EVERY PUT, never trust the 200.
- **Project-property pill wire form:** `"#{_dp('{\"pill_type\":\"project_property\",\"property_name\":\"alerts.dm_user_id\"}')}"`.
  Store with REAL quote chars in the DSL (json.dumps escapes once); literal backslashes fail
  start validation "invalid data pill: Invalid JSON". Property created via Dev CLI
  `workato properties upsert --project-id N --property "K=V"` (wt `properties upsert --file`
  returned success:true and persisted NOTHING — silent no-op, verify with `wt properties list`).
- **`create_records_batch` (data tables) ERRORS on an empty rows array** where a foreach no-ops.
  Any foreach→batch conversion needs an emptiness guard (if `candidates_found > 0`).
- **Foreach-pill triangles (editor) = undeclared item schemas.** Fix is schema-only: give the
  source ruby's array property real `properties` (replace bare `"of":"object"`) AND populate the
  foreach `extended_output_schema`; for parsed arrays, update `sample_document` too — all three
  or the pill stays unresolved. Runtime never needed this; editor-only. Raw-PUT safe.
- Slack identity rebind pattern: swap the recipe `config` entry (provider/name `slack`→`slack_bot`,
  account_id) + replace the step node with the `post_bot_message` shape (channel/text only) in one
  PUT; Slack's job-trace response carries `bot_id`/`app_id` — the authoritative proof of bot identity.

## Connection re-auth for workato_api_connector (BSYS-29498, 2026-11-02)

- The `workato_api_connector` connection's credential field is `input.api_token`;
  PUT /api/connections/:id stores it and runs a live credential test. **But test AND
  runtime both 401 with tokens that curl 200 on the same endpoints** — the UI connect
  flow stores federated-identity state beyond the token that no API path reproduces.
  Re-auth of this connector class is UI-ONLY. (3-strike proven on BSYS-29498; dev
  probes + prod swap both 401, job j-AcCgPWtD-kogcws-CD.)
- Developer API clients (`/api/developer_api_clients`, org-level, env-bound at issue
  time) carry a `token.value` view-once at create/regenerate; POST needs
  name + api_privilege_group_id + environment_id + environment_name + all_folders.
  Regenerate: POST /api/developer_api_clients/:id/regenerate. **Regeneration
  invalidates the old token INSTANTLY — check which connection holds it first**
  (BSYS-29498 incident: regen of the "unused-looking" client 446372 killed the live
  credential of prod connection 22284446; timing-created-at ↔ authorized-at matched
  to the minute and was taken as proof of "unused" — it was the binding).
- API-platform clients (`/api/api_clients`, is_legacy=true in v2 list) have NO
  headless token-generation route (create returns no token, /api_keys 404) — tokens
  for that class are UI-view-once only.
- BSYS-29283 precedent (2026-10-10) "Identity IAM API refuses all prod-scoped client
  tokens" is STALE as of 2026-11-02: prod-issued client tokens authenticate (the
  prod token lists prod genies on /api/agentic/genies).
- Timing-correlation is NOT ownership proof: two clients matched two connections by
  created-at/authorized-at minute-pairs, and only ONE was the live binding.

## Zoom S2S self-serve via Okta + marketplace (2026-11-02 — access-track pattern that works)

Josh grants Okta-based self-service for access items instead of filing tickets when the grantor
console is reachable with his Okta session (his ruling: the agent drives the UI end-to-end, learns
the traps, documents them — never hands UI work back). Proven on the Zoom S2S app:

- **App:** "Workato BTG 2.0 Integrations" (S2S OAuth, app id `9cfT95UeQsuHux6rBNEpyQ`, client
  `plG4JZbbT5CfWnUheWq2Mg`, account `C1v0GhzBSc2kzVlMiz4fQw`) — 6 least-privilege scopes (recording
  list/view/by-meeting reads + file/meeting deletes + user:read:user:admin for owner-binding),
  activated, token verified, live reads proven (user lookup + 10 real meetings). Secret in macOS
  keychain `zoom-s2s-btg20` (never in files/chat).
- **Login path:** `gb.py okta` → Zoom tile (`/home/zoomus/0oa2mxhjhqsnuAwo1697/1835`) → SSO to
  app.zoom.us; marketplace shares the session. Reauth = the orca-browser skill's Okta section
  (one password attempt max, push preferred, josh-alert.sh on challenge).
- **Marketplace automation traps** (viewport-per-goto mobile flip, invisible `.page-loading-pop`
  click-eater, off-screen clicks, clipboard monkey-patch for Copy buttons, eye-toggle pairs,
  a11y-tree > JS-eval value reads, S2S creds dead until Activation): full catalog in the
  orca-browser skill's "Working with Zoom" section — read it BEFORE any marketplace flow.
- **Workato-connection landing:** Wave-1 Zoom actions authenticate per-call via the S2S token
  endpoint (Basic client_id:secret); the token TTL is 1h — build a token-refresh pattern (fetch on
  demand per job, not stored) when wiring the Zoom fetch/delete actions. Client secret stays in the
  connection/property layer, never in recipe code.
- **Same pattern queued:** Google Workspace domain-wide delegation — grant scopes to the EXISTING
  `integrations.ai@workato.com` service identity (Josh's dedicated path; no new SAs), Groups
  membership write first, Drive permissions later. Gong admin via Okta admin access; Coupa key
  from an existing AHQ | AI connection or Amazon Secrets via CLI; Snowflake READ via an existing
  BT connection (Josh guidance 2026-11-01).
- **Multi-workspace Slack estate (learned same round):** the VUA slack-workato MCP is bound to
  workato.slack.com; the BT AI pilot channel (ask-bt-2-pilot, C0CC16E91GR) lives in
  bt-ai-workspace.slack.com — MCP posts there = channel_not_found. UAT posts go through the
  browser (app.slack.com via Okta). Identify a channel's true workspace from the permalink domain
  in router job traces.

## Deploy-completion watcher + post-deploy smoke runner LIVE (BSYS-30022, 2026-11-02)

Closes the Holiday Sync day-zero gap (deployed 10-20, watchdog caught 10-24): the FTR team
imports at an unobserved time, so nothing watched the first prod job. Built per Josh's
3-point plan (ticket comment 2026-10-27).

- `~/.claude/knowledge/scripts/deploy-watch.py` — one script, four subcommands:
  `watch` (hourly, launchd `com.josh.deploy-watch`, StartInterval 3600 = same cadence as
  the workato-health sweep), `smoke` (explicit run for one batch), `backstop` (deployed
  >24h with zero succeeded jobs, cadence-aware), `report` (latest readable report).
- **Trigger signal (validated at build step 0, live):** BSYS Deployment Request tickets
  transition to status **Deployed (id 10199)** — proven on BSYS-29780's changelog
  (FTR → Waiting to deploy → Deployed, twice). Fallback: `wt recipes versions <id>
  --profile josh-prod` version poll for tracked recipes (validated on 82120574).
- **Automated vs gated split:** placement/connections/schedule/first-green-job/VUA
  surface/masking-flag run read-only. Canary induce, linkage-remap fix, state restore are
  NEVER executed by the runner; the report lists the exact command and waits for Josh's go.
- Evidence: `workato-health/deploy-smoke/ledger.jsonl` (one row per check) + readable
  reports in `deploy-smoke/reports/`. Verdicts (pass/pending/fail) post to the gossip bus
  and the governing ticket either way.
- **Day-zero adoption guard (bug paid for in build):** the first sweep must adopt EXISTING
  Deployed transitions as `pre-launch` WITHOUT firing, and the fire filter must skip both
  `done` AND `pre-launch` keys. First version skipped only `done` → the second sweep fired
  17 empty smokes and spammed 17 bus findings. Cleaning: bus rows, ledger rows, and empty
  reports all removed; dedup re-proven at 0 fires on the third sweep.
- wt gotcha confirmed again: `--raw` output can carry a PRODUCTION warning banner line
  BEFORE the JSON — parse from the first `{` or `[`, never json.loads the whole stdout.
- Doctrine wired: deployment-request SKILL.md carries the deploy-completion-signal row
  (the FTR handoff tells the watcher how it learns the deploy landed); promotion-readiness
  row 8 carries the smoke-scheduled sub-check; post-deploy-smoke SKILL.md documents the runner.
- Unverified by design: the prod-facing trigger only truly fires on the first real
  deployment after this lands; the full TEST-project broken-promotion negative test is
  scoped, not staged (the pending-verdict path is verified instead).

## Platform claims require platform evidence (STANDING ORDER, Josh 2026-11-02)

Full text: ~/.claude/CLAUDE.md (authoritative). Essence: a claim that an asset
exists in / runs on Workato carries, in the same breath, the asset id + full
clickable URL + a FRESH job id (job_list trace, never last_run_at/counters) or a
read-back (GET-back/table read/tools list). Local scripts/launchd/cron doing work
is NOT platform deployment — it is a DEBT row until a platform asset replaces it
with job evidence. Born: the devapi build described local launchd twins as
platform recipes. Any violation is a P1 triage finding.

### Data-table write wire shape — `parameters` object (2026-11-02)
`workato_db_table` add_record/upsert_record carry column values ONLY at
`input.parameters = {"<field_uuid>": <value>}` (underscored uuids). Column keys
at the input top level are silently dropped at save — no error anywhere. AIRO's
`set_input_field` with `parameters.<uuid>` paths is the reliable way to write
them; a first bare-uuid attempt refreshes the step schema and gets rejected, then
the prefixed retry lands; remove top-level twins after. `ruby(...)` values inside
`parameters` fail to compile ("INVALID RUBY FORMULA") — use datapill or plaintext.

## Recipe runtime evaluation surfaces (job-proven 2026-11-05, T2 receiver work)

- `=-form` (`= <ruby>`) evaluates at RUNTIME in: **conditions** (if/compound lhs), **rest-step request.url**, **rest-step request body** (needs the leading `= ` or it's a literal), **data-table step `parameters` values**. It is silently STRIPPED from rest-step request **headers** at save (no error — read back to verify).
- Start validation rejects `JSON.parse` inside data-table field =-forms ("can't be blank"-class errors) but ALLOWS it in conditions... until the condition sandbox: `rindex` = "expression is unsafe". Whitelisted condition methods seen working: `include?`, `split`, `size`, `==`, `to_s`, `to_i`, `strip`.
- `#{}` templates: PURE pill references evaluate (any provider); expressions with method chains save fine but go over LITERAL at runtime — junk-row factory.
- Webhook trigger (form mode) output: `{"payload": {"payload": "<raw JSON string>"}, "params": {}}` — the inner payload is a STRING, never parsed. Real Slack block_actions payloads contain BOTH buttons' values (message blocks echo) AND mailto pipes (`<mailto:x|y>`) — string parsing must anchor on the full prefix (`split('approve|')[1]`) and isolate branches by occurrence COUNT (`split('approve|').size > split('deny|').size`), never by `include?`.
- The generic `rest` connector does NOT apply its connection's auth to `make_request_v2` requests (fails masked as Jira 404 "Issue does not exist or you do not have permission" = the unauth mask). For Jira, the `jira_service_desk` adapter's `__adhoc_http_action` step (verb/path/request_type raw/input.data =-form) with a working connection = the proven authenticated path; its step identity (uuid) matters — hand-converted rest steps throw "Internal error" unless deep-copied verbatim from a working step.
- A step whose `parameters` get silently dropped at every save (the save keeps the OLD value; no error): fix = deep-copy the ENTIRE known-working sibling step (schema cache fields included: `dynamicPickListSelection`, uuid slot) and change only the differing values.
- Recipe wire PUTs: after ANY structural change, renumber ALL steps depth-first (1..N, trigger = 0) — stale/duplicate `number` = "is out of sequence" reject; `number: null` = "not an integer" reject.
- REST-connector connections: creating via API with guessed input field names SAVES with auth silently EMPTY (the edit page shows Basic + blank user/password). Connection edit pages are read-only while connected AND while any active recipe uses the connection — stop the consumers first, then disconnect, edit, reconnect.
- Slack api.slack.com app-settings: toggles = hidden-checkbox UIs that swallow ref-clicks — real coordinate clicks (move/down/up) work; "Save Changes" enables ONLY after a real keystroke lands in a filled field (native-setter fills don't mark it dirty); verify by RELOADING (a disabled Save = ambiguous).
