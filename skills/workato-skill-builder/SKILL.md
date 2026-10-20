---
name: workato-skill-builder
description: >-
  Standard operating procedure for building, wiring, and testing a Workato Genie
  skill or recipe through the AIRO MCP server (the Workato platform MCP with
  recipe_builder_*, genie_*, mcp_server_*, data_table_*, blueprint_* tools). Use
  this whenever the task involves creating or editing a Workato recipe or Genie
  skill, converting a recipe to a skill, wiring a skill to a Genie or MCP server,
  running Workato test cases, or preparing a Workato asset for promotion — even
  if the user just says "build a Workato skill", "add a step to the recipe",
  "make a Genie that does X", "spin up an MCP tool for Y", or names a Workato
  asset by ID. It runs the full build→verify→UAT lifecycle in dev and stops at a
  promotion-ready handoff; it deliberately does NOT deploy to production. Do not
  use for consuming already-built Workato MCP tools (just call them), or for
  non-Workato automation platforms.
---

# Workato Skill Builder (via AIRO MCP)

This skill encodes the repeatable path for shipping a Workato Genie skill or
recipe through the **AIRO MCP server** — the Workato platform MCP whose tools are
prefixed `recipe_builder_*`, `genie_*`, `mcp_server_*`, `data_table_*`,
`knowledge_base_*`, `blueprint_*`, `collaborator_*`. Its own server instructions
tell you to lead with `docs_get(id="guides:overview")` when a workflow isn't
obvious — follow that.

