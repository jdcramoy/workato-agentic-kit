---
name: workato-hot-swap
description: >-
  Safely edit and redeploy a RUNNING Workato recipe (hot path, scheduler, or
  recipe function) with proof at every step: map the branch in the oversized
  DSL, stop via REST, AIRO edit/push, start via REST, verify the running flag
  (starts can silently no-op), then prove with a live run — force-run for
  schedulers, Orca editor Test for recipe functions, a real call for skills.
  Use any time you must change a recipe that is currently running, especially
  mid-pilot/production-adjacent work where downtime and silent no-ops matter.
---


Mandatory at this skill's core: each stop, push, and start opens a prediction (`python3 ~/.claude/knowledge/scripts/predict.py open --action ... --expect ...`) and closes it against the observed state. The whole point of hot-swap is that silent no-ops exist; predictions are how the no-op becomes a named, learned failure mode.

# Workato Hot Swap

Editing a running recipe is a five-phase discipline. Skipping a phase is how
you get "green" dashboards over dead recipes.

## Phase 0 — Map before you cut (oversized DSL)

`recipe_get` / `recipe_builder_pull` / `recipe_builder_show` on a large recipe
(>~100K chars) does NOT return inline — the result is saved to
`~/.claude/projects/<proj>/<session>/tool-results/mcp-workato-*.txt`.
Grep that file; never read it end-to-end:

```bash
F=<saved tool-results path>
grep -n "# step: \|flow_id=\"<callee>\"\|OUTCOME_STRING" "$F" | head -40
sed -n '<start>,<end>p' "$F" | cut -c1-200   # window reads with truncation guard
```

Find exact step numbers and sibling call-site envelopes BEFORE add_step —
post-insert renumbering is automatic, and a `recipe_builder_show` re-save is
the source of truth for new numbers. Do not hand-compute shifts beyond ±one
insert; re-grep.

## Phase 1 — Stop (REST, verified)

```bash
curl -s -X PUT "$WORKATO_BASE_URL/api/recipes/<id>/stop" \
  -H "Authorization: Bearer $WORKATO_API_TOKEN"
```

AIRO `recipe_builder_push` refuses running recipes ("can't modify running
recipe"). Stopping a live serving recipe = downtime starts NOW — have the
edit staged in a pulled session first when minutes matter.

## Phase 2 — Edit + push (AIRO session)

- Pull first (`recipe_builder_pull`) — never edit from memory.
- Insert fail-open telemetry/side-effects as their own `error_handling`
  (retries=0) monitor block + child action — never inside the primary
  try/monitor of the operation they observe (a telemetry failure must not
  convert a success into the failure path).
- For `call_recipe` steps: set `flow_id` FIRST, then `parameters` in a
  second call — the parameters schema materializes only after flow_id.
- Copy parameter envelopes verbatim from a sibling call site in the same
  recipe (grep the pull file for the callee's flow_id).

## Phase 3 — Start (REST) AND VERIFY

```bash
curl -s -X PUT "$WORKATO_BASE_URL/api/recipes/<id>/start" -H "Authorization: Bearer $WORKATO_API_TOKEN"
sleep 3
curl -s "$WORKATO_BASE_URL/api/recipes/<id>" -H "Authorization: Bearer $WORKATO_API_TOKEN" | jq .running
```

Starts/stops can silently no-op (especially right after a browser-side
action). The `running` flag re-read is mandatory. A stopped recipe with a
green-looking board is the exact failure this skill exists to prevent.

## Phase 4 — Prove with a LIVE run (never "it should work")

Pick by trigger type:
- **Scheduler**: `wt recipes force-run <id>` → job handle → AIRO `job_get`
  for the step trace. (force-run is scheduler-only; 422 otherwise.)
- **Recipe function**: Orca browser → recipe page → caret after "Start
  recipe" → real-click "Test recipe" → the Add-trigger-data modal fields are
  CodeMirror-backed: dispatch mousedown/mouseup/click on the field's
  `.text-field`, focus the revealed textarea, then
  `fieldEl.querySelector('.CodeMirror').CodeMirror.setValue(v)`; verify with
  getValue(); submit with `orca click --element <ref>`. Native value-setter
  and synthetic keypress do NOT register. Confirm the job via the API, then
  `job_get` for content.
- **Skill/public MCP surface**: make the real call through the real client
  and verify the side effect (e.g., the telemetry row) landed.

Verify the CONTENT, not the status: a green job with silently-empty results
is a false pass (field-ID scan-parse bug class). Read the actual output step.

## Phase 5 — Sweep the class, then close the books

- Fix bug CLASSES: grep sibling recipes/steps for the same shape (same op
  token, same regex key assumption, same missing recorder).
- Instrument the FULL outcome matrix: success, rejection, and failure — not
  just the failure that hurt.
- Live-fire ALERT paths, not just quiet paths (a monitor whose alert branch
  never ran is unverified).
- Deposit traps into `~/.claude/knowledge/domains/workato-platform.md` and
  update project memory before ending the session.

## Traps this skill encodes (all learned live)

- `get_records` default output keys records by FIELD ID; scan-parse Ruby must
  use `output_format: field_name_to_value` + name-keyed regexes (name keys
  survive `data_table_update` field-ID regeneration).
- `delete_records_by_condition` rejects `op_default: "is"` at runtime — use
  `eq` (picklist: eq/ne/isnull/isnotnull/starts_with).
- `recipe_get` "Inconsistencies detected" can be a STALE snapshot from a
  connector-release window — verify against live `get_datapills` first.
- Editor sessions go obsolete after AIRO pushes — fresh tab + Edit takeover.
- Never Playwright for UI automation here — Orca browser only (Josh directive
  2026-10-06); `pkill -f playwright-mcp-profile` kills the MCP server itself.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [RecipeOps - Stop recipe action](../../kb-corpus/docs/en/connectors/recipeops/actions/stop-recipe.md)
- [RecipeOps - Recipe stopped by Workato trigger](../../kb-corpus/docs/en/connectors/recipeops/triggers/recipe-stopped-by-workato.md)
- [Canvas](../../kb-corpus/docs/en/canvas.md)
- [More control and less stress with Cancel Job](../../kb-corpus/changelog/cancel-job-button.md)
<!-- kb-bridges:end -->
