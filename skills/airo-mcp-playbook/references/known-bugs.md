# Known bugs — recipe-builder mechanics, legacy migration, packaging

Load this file when doing recipe-builder session work, migrating a legacy
`workato_genie` skill, wiring blueprints, or importing/inspecting a Workato
package. For the six highest-severity data-loss/wrong-identity bugs, see
SKILL.md directly — they aren't repeated here.

## Resolved bugs / regression watch

- **VUA connection reset after recipe edits/pushes — intermittent regression
  watch.** A reset to the pushing service/ISU connection was confirmed fixed
  on 2026-08-05, but later personalized-recipe pushes showed intermittent
  loss of "End user's connection." Expect persistence, then verify the saved
  mode after identity-sensitive pushes when an authoritative surface exposes
  it. Repair only observed drift and retest caller scoping; do not blindly
  re-select after every push. Capture asset ID, environment, push path, and
  before/after state. New imports and first-time setup still need their
  intended connection configured.

## Recipe-builder session & editing mechanics

- **Session goes stale after push.** `recipe_builder_*` edits fail after a
  `recipe_builder_push` until you re-pull the recipe into the session
  (`recipe_builder_pull`).
- **Can't push a running recipe.** Stop it first in the Workato UI — no
  stop/start tool exists in AIRO MCP.
- **`recipe_builder_update_step` cannot reliably swap a trigger's
  connector/action.** The DSL preview updates but `get_input_schema` stays
  on the old action's schema (a real bug, not display lag) — input fields
  get flagged `InputFieldNotInSchema`. Fix: delete and rebuild via
  `recipe_builder_init` + a fresh `add_step(type="trigger", ...)`. Note
  `recipe_builder_remove_step` refuses `position < 2` — step 1 can't be
  removed either, only replaced by starting over.
- **`while_condition` can't be removed independently** — delete or empty the
  parent `repeat` instead.
- **`declare_variable` schema staging order matters.** Set `variables.schema`
  ALONE first, THEN `variables.data.*` in a separate call — setting both at
  once can fail to register the output datapill schema, producing a
  downstream `DatapillInvalidPath`. Also, `declare_variable`'s input shape
  itself varies by session state (sometimes simple scalar `name`/`type`/
  `value`, sometimes multi-field `variables.schema`/`variables.data.*`) —
  always call `recipe_builder_get_input_schema` fresh per step rather than
  assuming the shape from a previously-pulled recipe's DSL.
- **Inserting a step renumbers every step after it.** Re-verify step numbers
  with `recipe_builder_show` before editing a later step's fields.
- **`job_get` collapses loop iterations** (shows only one). To inspect
  per-iteration results across a loop, use `job_list` instead — job titles
  often carry an identifying value (e.g. recipient email) per iteration.

## Blueprints

**Order-sensitive.** Create placeholders (`blueprint_create`) first, build
the real assets, then bind each one with `blueprint_link_asset`. Linking
before the asset exists fails or orphans the binding.

## `session_id` collisions between `recipe_builder_*` and `genie_*`

Reusing one `session_id` across an active `recipe_builder_*` session AND a
subsequent `genie_update` call polluted the `genie_update` request URL with
the recipe's full JSON payload → `414 Request-URI Too Large`. Use a
dedicated `session_id` for `genie_get`/`genie_update`, never one an active
recipe-builder session is using.

Also: `genie_update` on a brand-new `session_id` that never called
`genie_get` first fails with `"Genie with ID '<workspace_id>:<session_id>'
not found"` — seed the session with a `genie_get` call once before
`genie_update` on that same `session_id`, the same pattern recipe sessions
need (`recipe_builder_pull`/`init` before edits).

## Legacy `workato_genie` → `workato_skill` migration

Skills built before the platform migrated to `workato_skill` still use
`workato_genie.start_workflow`/`workflow_return_result`. They run fine as
Genie skills, but the MCP-server attachment UI flags them **"Incompatible"**
— tooltip reason: *"Uses Call ID, Conversation ID or Genie ID datapill"*
(`start_workflow_1['context']['call_id']`/`['conversation_id']`/
`['genie_id']`). Those context fields only exist inside a live Genie
conversation; a generic MCP client invocation has none, so the platform
blocks attaching a skill that depends on them.

Migration steps:
- `recipe_builder_add_step` refuses new `workato_genie.*` steps outright
  ("deprecated and cannot be used") — new steps must use `workato_skill`.
- Use `recipe_builder_update_step` to change the trigger (step 1) and every
  `workflow_return_result` action to `workato_skill`. This **wipes** the
  trigger's `parameters_schema_json`/`result_schema_json`/`description`/
  `requires_user_confirmation` fields and every changed action step's
  `result` field. Re-set all of them immediately via
  `recipe_builder_set_input_field`, using `recipe_builder_show()`/
  `get_datapills` beforehand to capture the exact prior values.
