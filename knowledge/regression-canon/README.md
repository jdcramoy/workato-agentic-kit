# The regression canon

The attrition weapon: a bug that gets found once never happens twice.

## What a canon entry is

One JSON line per canonized bug:

```json
{"signature":"ruby-eval-empty-records-json","recipe_id":82272892,"kind":"empty-payload-guard","found_by":"watchdog","found":"2026-10-07","status":"open|fixed|tested","test_case_id":null,"line":"one sentence: the failure + the guard that now exists"}
```

- `signature` — short-kebab failure fingerprint. Watchdog uses this to
  recognize recurrence; dreamer uses it to avoid duplicate fixes.
- `status: open` (found, not fixed) → `fixed` (verified with a trace) →
  `tested` (a test case covers it). Nothing leaves canon.

## The loop

1. **watchdog** autopsies a failure → before reporting, greps
   `canon.jsonl` for a matching signature. Match = "canon violation"
   (a bug that returned) — P1 by definition, never a P2/P3.
   No match = new finding → handoff to the dreamer on the bus.
2. **dreamer (auto-dev)** fixes the clear ones. After trace-verified fix:
   canonize — append the canon line, and when a Workato test case can
   express the failure, create it on the recipe and link `test_case_id`.
3. **regression-nightly** already runs every estate test case; canonized
   cases ride that harness for free. The canon is the reason the harness
   keeps getting meaner every night.

## Rules

- Signatures are fingerprints of the FAILURE CLASS, not the stack trace
  (they must match the next instance of the same bug).
- Never rewrite canon lines; corrections are new lines (same rule as claims).
