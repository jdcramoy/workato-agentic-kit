---
name: workato-custom-action-schema
description: Resolve a Workato custom-connector action's schema before mapping datapills in a recipe. Use when building or editing recipe steps that call a custom (SDK or ad-hoc HTTP) connector action, when datapill mapping fails with DatapillSourceBlockNotFound or "input.schema not available", when a fresh custom action exposes no pills, or when the user asks to analyze a connector action's schema.
---

# Workato Custom Action Schema

A custom connector action has **no datapill schema until the action has executed
once** — the platform derives its input/output schema from a captured sample
response. Building recipe steps against a fresh or edited action fails with
`[datapill:DatapillSourceBlockNotFound]` and fields like `input.schema`,
`output`, `response_type` reported "not available". Do not guess mappings and do
not fall back to "skip and tell the user to configure manually"; run this loop
first.

## Workflow

1. **Resolve** the connector and its actions with the bundled
   `scripts/workato_action_schema.py`. It authenticates to the Workato
   Developer API with `WORKATO_TOKEN` or `--token` (the workspace token is
   normally in the keychain under the `workato-platform-cli` service; the
   account attribute matches your Workato CLI profile name — list it with
   `security find-generic-password -s workato-platform-cli` and add `-a
   <account> -w` to print the token), lists custom connectors, and reads the
   connector's SDK code to report each action's `input_fields`,
   `output_fields`, and `sample_output` presence and source. Never guess IDs.
2. **Probe** when the action reports no schema (typical for a fresh ad-hoc
   HTTP action). The Developer API has no action-test endpoint, so run the
   action once through a throwaway probe recipe (build a one-step recipe that
   calls the action with sample input, run it once, then stop it), or via the
   project's existing probe tooling if available. This makes the platform
   capture the sample response that defines the schema.
3. **Read back** the schema by re-running the wrapper after the probe; the
   action should now report its fields. Map the recipe step's datapills from
   that output in the same turn. Re-run after any action edit — editing an
   action invalidates its captured schema, so re-probe and re-map.
4. If a probe fails (auth, API error, schema still empty after a successful
   probe run), report the exact error and stop. Do not improvise field names.

## Preview by default

Without `--execute`, the wrapper previews the exact API calls and sends nothing.
Add `--execute` only when the task explicitly requires resolving the action's
schema now.

## Commands

```bash
# Preview: list custom connectors
python3 scripts/workato_action_schema.py list

# Preview: resolve one connector's actions (read-only GETs)
python3 scripts/workato_action_schema.py resolve --connector-id 1088132 --action-name get_object

# Execute: list every action in a connector with its schema presence
python3 scripts/workato_action_schema.py resolve --connector-id 1088132 --execute

# Execute: scope by connector name, one action
python3 scripts/workato_action_schema.py resolve \
  --connector-name click_up_connector_5830162_1756396686 \
  --action-name get_object --execute
```

Run commands from this skill directory, or use the script's absolute path. The
wrapper exits nonzero when the connector or action cannot be resolved, the code
cannot be fetched, or the action has no schema yet (which means: probe first,
then re-run). Surface that error instead of inventing field names.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [SDK reference — actions](../../kb-corpus/docs/en/developing-connectors/sdk/sdk-reference/actions.md)
- [SDK reference — custom action](../../kb-corpus/docs/en/developing-connectors/sdk/sdk-reference/custom-action.md)
- [SDK guide — building actions](../../kb-corpus/docs/en/developing-connectors/sdk/guides/building-actions.md)
- [Custom actions overview](../../kb-corpus/docs/en/developing-connectors/custom-actions.md)
<!-- kb-bridges:end -->
