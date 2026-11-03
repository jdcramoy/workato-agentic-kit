
## Ruby-snippet code_input silent drop + catch-block children (BTG metrics-rollup build, 2026-11-01)

- **AIRO silently drops `code_input.data` on custom-code snippet steps**: `set_input_field`
  on `code_input.data` (whole-object, mode dict) RENDERS correctly in the response and
  persists `{}` on the wire — start-validation then fails `code_input.data can't be blank`.
  Read-back caught it. Two attempts, same result. Fix: eliminate snippet inputs entirely
  (input-less snippet) or raw-PUT. Snippet OUTPUT schema pills resolve fine.
- **Adding steps to a monitor's CATCH block**: `add_step` with `parent=<monitor#>` lands in
  the TRY body; `move_step` with `new_parent=<catch#>` fails "Parent step not found".
  WORKS: `add_step(parent=<catch_block_number>, position=<catch_number+1>)` — the catch
  block IS addressable as a parent for ADD (not move), with position strictly greater.
- **Mixed operator types in one static `filters` array** (e.g. date-gte + string-isnotnull):
  uniform one-element mode requires ALL keys in every row; null values fail ("value must be
  a string"); fill unused keys with `""` and reuse the datapill string in unused value slots.
- **Data-table search filters include SYSTEM columns**: "Created time" field id
  `a5612739-5401-4ae7-bd07-782c1a6fb2d1` is filterable (gte/lt) even when the table has no
  real created_at column — the correct 7-day filter path on tables whose real date column
  is never populated (e.g. Action Ledger's `created_at` is null on every row).
- **`records.size` is a native pill** ("List size", integer) — no formula needed for counts.
- **`upsert_record` works by primary_field_id** (underscored field UUID key in `parameters`);
  second run updates rather than duplicates — proven live (5 rows after 2 runs).
