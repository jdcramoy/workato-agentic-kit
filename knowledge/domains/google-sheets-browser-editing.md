# Google Sheets browser editing via Playwright — traps

Confirmed 2026-10-06 while filling JIRA links in the HR Genie Skills
Repository sheet (1GOn_nrmjk19_XiHrC3JTF_9Zi_sygAIc).

## Reading sheet data

- Sheets renders cells in canvas — accessibility snapshots show no cell data.
- Read the whole sheet instead via same-origin fetch from the signed-in page:
  `fetch('/spreadsheets/d/<ID>/export?format=csv&gid=<GID>')` in
  `browser_evaluate`/`browser_run_code_unsafe`. Fast, filter-independent
  (returns ALL rows incl. filter-hidden), and doubles as write verification.
- Parse the CSV with a real quote-aware parser, not naive `.split(',')` —
  long Notes columns contain embedded commas/newlines.

## Editing cells

- Works: click Name box (`#t-name-box`) → type ref (e.g. `J44`) → Enter →
  `page.keyboard.type(value, {delay: 30})` → Enter. Committing opens no
  dialogs; autocomplete hasn't caused wrong values with exact key strings.
- **Trap — filter-hidden rows:** with a basic filter active, navigating via
  the Name box to a HIDDEN row silently skips to the next visible row (the
  Name box then reads that visible ref, e.g. asked J44 → shows J45). Any
  keyboard typing + Enter commits into the WRONG row. Always read back
  `inputValue()` of the Name box after navigating, and verify every intended
  cell (plus its neighbors) via CSV re-export after writing. `Escape` cancels
  an uncommitted cell edit safely.
- Watch neighboring cells after a misdirected commit — the overwrite is
  silent and easy to miss if you only check the target row.

## Playwright profile lock

- `Browser is already in use for .playwright-mcp-profile` = a stale
  Playwright-driven Chrome holds the profile (many orphaned `playwright-mcp`
  server processes accumulate across sessions). Fix: kill the main Chrome
  process (`Google Chrome ... --user-data-dir=...playwright-mcp-profile`,
  non-Helper) — lock frees immediately; Google login in the profile persists.

## Related (KB bridges)

<!-- kb-bridges:v1 begin -->
- [Workato connectors - Google Sheets New/updated row in sheet in My Drive trigger (real-time)](../../kb-corpus/docs/en/connectors/google-sheets/trigger-new-updated-row.md)
- [Configure Google Sheets as your data pipeline source](../../kb-corpus/docs/en/data-orchestration/data-pipeline-recipe/configure-google-sheets.md)
- [Workato connectors - Google Sheets Update row action](../../kb-corpus/docs/en/connectors/google-sheets/action-update-row-v4.md)
- [Workato connectors - Google Speech to Text - Convert short speech to text action](../../kb-corpus/docs/en/connectors/google-speech-to-text/action-short-speech.md)
<!-- kb-bridges:end -->