The point of this skill is not to teach the tools (they're self-describing). It's
to carry the **operational choreography and the traps** that aren't in any tool
schema and that cost real rework when forgotten. Read the whole file once, then
work the lifecycle.

## Workato Developer CLI is the default operational surface

For Workato Development work, prefer the authenticated **Workato Developer
CLI** for every operation it supports: inspect workspace/project state, list
recipes, connections, data tables, and properties, pull/push files, validate
definitions, and start/stop recipes. It is faster, lower-token, scriptable,
and portable to Claude Code or another local agent.

Use AIRO MCP where it provides the required semantic build/test capability.
Use the signed-in browser only for a genuine UI-only operation that neither the
CLI nor AIRO can perform (for example, selecting an End User's connection,
inspecting a visual job trace, or editing a UI-only table schema). Do not ask a
user to do a routine action merely because the browser is available.

In this Workday workspace, start with `tools/workato-dev.py` when its command
covers the work. It provides safe read-only discovery and explicit `--execute`
protection for recipe lifecycle operations. The script has no Codex-specific
dependency, so Claude Code can use it unchanged.

For the fuller catalog of general AIRO/Workato platform bugs and efficiency
practices that apply to ANY AIRO MCP call — not just a full build — see the
companion **`airo-mcp-playbook`** skill. It covers things this file only
summarizes (datapill sample values, VUA connection verification) plus others outside
this lifecycle entirely (data table schema-update wipes, Ruby DSL quirks,
session_id collisions). It's connector-agnostic — Workday/Drive/Zoom-specific
behavior isn't in scope there. Load both when the task is a full build.

## The boundary: dev + UAT only, never prod

This skill runs everything through the **dev build and UAT verification** stages
and then **stops at a promotion-ready handoff**. It does not promote to
production.

Why this boundary is deliberate, not a limitation:

- **AIRO doesn't own prod promotion.** The AIRO MCP exposes build and admin
  surfaces, not an environment-promotion primitive. Promotion across
  dev→test→prod is a separate, governed path (Workato Environments / manifest
  export-import, or CI/CD via the platform API). Reaching around that path from a
  build tool bypasses the control it exists to provide.
- **Prod promotion is hard-to-reverse and outward-facing.** It's exactly the
  class of action that stays human-gated. Surface the handoff, let a human (or
  the governed process) pull the trigger.

When the build and UAT are done, produce the **Promotion Handoff** (see the last
section) and stop. Promotions go through the **BT managed promotion process via
Jira** (deployment request born from the Story/Bug — see the Promotion Handoff
section). If the user explicitly asks you to promote to prod anyway, don't
silently comply — restate that promotion is governed, and ask them to confirm
they want you to attempt it outside the normal path. Direct prod edits only on
an explicit "hotfix to prod" instruction from Josh.

## TWO AIRO MCP servers: dev (default) vs PRODUCTION (danger)

There are two identically-tooled AIRO MCP servers in user config:

- **`workato-airo-mcp-server`** — DEVELOPMENT workspace. The default for
  everything in this skill. Any uncategorized build/edit/test/investigate ask
  uses this server, same as always.
- **`workato-airo-mcp-prod`** — **LIVE PRODUCTION workspace**, for production
  review and hotfixes only. Never use it unless Josh explicitly names
  production ("prod hotfix", "production review", "use the prod AIRO MCP").
  Ambiguity about which workspace was meant always resolves to **dev**.

Rules for the prod server:

1. **Prod reads run without prompting; prod writes always prompt.**
   `~/.claude/settings.json` allowlists the ~50 read-only prod tools
   (recipe_get/list, recipe_builder_pull/show, job_get/list, data_table_
   get/list/query, genie_get/list, knowledge_base reads, blueprint_pull/
   read, docs_get, lookups, etc.) and gates all ~41 write/mutation tools
   behind `permissions.ask`. Never add a prod write tool to
   `permissions.allow`, never route prod calls through a bypass, and never
   let a subagent or workflow call prod write tools unattended. Any prod
   tool added by Workato later is unlisted and prompts by default.
2. **Before ANY prod write action** (creating, saving, pushing, updating, or
   deleting ANY asset — recipe, skill, Genie, data table, blueprint, MCP
   server), stop and state in bold:

   > **⚠️ LIVE PRODUCTION EDIT — this action modifies the LIVE PRODUCTION
   > Workato workspace (`workato-airo-mcp-prod`). This is NOT dev. Real users
   > and real jobs are affected. Josh, confirm you want this production
   > hotfix: [exact action + asset + URL].**

3. Do not execute until Josh explicitly confirms, and re-verify the asset URL
   resolves in the prod workspace before running the tool.

## Step 0: open the living manifest (house style, Josh 2026-10-10)

Before the first step of ANY build, create the living export manifest for the
story and note its ID in the ticket (full doctrine: workato-development-
playbook SKILL.md, "The living manifest"). Every time a step of this SOP
creates or updates an asset (recipe, function, table, genie, MCP server), add
it to the mirror file `<repo>/manifests/<BSYS-id>.manifest.json` and push the
whole list with `wt manifests update`. The promotion handoff at the end of
this SOP MUST include the manifest ID and mirror path; a handoff without a
current manifest is incomplete.

## Lifecycle

Work these in order. Skip a step only when the user's task clearly doesn't touch
it (e.g. editing an existing recipe skips scaffolding).

### 1. Orient & scaffold

- If the workflow isn't obvious, call `docs_get(id="guides:overview")` first.
- Confirm **where** the asset lives before creating it: project and folder. Use
  `project_list` / `folder_list` to verify the target rather than assuming. Never
  create assets loose in the wrong project — moving them later is friction.
- Editing an existing recipe you only know by name? Resolve it (recipe ID +
  workspace ID + fail rate + running state) with the Dependency Tracker's
  `search_recipe_dependencies` instead of paging through `recipe_list` — see
  `workato-development-playbook` → Routing. Also use it for blast radius
  (which recipes touch a connection/object/field) before changing shared assets.
- Agree on a **naming convention** with the user up front (verb-first,
  environment-neutral). The name travels to prod, so don't bake "dev" or a
  ticket number into it.
- For a new skill recipe, start with `recipe_builder_init_skill`. For a plain
  recipe, `recipe_builder_init`.

### 2. Build

- Add and configure steps: `recipe_builder_add_step`, then
  `recipe_builder_set_input_field`, `recipe_builder_set_condition`,
  `recipe_builder_set_foreach_source`, and
  `recipe_builder_set_error_handling_config` as the logic requires.
- Discover connectors/operations with `recipe_builder_search_connectors` /
  `recipe_builder_list_connector_operations`; get real datapills with
  `recipe_builder_get_datapills` rather than hand-typing pill references.
- **Always Validate.** Prefer looking up the source of truth at runtime (with
  error handling) over persisting a denormalized copy of it. A skill that reads
  the authoritative record each run doesn't drift; one that caches a copy does.
  This is a design bias to carry into every step, not a one-time check.
- Save with `recipe_builder_save` as you go.

### 3. Verify (before converting)

- Pull the recipe with `recipe_builder_pull` to review it — **but do not trust
  the export for field mappings.** `recipe_builder_pull` can render a datapill as
  its *sample value* (e.g. a mapped `employee.name` pill shows as the literal
  "Logan McNeil"), so a correctly-mapped field looks hardcoded in the export.
  **Verify mappings against the recipe UI**, not the pulled JSON. When in doubt,
  `recipe_builder_show` and cross-check in the builder.
- Run the recipe's test cases: `test_case_list` to find them,
  `test_run_request_get` to check results. Green tests before you convert.
- **Failure-classification check:** every error branch in the built recipe
  is classified transient/permanent/capacity and handled per class — details
  in `workato-development-playbook`. An unclassified catch-all is a build
  defect, not a style preference.
- **Two-signal check:** the user-facing notification path and the
  operator/monitoring signal are separate (one is what the user sees, the
  other is what an operator sees), and the run ends in exactly one
  authoritative outcome. Both are house rules from the otto platform
  codebase study.

### 4. Convert & wire

- Convert the recipe to a skill with `recipe_builder_convert_to_skill`.
- Assign it to the target Genie (`genie_get` / `genie_update`, or
  `knowledge_base_assign_to_genie` for KB-backed skills). Verify the Genie exists
  first with `genie_list` / `genie_get`.
- If the skill needs to be exposed as an MCP tool, attach/create the MCP server
  with `mcp_server_create` / `mcp_server_get`.
- **Blueprints, if used, are order-sensitive:** create placeholders first
  (`blueprint_create`), build the real assets, *then* bind each one with
  `blueprint_link_asset`. Linking before the asset exists fails or orphans the
  binding.

### 5. VUA connection persistence and verification

If this is a **VUA / end-user-connection skill** (it runs on the *end user's*
connection, not a service/ISU account), the selected connection mode is expected
to persist through recipe edits and AIRO pushes. The former platform bug that
reset VUA recipes to the service/ISU identity was confirmed resolved on
2026-08-05.

The sequence around a VUA skill push is:

1. **Stop** the recipe.
2. **Push** (`recipe_builder_push` / copilot push).
3. For identity-sensitive changes, **verify** that "End user's connection"
   remains selected when an authoritative UI or API surface exposes the mode.
4. Re-select only if verification shows drift, then **start** the recipe.

Do not add a mandatory manual re-selection gate after every push. Treat any
observed reversion as a regression: record the asset, environment, push path,
and before/after connection mode. New environment imports and first-time setup
still require the intended connection mode to be configured normally.

### 6. UAT

- Hand the user **full, clickable Workato URLs** to test — not bare asset IDs.
  Use `asset_url_get` to resolve them. "Run recipe 71440076" is friction; a link
  they click is not.
- If a UAT tracking sheet exists for this work, append the new skill's test
  results to it; if the user works from one, keep using it.
- Let the user drive UAT in dev. Don't declare success on their behalf — report
  what passed, what you tested, and what remains.

### 7. Promotion handoff — then STOP

When UAT passes, produce a **Promotion Handoff** so a human or the governed
Environments process can promote. Do not promote yourself. The handoff is a
short, copy-pasteable block:

```
## Promotion Handoff — <skill/recipe name>
Status: UAT passed in dev, PENDING prod promotion

Assets to promote:
- Recipe(s): <name> (id <id>) — <full URL>
- Skill: <name> (id <id>)
- Genie: <name> (id <id>)  [if wired]
- MCP server: <name> (id <id>)  [if wired]
- Data tables: <name> (id <id>)  [if any]
- Knowledge base(s): <name> (id <id>)  [if any]

Connections required in prod:
- <connector> — <VUA / end-user  OR  service/ISU account>

Dependencies / order:
- <blueprint links, upstream recipes, lookup tables>

Post-promotion checklist:
- [ ] Verify intended VUA/end-user connection mode after prod import or identity-sensitive push
- [ ] Re-run UAT cases in prod
- [ ] Confirm asset URLs resolve in prod

Promotion path: BT managed promotion process via Jira (see below) — human-gated
```

**BT managed promotion process (the only normal path to prod).** All
promotions go through the BT managed promotion process via Jira. A
deployment request starts its life as a **Story or Bug** that already
contains the information for the thing being conveyed (what changed, why,
verification evidence) — draft the deployment request from that item and
get Josh's approval on the artifact before filing. Direct prod edits happen
ONLY when Josh explicitly says "hotfix to prod" (or similar explicit
wording), and the Jira ticket still gets the hotfix record afterward.

## Cross-cutting conventions

- **Full URLs, always.** Any time you ask the user to open, test, or run
  something, include the resolved Workato URL (`asset_url_get`), not just the ID.
- **Verify before mutating.** Before editing or linking an existing asset, read
  it first (`recipe_get`, `genie_get`, `data_table_get`, etc.). The AIRO server
  instructions require this, and it prevents editing the wrong asset.
- **Preserve IDs, handles, and placeholders** exactly as tools return them; pass
  explicit asset IDs into read/update/link calls.
- **Jira/markdown note:** if this work involves writing a Jira ticket via the
  Atlassian MCP in "markdown" mode, a leading `#` renders as an H1 heading, not a
  list bullet. Use `1.`, `-`, and `**bold**` for lists and emphasis — never a
  leading `#` for list items.

## Quick reference: the traps, in one place

| Trap | Symptom | Guardrail |
|---|---|---|
| VUA connection persistence regression | Skill runs as service account | Expect persistence; verify identity-sensitive pushes and re-select only if drift is observed |
| Datapill sample values | Mapped field looks hardcoded in pull | Verify mappings in the **UI**, not the export |
| Blueprint link order | Link fails / orphaned binding | Placeholders → build assets → `blueprint_link_asset` |
| Bare asset IDs | User can't find what to test | Resolve full URL with `asset_url_get` |
| Denormalized copies | Skill data drifts over time | Always Validate — look up source of truth at runtime |
| Prod promotion | Bypassed governance | Emit handoff, **stop**; promotion is human-gated |
| Wrong AIRO server (prod vs dev) | Live production edited by mistake | Default `workato-airo-mcp-server` (dev); `workato-airo-mcp-prod` only on explicit prod ask + bold **LIVE PRODUCTION EDIT** confirmation per write |
| Jira leading `#` | Renders as H1, not a bullet | Use `1.`/`-`/`**` in markdown mode |

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Adding specialist Genies and MCPs to Multi-Genie Orchestration](../../kb-corpus/confluence/extbt/2872377507-adding-specialist-genies-and-mcps-to-multi-genie-orchestration.md)
- [AIRO - AIRO MCP server](../../kb-corpus/docs/en/airo/mcp.md)
- [Product Scoop &#8211; July 2026](../../kb-corpus/changelog/product-scoop-july-2026.md)
- [Workato Skill connector - FAQs](../../kb-corpus/docs/en/agentic/agent-studio/connectors/workato-skill-connector/workato-skill-connector-faqs.md)
<!-- kb-bridges:end -->
