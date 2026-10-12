# AIRO token and cost patterns

- Response size dominates call count. Prefer several narrow reads over one full
  recipe DSL, full job trace, connector operation catalog, or table dump.
- Parse IDs from supplied Workato URLs. Preserve returned IDs and handles.
- Fetch a step schema or datapill list once, then configure all relevant fields.
- Keep recipe-builder and Genie session IDs separate. Reuse a valid session;
  re-pull only after push because pushed sessions become stale.
- Verify a pushed asset through an independent compact `recipe_get` extraction.
- Never pass `columns` to `data_table_update` on a populated table.
- Keep `table_id` literal for data-table add/update actions.
- Delegate bulk read-only surveys to a cheaper agent and return only synthesis.
- Persist compact evidence: request, job IDs, snapshot version, backend duration,
  end-to-end duration, payload bytes, call count, and pass/fail.
- Fetch a documentation guide once per task and reuse it.