- Strip any `call_id`/`conversation_id`/`genie_id` datapill usage elsewhere
  in the recipe (e.g. a file-naming expression) — replace with something
  MCP-safe and still unique, like `job_context['job_id']`.
- The recipe must be **stopped** before `recipe_builder_push` accepts the
  edit — pushing a running recipe errors "Cannot edit recipe... because it
  is running." No stop/start tool exists in AIRO MCP; manual UI step.
- After a successful migration + push, the MCP server's tool listing can
  still show stale info (old description, "Incompatible" badge) even though
  an independent `recipe_get` confirms the backend updated — a display
  cache issue, not a failed push. There's no confirmed auto-refresh path;
  re-syncing the MCP server row or manually updating its description may be
  needed.
- Ruby `ruby()` formulas are a restricted subset (see
  `references/ruby-dsl.md`) — relevant here because nil-safe guards on
  optional nested fields need the `present`/`blank` pattern, not `.dig`/`||`.

## Packaging / multi-copy gotchas

- **Exported Workato MCP packages can be missing recipe assets
  entirely.** An import error that looks like a "dependency ordering"
  problem can actually mean the zip contains only `.agentic_skill.json`
  pointer files + connection + `project.json` metadata, with zero
  `.recipe.json` files anywhere — even though each skill JSON's
  `references.recipe_id.id.zip_name` points to one. Confirm by direct
  filesystem search for `*.recipe.json` in the extracted package before
  assuming an import-order or manifest-structure fix will work — it won't;
  the real recipe logic only exists in the customer's live workspace and
  requires a re-export with "include recipe/dependencies" checked.
- **Duplicate copies of the same skill set can exist across different
  projects** — a dev copy and a different team's production deployment can
  share near-identical recipe names/logic with no distinguishing suffix,
  living in different project IDs. Always confirm which project/recipe ID
  an MCP server config actually points to before trusting test results
  against it — a local MCP client config can silently point at the wrong
  copy with no obvious symptom until behavior looks "already fixed" or
  "still broken" in a confusing way.

## Project properties

- **No create/set tool exists.** `property_list` is read-only — properties
  must be created/edited manually in the Workato UI (Project settings →
  Properties).
- Reference them in a recipe as a plain expression:
  `project_property['Property Name']` (no `ruby()` wrapper needed for
  simple substitution). This is the pattern for making environment-specific
  IDs (service-desk IDs, base URLs) portable across dev/prod without a
  recipe edit.
- **Property names are exact-match, case-sensitive.** Always confirm the
  exact created name via `property_list` before assuming a binding
  resolves — a case mismatch (e.g. referencing `Anniversary Lookahead Days`
  when the user created `Anniversary lookahead days`) silently no-ops to
  whatever hardcoded fallback the recipe has, forever, with no error.
- **ruby() formulas with block syntax (`select { |r| ... }`) inside a mapped
  list-comprehension string are silently dropped at set time** — the builder
  accepts the call, then persists the field as `""` (confirmed 2026-09-12 on
  recipe 78672907). Simple ruby() with scalar/deep-path bindings inside a
  comprehension DOES persist. Fix: move correlation/lookup logic into a custom
  connector helper action (pure Ruby, full JSON) and keep comprehensions to
  plain f-string datapills over a parse step's output.
- **Brand-new step rejects the first set_input_field call** with "not available
  in the current input schema" even when the schema is correct; one
  `get_input_schema` call warms it and the identical retry succeeds (seen
  repeatedly 2026-09-12).
- **New connector actions need cache warming before AIRO can map their
  fields**: a fresh recipe_builder session sometimes resolves them; otherwise
  open the action once in the browser editor's action picker (fetches the
  fresh schema), then retry AIRO. Same trap family as the v32/v34 deferrals.

## recipe_builder_save creates a NEW recipe ID on every save (confirmed 2026-09-25)

- **Symptom:** In the Workday dev workspace (AIRO MCP), each `recipe_builder_save` call on an active builder session returned "Recipe created successfully" with a NEW recipe ID (82641535 → 82641537 → 82641538 → 82641544 for one probe recipe) instead of updating the previously saved asset. No error; easy to end up with several near-identical copies.
- **Workaround:** Treat the newest save as canonical; verify with `recipe_get` (check connection binding + latest steps on the newest ID). Rename superseded copies "(DUPLICATE - delete me)" via `recipe_builder_update_asset_metadata` and delete them with the public REST API: `DELETE /api/recipes/:id` (recipe must be stopped first; works with the workspace API token — confirmed 2026-09-30 on 14 duplicates). AIRO the MCP server has no delete tool, but the API does. Watch for this whenever a session does multiple save cycles.
